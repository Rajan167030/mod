"""
Planning copilot: answers questions about a scenario in plain language using Claude with
read-only tools over this application's own data. It can run what-if simulations but can
never change a plan - adopting and approving stay with people on the existing screens.
"""
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import anthropic
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError, NotFoundError, ValidationError
from app.models.all_models import (
    Assignment,
    Resource,
    ResourceAvailability,
    Scenario,
    ScheduleVersion,
    Task,
    User,
)
from app.models.replay_models import ReplaySession
from app.models.weather_models import Location
from app.services.conflict_service import check_schedule_conflicts
from app.services.weather_impact import exposure, site_hours
from app.services.weather_rules_service import get_alerts_for_scenario

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8
CONVERSATION_TTL = timedelta(hours=2)
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = """You are the planning copilot inside AirOps, a training prototype for scheduling air operations \
(airlift, casualty evacuation, reconnaissance and support flights) across a set of sites. All aircraft, sites and \
tasks are fictional training data; the weather at the site coordinates is live, except anything marked as an \
exercise inject, which is simulated.

Help the planner understand the current situation and the consequences of options. Use the tools to look things \
up rather than guessing, and quote the figures they return. Times are UTC; write them like 1430Z.

You cannot change the schedule. When the user wants to act, point them to "Courses of action" to generate and \
adopt a plan, and to "Review", where a reviewer approves it. Say so plainly rather than implying you have done it.

Keep answers short and concrete: lead with the answer, then the two or three facts that support it. If the data \
does not answer the question, say what is missing."""


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _z(dt: Optional[datetime]) -> Optional[str]:
    return _utc(dt).strftime("%d %b %H%MZ") if dt else None


# ---------------------------------------------------------------------------
# Tools (read-only; what-if runs in a savepoint and is rolled back)
# ---------------------------------------------------------------------------

def _active_version(db: Session, scenario_id: str) -> Optional[ScheduleVersion]:
    return (
        db.query(ScheduleVersion)
        .filter(ScheduleVersion.scenario_id == scenario_id, ScheduleVersion.status == "APPROVED")
        .order_by(ScheduleVersion.version_number.desc())
        .first()
    )


def _now_for(db: Session, scenario_id: str) -> datetime:
    """The scenario's operational 'now': the simulated clock in an exercise, else real time."""
    from app.services.replay_service import sim_now

    session = db.query(ReplaySession).filter(ReplaySession.scenario_id == scenario_id).first()
    return sim_now(session) if session else datetime.now(timezone.utc)


def tool_get_situation(db: Session, scenario_id: str, _: Dict[str, Any]) -> Dict[str, Any]:
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).one()
    version = _active_version(db, scenario_id)
    now = _now_for(db, scenario_id)
    check = check_schedule_conflicts(db, version.id) if version else None
    tasks = {t.id: t for t in db.query(Task).filter(Task.scenario_id == scenario_id)}
    assigned = {a.task_id for a in db.query(Assignment).filter(Assignment.schedule_version_id == version.id)} if version else set()
    aircraft = []
    for r in db.query(Resource).filter(Resource.scenario_id == scenario_id):
        blocks = [
            f"{_z(a.start_at)}–{_z(a.end_at)}"
            for a in db.query(ResourceAvailability).filter(ResourceAvailability.resource_id == r.id, ResourceAvailability.available.is_(False))
            if _utc(a.end_at) > now
        ]
        aircraft.append({
            "name": r.name, "type": r.resource_type, "status": r.status,
            "qualifications": (r.metadata_json or {}).get("qualifications", []),
            "unavailable": blocks,
        })
    return {
        "scenario": scenario.name,
        "now": _z(now),
        "active_plan_version": version.version_number if version else None,
        "tasks_total": len(tasks),
        "tasks_without_slot": [{"name": tasks[t].name, "priority": tasks[t].priority} for t in tasks if t not in assigned],
        "rule_conflicts": [{"rule": c.code, "aircraft": c.resource_name, "detail": c.explanation} for c in (check.conflicts if check else [])][:10],
        "aircraft": aircraft,
        "pending_proposals": db.query(ScheduleVersion).filter(ScheduleVersion.scenario_id == scenario_id, ScheduleVersion.status == "PROPOSED").count(),
    }


