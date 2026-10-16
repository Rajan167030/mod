"""
Courses of Action (COA): solve the same problem under several planning intents and
compare the resulting plans side by side. Nothing is written to the database until a
plan is adopted, and an adopted plan is only a PROPOSAL that still needs human approval.
"""
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.engine.solver import ScheduleSolverResult, solve_schedule_scenario
from app.models.all_models import Task, User
from app.schemas.coa_schemas import (
    CoaMetrics,
    CoaSetResponse,
    CoaTaskOutcome,
    CourseOfAction,
)
from app.services.proposal_service import SolverInputs, load_solver_inputs, validate_without_saving
from app.services.weather_impact import exposure, site_hours, solver_weather_kwargs, uses_site_model
from app.services.weather_rules_service import get_alerts_for_scenario

HOUR = timedelta(hours=1)
COA_TTL = timedelta(minutes=30)
MAX_CACHED_SETS = 20
RETIME_TOLERANCE_SECONDS = 60


@dataclass(frozen=True)
class Profile:
    key: str
    label: str
    intent: str
    weights: Dict[str, int]
    priority_weights: Optional[Dict[str, int]] = None
    delay_by_priority: bool = False
    # "strict" treats forecast WARNING hours like CRITICAL ones (never fly through them)
    weather_mode: str = "normal"


PROFILES: List[Profile] = [
    Profile(
        key="FASTEST",
        label="Fastest execution",
        intent="Start every task as early as possible. Accepts more aircraft and crew swaps to get there.",
        weights=dict(weight_unassigned=10000, weight_delay=40, weight_churn=5, weight_makespan=2),
    ),
    Profile(
        key="STABLE",
        label="Least disruption",
        intent="Keep aircraft and crews on the tasks they were briefed for; move times instead of people.",
        weights=dict(weight_unassigned=10000, weight_delay=1, weight_churn=800, weight_makespan=0),
    ),
    Profile(
        key="SAFEST",
        label="Weather-safe",
        intent="Never fly a task through a forecast warning or critical hour at its site. Accepts delay or dropped low-priority work.",
        weights=dict(weight_unassigned=10000, weight_delay=5, weight_churn=50, weight_makespan=1),
        weather_mode="strict",
    ),
    Profile(
        key="PRIORITY",
        label="Critical missions first",
        intent="Fly CRITICAL and HIGH tasks first and earliest, even if lower-priority tasks slip or drop.",
        weights=dict(weight_unassigned=10000, weight_delay=10, weight_churn=20, weight_makespan=1),
        priority_weights={"CRITICAL": 100, "HIGH": 25, "MEDIUM": 3, "LOW": 1},
        delay_by_priority=True,
    ),
]


@dataclass
class _StoredSet:
    response: CoaSetResponse
    baseline_id: str
    results: Dict[str, ScheduleSolverResult]
    created_by: str
    expires: datetime = field(default_factory=lambda: datetime.now(timezone.utc) + COA_TTL)


_sets: Dict[str, _StoredSet] = {}
_sets_lock = threading.Lock()


def _remember(entry: _StoredSet) -> None:
    now = datetime.now(timezone.utc)
    with _sets_lock:
        for k in [k for k, v in _sets.items() if v.expires < now]:
            del _sets[k]
        while len(_sets) >= MAX_CACHED_SETS:
            del _sets[min(_sets, key=lambda k: _sets[k].expires)]
        _sets[entry.response.coa_set_id] = entry


def get_stored_set(coa_set_id: str) -> _StoredSet:
    with _sets_lock:
        entry = _sets.get(coa_set_id)
    if not entry or entry.expires < datetime.now(timezone.utc):
        raise NotFoundError("Course-of-action set (expired or unknown)", coa_set_id)
    return entry


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _weather_hours(db: Session, scenario_id: str) -> Dict[datetime, str]:
    """Worst alert severity per forecast hour across the scenario's sites."""
    hours: Dict[datetime, str] = {}
    for a in get_alerts_for_scenario(db, scenario_id).alerts:
        if a.severity not in ("CRITICAL", "WARNING") or a.variable == "all":
            continue
        h = _as_utc(a.forecast_timestamp).replace(minute=0, second=0, microsecond=0)
        if hours.get(h) != "CRITICAL":
            hours[h] = a.severity
    return hours