def tool_get_weather(db: Session, scenario_id: str, _: Dict[str, Any]) -> Dict[str, Any]:
    alerts = get_alerts_for_scenario(db, scenario_id)
    now = _now_for(db, scenario_id)
    sites: Dict[str, Dict[str, Any]] = {}
    for a in alerts.alerts:
        if a.variable == "all":
            sites.setdefault(a.location_name, {"no_data": True})
            continue
        if _utc(a.forecast_timestamp) < now - timedelta(hours=1):
            continue
        s = sites.setdefault(a.location_name, {"critical_hours": [], "warning_hours": [], "causes": set(), "exercise_inject": False})
        (s["critical_hours"] if a.severity == "CRITICAL" else s["warning_hours"]).append(_utc(a.forecast_timestamp).strftime("%H%MZ"))
        s["causes"].add(a.variable.replace("_", " "))
        s["exercise_inject"] |= a.source == "exercise"
    for s in sites.values():
        if "causes" in s:
            s["causes"] = sorted(s["causes"])
            s["critical_hours"] = s["critical_hours"][:12]
            s["warning_hours"] = s["warning_hours"][:12]
    quiet = [loc.name for loc in db.query(Location).filter(Location.scenario_id == scenario_id) if loc.name not in sites]
    return {"now": _z(now), "data_freshness": alerts.freshness_summary, "sites_with_limits": sites, "sites_within_limits": quiet}


def _find_task(db: Session, scenario_id: str, text: str) -> Task:
    q = text.strip().lower()
    tasks = db.query(Task).filter(Task.scenario_id == scenario_id).all()
    exact = [t for t in tasks if t.name.lower().startswith(q) or t.name.lower() == q]
    match = exact or [t for t in tasks if q in t.name.lower()]
    if not match:
        raise ValidationError(f"No task matches '{text}'.")
    return match[0]