def _outcomes(
    inputs: SolverInputs,
    result: ScheduleSolverResult,
    hours: Dict[Optional[str], Dict[datetime, str]],
) -> List[CoaTaskOutcome]:
    resources = {r.id: r for r in inputs.resources}
    base = {a.task_id: a for a in inputs.baseline_assignments}
    plan = {a["task_id"]: a for a in result.assignments}
    out: List[CoaTaskOutcome] = []

    for t in inputs.tasks:
        p = plan.get(t.id)
        b = base.get(t.id)
        if not p:
            out.append(CoaTaskOutcome(
                task_id=t.id, task_name=t.name, priority=t.priority,
                change="DROPPED" if b else "UNASSIGNED",
            ))
            continue
        if not b:
            change = "NEW"
        elif b.resource_id != p["resource_id"]:
            change = "REASSIGNED"
        elif abs((_as_utc(b.start_at) - _as_utc(p["start_at"])).total_seconds()) > RETIME_TOLERANCE_SECONDS:
            change = "RETIMED"
        else:
            change = "UNCHANGED"
        out.append(CoaTaskOutcome(
            task_id=t.id,
            task_name=t.name,
            priority=t.priority,
            resource_id=p["resource_id"],
            resource_name=resources[p["resource_id"]].name if p["resource_id"] in resources else None,
            start_at=p["start_at"],
            end_at=p["end_at"],
            delay_minutes=int((_as_utc(p["start_at"]) - _as_utc(t.earliest_start)).total_seconds() // 60),
            change=change,
            weather_exposure=exposure(p["start_at"], p["end_at"], hours.get(t.location_id) if None not in hours else hours[None]),
        ))
    return out


def _metrics(outcomes: List[CoaTaskOutcome], validator_pass: bool, conflicts: int) -> CoaMetrics:
    assigned = [o for o in outcomes if o.resource_id]
    missing = [o for o in outcomes if not o.resource_id]
    crit_delays = [o.delay_minutes for o in assigned if o.priority == "CRITICAL" and o.delay_minutes is not None]
    return CoaMetrics(
        assigned=len(assigned),
        unassigned=len(missing),
        unassigned_critical=sum(o.priority == "CRITICAL" for o in missing),
        unassigned_high=sum(o.priority == "HIGH" for o in missing),
        total_delay_minutes=sum(o.delay_minutes or 0 for o in assigned),
        critical_avg_delay_minutes=round(sum(crit_delays) / len(crit_delays), 1) if crit_delays else None,
        reassigned=sum(o.change == "REASSIGNED" for o in outcomes),
        retimed=sum(o.change == "RETIMED" for o in outcomes),
        unchanged=sum(o.change == "UNCHANGED" for o in outcomes),
        finish_at=max((o.end_at for o in assigned if o.end_at), default=None),
        weather_exposed_critical=sum(o.weather_exposure == "CRITICAL" for o in assigned),
        weather_exposed_warning=sum(o.weather_exposure == "WARNING" for o in assigned),
        validator_pass=validator_pass,
        validator_conflicts=conflicts,
    )


# Lower is better for every metric listed here
_COMPARED = [
    "unassigned_critical",
    "unassigned_high",
    "unassigned",
    "weather_exposed_critical",
    "weather_exposed_warning",
    "total_delay_minutes",
    "critical_avg_delay_minutes",
    "reassigned",
    "retimed",
    "validator_conflicts",
]


def _best_by_metric(courses: List[CourseOfAction]) -> Dict[str, List[str]]:
    best: Dict[str, List[str]] = {}
    scored = [c for c in courses if c.metrics]
    for name in _COMPARED:
        vals = [(getattr(c.metrics, name), c.key) for c in scored if getattr(c.metrics, name) is not None]
        if not vals:
            continue
        low = min(v for v, _ in vals)
        # Only mark a winner when the plans actually differ
        if any(v != low for v, _ in vals):
            best[name] = [k for v, k in vals if v == low]
    return best


def _plan_signature(result: ScheduleSolverResult) -> frozenset:
    return frozenset((a["task_id"], a["resource_id"], a["start_at"]) for a in result.assignments)


def _mark_duplicates(courses: List[CourseOfAction], results: Dict[str, ScheduleSolverResult]) -> None:
    """Different intents can land on the identical plan; say so instead of showing a fake alternative."""
    seen: Dict[frozenset, CourseOfAction] = {}
    for c in courses:
        if not c.metrics:
            continue
        sig = _plan_signature(results[c.key])
        if sig in seen:
            c.same_as = seen[sig].key
            c.note = f"Same plan as “{seen[sig].label}”: this intent changes nothing under current conditions."
        else:
            seen[sig] = c


def _recommend(courses: List[CourseOfAction]) -> Optional[str]:
    """Rule-based pick: protect critical work and safety first, then efficiency. Always explained."""
    valid = [c for c in courses if c.metrics and c.metrics.validator_pass and not c.same_as]
    if not valid:
        return None

    def rank(c: CourseOfAction) -> Tuple:
        m = c.metrics
        return (
            m.unassigned_critical,
            m.weather_exposed_critical,
            m.unassigned_high,
            m.unassigned,
            m.reassigned + m.retimed,
            m.total_delay_minutes,
        )

    ordered = sorted(valid, key=rank)
    pick = ordered[0]
    pick.recommended = True
    m = pick.metrics
    parts = [f"“{pick.label}” leaves {m.unassigned_critical} critical task(s) unassigned"]
    parts.append(f"puts {m.weather_exposed_critical} sortie(s) inside a critical weather hour")
    parts.append(f"and changes {m.reassigned + m.retimed} assignment(s)")
    reason = ", ".join(parts) + "."
    if len(ordered) > 1 and rank(ordered[1])[:2] == rank(pick)[:2]:
        reason += " Tie on critical coverage and weather; decided on fewer changes, then less delay."
    return reason


def _freeze(inputs: SolverInputs, freeze_at: datetime):
    """
    Split the problem at `freeze_at` (the operational "now"):
      - sorties already started stay exactly as planned and block their aircraft
      - everything else may not start before freeze_at
      - tasks whose window can no longer fit are reported as missed
    Returns (tasks to solve, availabilities incl. frozen sorties, frozen assignments, missed task ids).
    """
    blackouts: Dict[str, List[Tuple[datetime, datetime]]] = {}
    for av in inputs.availabilities:
        if not av.available:
            blackouts.setdefault(av.resource_id, []).append((_as_utc(av.start_at), _as_utc(av.end_at)))
    grounded = {r.id for r in inputs.resources if r.status in ("GROUNDED", "UNAVAILABLE")}

    def could_have_flown(a) -> bool:
        # A sortie on an aircraft that was grounded or blacked out at the time never launched
        s, e = _as_utc(a.start_at), _as_utc(a.end_at)
        return a.resource_id not in grounded and not any(bs < e and s < be for bs, be in blackouts.get(a.resource_id, []))

    frozen = [a for a in inputs.baseline_assignments if _as_utc(a.start_at) < freeze_at and could_have_flown(a)]
    frozen_ids = {a.task_id for a in frozen}
    blocks = [
        SimpleNamespace(id=f"frozen-{a.id}", resource_id=a.resource_id, available=False, start_at=a.start_at, end_at=a.end_at)
        for a in frozen
    ]
    to_solve, missed = [], []
    for t in inputs.tasks:
        if t.id in frozen_ids:
            continue
        start = max(_as_utc(t.earliest_start), freeze_at)
        if start + timedelta(minutes=t.duration_minutes) > _as_utc(t.latest_finish):
            missed.append(t.id)
            continue
        to_solve.append(SimpleNamespace(
            id=t.id, name=t.name, priority=t.priority, duration_minutes=t.duration_minutes,
            earliest_start=start, latest_finish=_as_utc(t.latest_finish),
            requirements=list(t.requirements), location_id=t.location_id,
        ))
    frozen_out = [
        {"task_id": a.task_id, "resource_id": a.resource_id, "start_at": _as_utc(a.start_at), "end_at": _as_utc(a.end_at)}
        for a in frozen
    ]
    return to_solve, list(inputs.availabilities) + blocks, frozen_out, missed


def generate_courses_of_action(
    db: Session,
    schedule_id: str,
    user: User,
    include_weather: bool,
    time_limit_seconds: int,
    freeze_at: Optional[datetime] = None,
    remember: bool = True,
) -> CoaSetResponse:
    inputs = load_solver_inputs(db, schedule_id)
    scenario_id = inputs.baseline.scenario_id

    # Load lazy relationships now: the solver threads must not touch the session
    for t in inputs.tasks:
        _ = list(t.requirements)

    solve_tasks, solve_avail, frozen, missed = list(inputs.tasks), inputs.availabilities, [], []
    if freeze_at:
        solve_tasks, solve_avail, frozen, missed = _freeze(inputs, _as_utc(freeze_at))

    weather_kwargs = solver_weather_kwargs(db, scenario_id, solve_tasks)[0] if include_weather else {}
    strict_kwargs = dict(weather_kwargs)
    if "task_hard_windows" in weather_kwargs:
        # Strict mode: warning windows become hard limits as well
        merged = {k: list(v) for k, v in weather_kwargs["task_hard_windows"].items()}
        for t_id, windows in weather_kwargs.get("task_soft_windows", {}).items():
            merged.setdefault(t_id, []).extend(windows)
        strict_kwargs = {"task_hard_windows": merged}
    profiles = [p for p in PROFILES if p.weather_mode != "strict" or include_weather]
    # Exposure is reported even for weather-blind plans so the comparison shows the risk taken
    per_site = uses_site_model(inputs.tasks)
    hours = site_hours(db, scenario_id) if per_site else {None: _weather_hours(db, scenario_id)}

    def solve(profile: Profile) -> Tuple[Profile, ScheduleSolverResult, float]:
        t0 = time.perf_counter()
        res = solve_schedule_scenario(
            scenario=inputs.scenario,
            resources=inputs.resources,
            availabilities=solve_avail,
            tasks=solve_tasks,
            baseline_assignments=inputs.baseline_assignments,
            time_limit_seconds=time_limit_seconds,
            priority_weights=profile.priority_weights,
            delay_by_priority=profile.delay_by_priority,
            num_workers=2,
            **(strict_kwargs if profile.weather_mode == "strict" else weather_kwargs),
            **profile.weights,
        )
        # The full plan = sorties already flying + the newly solved remainder
        res.assignments = frozen + res.assignments
        res.unassigned_tasks = list(res.unassigned_tasks) + missed
        if res.metrics:
            res.metrics.update(assigned_tasks=len(res.assignments), unassigned_tasks=len(res.unassigned_tasks), frozen_sorties=len(frozen))
        return profile, res, time.perf_counter() - t0

    with ThreadPoolExecutor(max_workers=len(profiles)) as pool:
        solved = list(pool.map(solve, profiles))

    courses: List[CourseOfAction] = []
    results: Dict[str, ScheduleSolverResult] = {}
    for profile, res, seconds in solved:
        results[profile.key] = res
        course = CourseOfAction(
            key=profile.key,
            label=profile.label,
            intent=profile.intent,
            solver_status=res.solver_status,
            objective_value=res.objective_value,
            solve_seconds=round(seconds, 2),
        )
        if res.solver_status in ("OPTIMAL", "FEASIBLE"):
            validation = validate_without_saving(db, inputs.baseline, res.assignments)
            outcomes = _outcomes(inputs, res, hours)
            course.tasks = outcomes
            course.metrics = _metrics(outcomes, validation.is_valid, validation.conflict_count)
        else:
            course.note = "; ".join(res.infeasibility_reasons) or "No feasible plan found in the time limit."
        courses.append(course)

    _mark_duplicates(courses, results)
    reason = _recommend(courses)
    now = datetime.now(timezone.utc)
    response = CoaSetResponse(
        coa_set_id=str(uuid.uuid4()),
        baseline_version_id=inputs.baseline.id,
        baseline_version_number=inputs.baseline.version_number,
        include_weather=include_weather,
        generated_at=now,
        expires_at=now + COA_TTL,
        courses=courses,
        recommendation_reason=reason,
        best_by_metric=_best_by_metric(courses),
    )
    if remember:  # hypothetical (what-if) plans are never kept, so they cannot be adopted
        _remember(_StoredSet(response=response, baseline_id=inputs.baseline.id, results=results, created_by=user.id))
    return response


def get_result_for_adoption(coa_set_id: str, key: str) -> Tuple[_StoredSet, ScheduleSolverResult]:
    entry = get_stored_set(coa_set_id)
    result = entry.results.get(key)
    if result is None:
        raise NotFoundError("Course of action", key)
    if result.solver_status not in ("OPTIMAL", "FEASIBLE"):
        raise ValidationError("This course of action has no feasible plan to adopt.")
    return entry, result