def tool_list_tasks(db: Session, scenario_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    version = _active_version(db, scenario_id)
    plan = {a.task_id: a for a in db.query(Assignment).filter(Assignment.schedule_version_id == version.id)} if version else {}
    resources = {r.id: r.name for r in db.query(Resource).filter(Resource.scenario_id == scenario_id)}
    sites = {loc.id: loc.name for loc in db.query(Location).filter(Location.scenario_id == scenario_id)}
    out = []
    for t in db.query(Task).filter(Task.scenario_id == scenario_id).order_by(Task.earliest_start):
        if args.get("priority") and t.priority != args["priority"]:
            continue
        a = plan.get(t.id)
        out.append({
            "name": t.name, "priority": t.priority, "minutes": t.duration_minutes,
            "window": f"{_z(t.earliest_start)} to {_z(t.latest_finish)}",
            "site": sites.get(t.location_id),
            "requires": [r.requirement_value for r in t.requirements],
            "planned": f"{resources.get(a.resource_id)} at {_z(a.start_at)}" if a else None,
        })
    return {"tasks": out}


def tool_explain_task(db: Session, scenario_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Why a task is (or is not) where it is: qualification, availability and weather facts."""
    t = _find_task(db, scenario_id, args["task"])
    version = _active_version(db, scenario_id)
    a = db.query(Assignment).filter(Assignment.schedule_version_id == version.id, Assignment.task_id == t.id).first() if version else None
    needed = [r.requirement_value for r in t.requirements if r.requirement_type == "QUALIFICATION"]
    start, end = _utc(t.earliest_start), _utc(t.latest_finish)
    candidates = []
    for r in db.query(Resource).filter(Resource.scenario_id == scenario_id):
        quals = (r.metadata_json or {}).get("qualifications", [])
        missing = [q for q in needed if q not in quals]
        blocked = [
            f"{_z(b.start_at)}–{_z(b.end_at)}"
            for b in db.query(ResourceAvailability).filter(ResourceAvailability.resource_id == r.id, ResourceAvailability.available.is_(False))
            if _utc(b.start_at) < end and start < _utc(b.end_at)
        ]
        if missing:
            continue
        busy = []
        if version:
            for other in db.query(Assignment).filter(Assignment.schedule_version_id == version.id, Assignment.resource_id == r.id):
                if other.task_id != t.id and _utc(other.start_at) < end and start < _utc(other.end_at):
                    busy.append(_z(other.start_at))
        candidates.append({"aircraft": r.name, "status": r.status, "unavailable_in_window": blocked, "other_sorties_in_window": busy})
    site = db.query(Location).filter(Location.id == t.location_id).first() if t.location_id else None
    hours = site_hours(db, scenario_id).get(t.location_id, {}) if t.location_id else {}
    limits = sorted(f"{h:%H%MZ} {s}" for h, s in hours.items() if start <= h < end)
    return {
        "task": t.name, "priority": t.priority, "minutes": t.duration_minutes,
        "window": f"{_z(start)} to {_z(end)}", "site": site.name if site else None, "requires": needed,
        "planned": {
            "aircraft": db.get(Resource, a.resource_id).name,
            "start": _z(a.start_at),
            "end": _z(a.end_at),
            "weather": exposure(_utc(a.start_at), _utc(a.end_at), hours),
        } if a else None,
        "qualified_aircraft": candidates,
        "weather_limit_hours_at_site_in_window": limits,
    }


def tool_what_if_unavailable(db: Session, scenario_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Simulate an aircraft becoming unavailable and compare the plans the optimiser would produce. Nothing is kept."""
    from app.services.coa_service import generate_courses_of_action

    version = _active_version(db, scenario_id)
    if not version:
        raise ValidationError("This scenario has no approved plan to test against.")
    resource = db.query(Resource).filter(Resource.scenario_id == scenario_id, Resource.name.ilike(args["aircraft"].strip())).first()
    if not resource:
        names = ", ".join(r.name for r in db.query(Resource).filter(Resource.scenario_id == scenario_id))
        raise ValidationError(f"No aircraft called '{args['aircraft']}'. Aircraft: {names}.")
    now = _now_for(db, scenario_id)
    start = now + timedelta(hours=float(args.get("starts_in_hours") or 0))
    end = start + timedelta(hours=float(args["hours"]))
    user = db.query(User).filter(User.id == version.created_by).first() or db.query(User).first()

    # Fetch weather first so nothing inside the simulation touches the network or writes history
    get_alerts_for_scenario(db, scenario_id)
    savepoint = db.begin_nested()
    try:
        db.add(ResourceAvailability(resource_id=resource.id, start_at=start, end_at=end, available=False))
        db.flush()
        before = check_schedule_conflicts(db, version.id)
        coa = generate_courses_of_action(
            db, version.id, user, include_weather=True, time_limit_seconds=4, freeze_at=now, remember=False,
        )
    finally:
        savepoint.rollback()

    return {
        "simulated": f"{resource.name} unavailable {_z(start)}–{_z(end)} (not saved)",
        "current_plan_conflicts_if_nothing_changes": before.conflict_count,
        "plans": [
            {
                "plan": c.label,
                "suggested": c.recommended,
                "same_as": c.same_as,
                **({
                    "tasks_dropped": c.metrics.unassigned, "critical_dropped": c.metrics.unassigned_critical,
                    "total_delay_min": c.metrics.total_delay_minutes, "aircraft_swaps": c.metrics.reassigned,
                    "retimed": c.metrics.retimed, "sorties_in_critical_weather": c.metrics.weather_exposed_critical,
                    "dropped_tasks": [o.task_name for o in c.tasks if not o.resource_id][:6],
                } if c.metrics else {"status": c.solver_status}),
            }
            for c in coa.courses
        ],
        "suggestion_reason": coa.recommendation_reason,
    }


def _schema(props: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


TOOLS: List[Dict[str, Any]] = [
    {
        "name": "get_situation",
        "description": "Current operational picture for the scenario: the clock, the active plan version, tasks with no slot, rule conflicts, and each aircraft's status, qualifications and upcoming unavailability.",
        "input_schema": _schema({}, []),
        "strict": True,
    },
    {
        "name": "get_weather",
        "description": "Forecast weather limits per site from now on: which hours are at warning or critical level and why. Marks simulated exercise injects.",
        "input_schema": _schema({}, []),
        "strict": True,
    },
    {
        "name": "list_tasks",
        "description": "All tasks with priority, time window, site, required qualification and where the active plan puts them. Optionally filter by priority.",
        "input_schema": _schema(
            {"priority": {"type": ["string", "null"], "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW", None]}},
            ["priority"],
        ),
        "strict": True,
    },
    {
        "name": "explain_task",
        "description": "Explain one task's placement: which aircraft are qualified, whether each is unavailable or busy during the task's window, and the weather limits at its site. Use for 'why is X late / unassigned / on that aircraft'. Accepts a task code like WL-07 or part of the name.",
        "input_schema": _schema({"task": {"type": "string"}}, ["task"]),
        "strict": True,
    },
    {
        "name": "what_if_unavailable",
        "description": "Simulate an aircraft becoming unavailable (from now, or after a delay, for a number of hours) and compare the plans the optimiser would produce. Nothing is saved; the real schedule is unchanged.",
        "input_schema": _schema(
            {
                "aircraft": {"type": "string", "description": "Aircraft name, e.g. C-130-Alpha"},
                "hours": {"type": "number", "description": "How long it is unavailable"},
                "starts_in_hours": {"type": ["number", "null"], "description": "Hours from now until it becomes unavailable; null for now"},
            },
            ["aircraft", "hours", "starts_in_hours"],
        ),
        "strict": True,
    },
]

HANDLERS: Dict[str, Callable[[Session, str, Dict[str, Any]], Dict[str, Any]]] = {
    "get_situation": tool_get_situation,
    "get_weather": tool_get_weather,
    "list_tasks": tool_list_tasks,
    "explain_task": tool_explain_task,
    "what_if_unavailable": tool_what_if_unavailable,
}

TOOL_LABELS = {
    "get_situation": "Checked the current situation",
    "get_weather": "Checked site weather",
    "list_tasks": "Listed tasks",
    "explain_task": "Explained a task",
    "what_if_unavailable": "Ran a what-if",
}


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

@dataclass
class _Conversation:
    scenario_id: str
    user_id: str
    # Append-only: assistant turns are stored exactly as returned so thinking blocks stay valid
    messages: List[Any] = field(default_factory=list)
    touched: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)


_conversations: Dict[str, _Conversation] = {}
_conv_guard = threading.Lock()
_client: Optional[anthropic.Anthropic] = None


class CopilotUnavailable(AppError):
    def __init__(self, detail: str):
        super().__init__(status_code=503, detail=detail, error_code="COPILOT_UNAVAILABLE")


_NOT_CONFIGURED = "The copilot needs Claude API credentials on the server. Set ANTHROPIC_API_KEY in backend/.env and restart."


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        try:
            client = anthropic.Anthropic()
        except anthropic.AnthropicError as e:
            raise CopilotUnavailable(_NOT_CONFIGURED) from e
        # The client can be built without credentials and only fail on the first request
        if not (client.api_key or getattr(client, "auth_token", None)):
            raise CopilotUnavailable(_NOT_CONFIGURED)
        _client = client
    return _client


def is_configured() -> bool:
    try:
        _get_client()
        return True
    except CopilotUnavailable:
        return False


def _conversation(conversation_id: Optional[str], scenario_id: str, user: User) -> tuple[str, _Conversation]:
    now = time.time()
    with _conv_guard:
        for k in [k for k, c in _conversations.items() if now - c.touched > CONVERSATION_TTL.total_seconds()]:
            del _conversations[k]
        if conversation_id and conversation_id in _conversations:
            conv = _conversations[conversation_id]
            if conv.user_id != user.id or conv.scenario_id != scenario_id:
                raise ValidationError("That conversation belongs to another user or scenario. Start a new one.")
            return conversation_id, conv
        new_id = str(uuid.uuid4())
        _conversations[new_id] = _Conversation(scenario_id=scenario_id, user_id=user.id)
        return new_id, _conversations[new_id]


def _run_tool(db: Session, scenario_id: str, name: str, args: Dict[str, Any]) -> tuple[str, bool]:
    handler = HANDLERS.get(name)
    if not handler:
        return f"Unknown tool '{name}'.", True
    try:
        return json.dumps(handler(db, scenario_id, args), default=str), False
    except (ValidationError, NotFoundError) as e:
        return e.detail, True
    except Exception as e:  # tool failures go back to the model, not to the user as a 500
        logger.exception("Copilot tool %s failed", name)
        db.rollback()
        return f"The tool failed: {e}", True


def chat(db: Session, user: User, scenario_id: str, message: str, conversation_id: Optional[str]) -> Dict[str, Any]:
    if not db.query(Scenario).filter(Scenario.id == scenario_id).first():
        raise NotFoundError("Scenario", scenario_id)
    client = _get_client()
    conv_id, conv = _conversation(conversation_id, scenario_id, user)
    steps: List[Dict[str, Any]] = []

    with conv.lock:
        conv.touched = time.time()
        conv.messages.append({"role": "user", "content": message})
        response = None
        for _ in range(MAX_TOOL_ROUNDS):
            try:
                response = client.beta.messages.create(
                    model=settings.COPILOT_MODEL,
                    max_tokens=16000,
                    system=SYSTEM_PROMPT,
                    tools=TOOLS,
                    messages=conv.messages,
                    thinking={"type": "adaptive"},
                    output_config={"effort": settings.COPILOT_EFFORT},
                    # On a policy decline, let the API retry on Anthropic's recommended fallback model
                    betas=[FALLBACK_BETA],
                    extra_body={"fallbacks": "default"},
                )
            except anthropic.AuthenticationError as e:
                conv.messages.pop()
                raise CopilotUnavailable("The Claude API rejected the server's credentials. Check ANTHROPIC_API_KEY.") from e
            except anthropic.RateLimitError as e:
                conv.messages.pop()
                raise CopilotUnavailable("The copilot is rate limited. Try again in a minute.") from e
            except anthropic.APIConnectionError as e:
                conv.messages.pop()
                raise CopilotUnavailable("Could not reach the Claude API from the server.") from e

            conv.messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason != "tool_use":
                break

            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                output, is_error = _run_tool(db, scenario_id, block.name, dict(block.input))
                steps.append({"tool": block.name, "label": TOOL_LABELS.get(block.name, block.name), "input": block.input, "error": is_error})
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output, "is_error": is_error})
            conv.messages.append({"role": "user", "content": results})
        else:
            steps.append({"tool": None, "label": "Stopped after the tool limit", "input": {}, "error": True})

    stop = response.stop_reason if response else None
    text = "\n\n".join(b.text for b in (response.content if response else []) if b.type == "text").strip()
    if stop == "refusal":
        text = "I can't help with that request. Try rephrasing it as a planning question about this scenario."
    elif stop == "max_tokens":
        text += "\n\n(Answer cut short.)"
    elif not text:
        text = "I looked into it but have nothing to add. Try asking more specifically."
    return {"conversation_id": conv_id, "reply": text, "steps": steps, "stop_reason": stop, "model": getattr(response, "model", None)}
