"""
Live exercise replay.

A copy of a scenario is played forward on a simulated clock. Scripted events (aircraft
unserviceable, weather updates, new urgent tasks, ...) are applied when the clock reaches
them; each one is checked against the active plan and, if the plan breaks, courses of
action are generated in the background from the operational "now". People still decide:
a plan only becomes active through the normal adopt + approve path.
"""
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.db.demo_contested import CONTESTED_SCENARIO_NAME
from app.db.session import SessionLocal
from app.models.all_models import (
    Assignment,
    Disruption,
    Resource,
    ResourceAvailability,
    ScheduleVersion,
    Task,
    TaskRequirement,
    User,
)
from app.models.ops_models import Crew, OpsZone
from app.models.replay_models import ReplaySession, WeatherInject
from app.models.weather_models import Location
from app.services.audit_service import log_audit_event
from app.services.coa_service import generate_courses_of_action
from app.services.conflict_service import check_schedule_conflicts
from app.services.scenario_admin import clone_scenario, delete_scenario, scenario_start
from app.services.weather_impact import exposure, site_hours

logger = logging.getLogger(__name__)

REPLAN_TIME_LIMIT_SECONDS = 4
# Tests run replanning inline: the in-memory test database has a single shared connection
RUN_REPLAN_INLINE = False
SPEEDS = (30.0, 60.0, 120.0, 240.0)

# Minutes are measured from the exercise start. Site keys match demo_contested.SITES names.
SCRIPTS: Dict[str, Dict[str, Any]] = {
    "winter_lift": {
        "title": "Winter Lift, day one",
        "source_scenario": CONTESTED_SCENARIO_NAME,
        "end_min": 600,
        "events": [
            {
                "at_min": 20, "kind": "NOTE",
                "title": "Shift handover",
                "detail": "Approved plan v1 in force. All aircraft serviceable.",
            },
            {
                "at_min": 75, "kind": "AIRCRAFT_UNSERVICEABLE",
                "title": "C-130-Alpha unserviceable",
                "detail": "Hydraulic leak reported after start-up. Grounded for 7 hours from landing.",
                "params": {"resource": "C-130-Alpha", "hours": 7},
            },
            {
                "at_min": 120, "kind": "THREAT_DETECTED",
                "title": "SAM radar detected near Foxtrot",
                "detail": "ELINT reports a mobile SAM tracking radar 15 km north of Foxtrot. Unprotected aircraft must stay clear for six hours.",
                "params": {"name": "Pop-up SAM, Foxtrot north", "site": "Foxtrot Medevac Point", "kind": "SAM",
                           "offset": [0.10, 0.02], "radius_km": 22, "hours": 6, "exempt": "DASS",
                           "source": "ELINT", "confidence": 0.8},
            },
            {
                "at_min": 150, "kind": "WEATHER_INJECT",
                "title": "Gust warning, Echo Pass",
                "detail": "Forecast update: gusts above 70 km/h at Echo Pass for four hours.",
                "params": {"site": "Echo Pass LZ", "variable": "wind_speed", "value": 72, "severity": "CRITICAL",
                           "from_min": 30, "hours": 4},
            },
            {
                "at_min": 210, "kind": "NEW_TASK",
                "title": "Avalanche casualties, Delta Valley",
                "detail": "Two casualties reported; casualty evacuation needed within three hours.",
                "params": {"name": "WL-22 Avalanche casualty evac, Delta Valley", "minutes": 75, "open_min": 15,
                           "close_min": 180, "priority": "CRITICAL", "qualification": "MEDEVAC", "site": "Delta Valley LZ"},
            },
            {
                "at_min": 260, "kind": "CREW_STOOD_DOWN",
                "title": "Hercules crew 1 stood down",
                "detail": "Flight surgeon stands Hercules crew 1 down for fatigue once they land.",
                "params": {"crew": "Hercules crew 1"},
            },
            {
                "at_min": 300, "kind": "DURATION_SURGE",
                "title": "Headwinds on the Bravo route",
                "detail": "Engineer plant lift will take an extra hour.",
                "params": {"task_prefix": "WL-03", "minutes": 60},
            },
            {
                "at_min": 390, "kind": "DEADLINE_TIGHTEN",
                "title": "Foxtrot needs medical stores sooner",
                "detail": "Second-wave medical delivery deadline brought forward by two hours.",
                "params": {"task_prefix": "WL-09", "hours": 2},
            },
        ],
    }
}

_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(session_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(session_id, threading.Lock())


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def sim_now(s: ReplaySession) -> datetime:
    anchor = _utc(s.sim_anchor)
    if s.status != "RUNNING":
        return anchor
    return anchor + (_now() - _utc(s.wall_anchor)) * s.speed


def _active_version(db: Session, scenario_id: str) -> Optional[ScheduleVersion]:
    return (
        db.query(ScheduleVersion)
        .filter(ScheduleVersion.scenario_id == scenario_id, ScheduleVersion.status == "APPROVED")
        .order_by(ScheduleVersion.version_number.desc())
        .first()
    )


def _save_events(s: ReplaySession, events: List[dict]) -> None:
    # Reassign a new list so SQLAlchemy sees the JSON change
    s.events_json = [dict(e) for e in events]


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def start_replay(db: Session, user: User, script_key: str, speed: float) -> ReplaySession:
    script = SCRIPTS.get(script_key)
    if not script:
        raise ValidationError(f"Unknown exercise script '{script_key}'.")
    if speed not in SPEEDS:
        raise ValidationError(f"speed must be one of {SPEEDS}.")
    from app.models.all_models import Scenario

    source = db.query(Scenario).filter(Scenario.name == script["source_scenario"]).first()
    if not source:
        raise NotFoundError("Exercise source scenario", script["source_scenario"])

    t0 = _now().replace(second=0, microsecond=0)
    copy = clone_scenario(
        db, source.id,
        name=f"{script['title']} · exercise {t0:%d %b %H%MZ}",
        description=f"Live exercise copy of '{source.name}'. Deleted when the exercise is closed.",
        created_by=user.id,
        new_t0=t0,
    )
    session = ReplaySession(
        scenario_id=copy.id,
        source_scenario_id=source.id,
        script_key=script_key,
        status="RUNNING",
        speed=speed,
        sim_t0=t0,
        sim_anchor=t0,
        wall_anchor=_now(),
        events_json=[
            {**{k: v for k, v in e.items() if k != "params"}, "idx": i, "params": e.get("params", {}), "status": "PENDING"}
            for i, e in enumerate(script["events"])
        ],
        created_by=user.id,
    )
    db.add(session)
    db.flush()
    log_audit_event(db, action="EXERCISE_STARTED", entity_type="REPLAY", entity_id=session.id, actor=user,
                    metadata={"script": script_key, "scenario_id": copy.id, "speed": speed})
    db.commit()
    return session


def get_session(db: Session, session_id: str) -> ReplaySession:
    s = db.query(ReplaySession).filter(ReplaySession.id == session_id).first()
    if not s:
        raise NotFoundError("Exercise", session_id)
    return s


def control(db: Session, s: ReplaySession, action: str, speed: Optional[float] = None) -> ReplaySession:
    with _lock(s.id):
        db.refresh(s)
        if s.status == "FINISHED":
            raise ValidationError("This exercise has finished.")
        now_sim = sim_now(s)
        if action == "pause":
            s.sim_anchor, s.wall_anchor, s.status = now_sim, _now(), "PAUSED"
        elif action == "resume":
            s.sim_anchor, s.wall_anchor, s.status = now_sim, _now(), "RUNNING"
        elif action == "speed":
            if speed not in SPEEDS:
                raise ValidationError(f"speed must be one of {SPEEDS}.")
            s.sim_anchor, s.wall_anchor, s.speed = now_sim, _now(), speed
        elif action == "skip":
            # Jump the clock to just before the next pending event
            pending = [e for e in s.events_json if e["status"] == "PENDING"]
            if pending:
                target = _utc(s.sim_t0) + timedelta(minutes=pending[0]["at_min"] - 1)
                if target > now_sim:
                    s.sim_anchor, s.wall_anchor = target, _now()
        else:
            raise ValidationError(f"Unknown action '{action}'.")
        db.commit()
    return s


def close_replay(db: Session, s: ReplaySession, user: User) -> None:
    scenario_id, session_id = s.scenario_id, s.id
    with _lock(session_id):
        delete_scenario(db, scenario_id)
        log_audit_event(db, action="EXERCISE_CLOSED", entity_type="REPLAY", entity_id=session_id, actor=user, metadata={})
        db.commit()


# ---------------------------------------------------------------------------
# Clock tick: apply due events
# ---------------------------------------------------------------------------

def tick(db: Session, s: ReplaySession, user: User) -> ReplaySession:
    """Apply every event the simulated clock has reached. Safe to call on every poll."""
    with _lock(s.id):
        db.refresh(s)
        if s.status == "FINISHED":
            return s
        now_sim = sim_now(s)
        t0 = _utc(s.sim_t0)
        events = [dict(e) for e in s.events_json]
        for e in events:
            if e["status"] != "PENDING" or t0 + timedelta(minutes=e["at_min"]) > now_sim:
                continue
            event_time = t0 + timedelta(minutes=e["at_min"])
            try:
                _apply(db, s, e, event_time, user)
                db.flush()
                version = _active_version(db, s.scenario_id)
                e.update(_impact(db, s.scenario_id, version))
                e["applied_wall_at"] = _now().isoformat()
                needs_replan = e["kind"] != "NOTE" and version is not None
                e["status"] = "REPLANNING" if needs_replan else "NO_ACTION"
                if needs_replan:
                    e["replan_from_version"] = version.id
            except Exception as exc:  # an event must never take the exercise down
                logger.exception("Exercise event %s failed", e.get("title"))
                db.rollback()
                db.refresh(s)
                e["status"] = "ERROR"
                e["error"] = str(exc)
            # Commit each event on its own so a later failure cannot undo earlier ones
            _save_events(s, events)
            db.commit()

        script = SCRIPTS[s.script_key]
        if now_sim >= t0 + timedelta(minutes=script["end_min"]) and all(ev["status"] != "PENDING" for ev in events):
            s.sim_anchor, s.wall_anchor, s.status = t0 + timedelta(minutes=script["end_min"]), _now(), "FINISHED"
            db.commit()

    started = False
    for e in events:
        if e["status"] == "REPLANNING" and not e.get("replan_started"):
            _start_replan(s.id, e["idx"], user.id)
            started = True
    if started:
        db.refresh(s)  # replanning records its progress through its own session
    return s


def _impact(db: Session, scenario_id: str, version: Optional[ScheduleVersion]) -> Dict[str, int]:
    """How the active plan looks right after an event: rule conflicts, unscheduled tasks, weather exposure."""
    if not version:
        return {"conflicts_after": 0, "unassigned_after": 0, "weather_exposed_after": 0}
    check = check_schedule_conflicts(db, version.id)
    hours = site_hours(db, scenario_id)
    task_sites = {t.id: t.location_id for t in db.query(Task).filter(Task.scenario_id == scenario_id)}
    exposed = sum(
        exposure(_utc(a.start_at), _utc(a.end_at), hours.get(task_sites.get(a.task_id))) == "CRITICAL"
        for a in db.query(Assignment).filter(Assignment.schedule_version_id == version.id)
    )
    return {
        "conflicts_after": check.conflict_count,
        "unassigned_after": check.unassigned_task_count,
        "weather_exposed_after": exposed,
    }


def _task_by_prefix(db: Session, scenario_id: str, prefix: str) -> Task:
    task = db.query(Task).filter(Task.scenario_id == scenario_id, Task.name.like(f"{prefix}%")).first()
    if not task:
        raise ValidationError(f"No task starting with '{prefix}'.")
    return task


def _apply(db: Session, s: ReplaySession, e: dict, at: datetime, user: User) -> None:
    kind, p = e["kind"], e.get("params", {})
    sid = s.scenario_id
    if kind == "NOTE":
        return

    if kind == "AIRCRAFT_UNSERVICEABLE":
        res = db.query(Resource).filter(Resource.scenario_id == sid, Resource.name == p["resource"]).one()
        # Grounded once it lands: a sortie already airborne completes
        version = _active_version(db, sid)
        landing = at
        if version:
            for a in db.query(Assignment).filter(Assignment.schedule_version_id == version.id, Assignment.resource_id == res.id):
                if _utc(a.start_at) <= at < _utc(a.end_at):
                    landing = _utc(a.end_at)
        until = landing + timedelta(hours=p["hours"])
        db.add(ResourceAvailability(resource_id=res.id, start_at=landing, end_at=until, available=False))
        e["effect"] = f"{res.name} unavailable {landing:%H%MZ}–{until:%H%MZ}"

    elif kind == "THREAT_DETECTED":
        loc = db.query(Location).filter(Location.scenario_id == sid, Location.name == p["site"]).one()
        zone = OpsZone(
            scenario_id=sid, name=p["name"], category="THREAT", kind=p["kind"], effect="BLOCK",
            center_lat=loc.latitude + p["offset"][0], center_lon=loc.longitude + p["offset"][1], radius_km=p["radius_km"],
            exempt_capability=p.get("exempt"), source=p.get("source"), confidence=p.get("confidence", 0.8),
            notes=e["detail"],
        )
        # Aircraft already airborne in the area recover first; the restriction starts once they land
        from app.services.ops_constraints import zone_contains
        sites = {x.id: x for x in db.query(Location).filter(Location.scenario_id == sid)}
        tasks = {t.id: t for t in db.query(Task).filter(Task.scenario_id == sid)}
        start = at
        version = _active_version(db, sid)
        if version:
            for a in db.query(Assignment).filter(Assignment.schedule_version_id == version.id):
                site = sites.get(tasks[a.task_id].location_id) if a.task_id in tasks else None
                if site and zone_contains(zone, site.latitude, site.longitude) and _utc(a.start_at) <= at < _utc(a.end_at):
                    start = max(start, _utc(a.end_at))
        zone.active_from, zone.active_until = start, start + timedelta(hours=p["hours"])
        db.add(zone)
        need = f" without {zone.exempt_capability}" if zone.exempt_capability else ""
        e["effect"] = f"{zone.name}: no flying near {loc.name}{need} {start:%H%MZ}–{zone.active_until:%H%MZ}"

    elif kind == "CREW_STOOD_DOWN":
        crew = db.query(Crew).filter(Crew.scenario_id == sid, Crew.name == p["crew"]).one()
        # A crew in the air finishes its sortie; its duty ends when it lands
        landing = at
        version = _active_version(db, sid)
        if version:
            for a in db.query(Assignment).filter(Assignment.schedule_version_id == version.id, Assignment.crew_id == crew.id):
                if _utc(a.start_at) <= at < _utc(a.end_at):
                    landing = _utc(a.end_at)
        crew.duty_end = landing
        crew.notes = f"Stood down {landing:%H%MZ}: {e['detail']}"
        e["effect"] = f"{crew.name} unavailable from {landing:%H%MZ}"

    elif kind == "WEATHER_INJECT":
        loc = db.query(Location).filter(Location.scenario_id == sid, Location.name == p["site"]).one()
        start = (at + timedelta(minutes=p.get("from_min", 0))).replace(minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=p["hours"])
        db.add(WeatherInject(
            scenario_id=sid, location_id=loc.id, variable=p["variable"], value=p["value"],
            severity=p["severity"], start_at=start, end_at=end, note=e["title"],
        ))
        e["effect"] = f"Simulated {p['severity'].lower()} {p['variable'].replace('_', ' ')} at {loc.name} {start:%H%MZ}–{end:%H%MZ}"

    elif kind == "NEW_TASK":
        loc = db.query(Location).filter(Location.scenario_id == sid, Location.name == p["site"]).one()
        task = Task(
            scenario_id=sid, name=p["name"], description=e["detail"], duration_minutes=p["minutes"],
            earliest_start=at + timedelta(minutes=p["open_min"]), latest_finish=at + timedelta(minutes=p["close_min"]),
            priority=p["priority"], status="PENDING", location_id=loc.id,
        )
        db.add(task)
        db.flush()
        db.add(TaskRequirement(task_id=task.id, requirement_type="QUALIFICATION", requirement_value=p["qualification"]))
        e["effect"] = f"New {p['priority'].lower()} task, window {task.earliest_start:%H%MZ}–{task.latest_finish:%H%MZ}"

    elif kind == "DURATION_SURGE":
        task = _task_by_prefix(db, sid, p["task_prefix"])
        task.duration_minutes += p["minutes"]
        e["effect"] = f"{task.name}: now {task.duration_minutes} min"

    elif kind == "DEADLINE_TIGHTEN":
        task = _task_by_prefix(db, sid, p["task_prefix"])
        task.latest_finish = _utc(task.latest_finish) - timedelta(hours=p["hours"])
        e["effect"] = f"{task.name}: must finish by {task.latest_finish:%H%MZ}"

    else:
        raise ValidationError(f"Unknown event kind '{kind}'.")

    db.add(Disruption(scenario_id=sid, type=f"EXERCISE_{kind}", payload_json={"event": e["title"], **p}, created_by=user.id))
    e["applied_sim_at"] = at.isoformat()


# ---------------------------------------------------------------------------
# Background replanning
# ---------------------------------------------------------------------------

def _start_replan(session_id: str, idx: int, user_id: str) -> None:
    with _lock(session_id):
        with SessionLocal() as db:
            s = db.query(ReplaySession).filter(ReplaySession.id == session_id).first()
            if not s:
                return
            events = [dict(e) for e in s.events_json]
            if events[idx].get("replan_started"):
                return
            events[idx]["replan_started"] = True
            _save_events(s, events)
            db.commit()
    if RUN_REPLAN_INLINE:
        _replan(session_id, idx, user_id)
    else:
        threading.Thread(target=_replan, args=(session_id, idx, user_id), name=f"replan-{idx}", daemon=True).start()


def _replan(session_id: str, idx: int, user_id: str) -> None:
    started = time.perf_counter()
    result: Dict[str, Any] = {}
    try:
        with SessionLocal() as db:
            s = db.query(ReplaySession).filter(ReplaySession.id == session_id).one()
            e = s.events_json[idx]
            user = db.query(User).filter(User.id == user_id).one()
            freeze = datetime.fromisoformat(e["applied_sim_at"]) if e.get("applied_sim_at") else sim_now(s)
            coa = generate_courses_of_action(
                db, e["replan_from_version"], user, include_weather=True,
                time_limit_seconds=REPLAN_TIME_LIMIT_SECONDS, freeze_at=freeze,
            )
            db.rollback()  # nothing from planning is kept; adoption writes later
            suggested = next((c for c in coa.courses if c.recommended), None)
            result = {
                "status": "READY",
                "coa_set_id": coa.coa_set_id,
                "suggested_key": suggested.key if suggested else None,
                "suggested_label": suggested.label if suggested else None,
                "recommendation_reason": coa.recommendation_reason,
                "replan_seconds": round(time.perf_counter() - started, 2),
            }
    except Exception as exc:
        logger.exception("Exercise replan failed")
        result = {"status": "ERROR", "error": f"Replanning failed: {exc}"}

    with _lock(session_id):
        with SessionLocal() as db:
            s = db.query(ReplaySession).filter(ReplaySession.id == session_id).first()
            if not s:
                return
            events = [dict(ev) for ev in s.events_json]
            events[idx].update(result)
            _save_events(s, events)
            db.commit()


def restart_replan(db: Session, s: ReplaySession, idx: int, user: User) -> None:
    """
    Solve an event's courses of action again. Options live in server memory, so a restart (or the
    two-hour expiry) loses them; the event keeps its inputs, so the same problem is solved again.
    """
    with _lock(s.id):
        db.refresh(s)
        events = [dict(e) for e in s.events_json]
        e = events[idx]
        if e.get("status") not in ("READY", "ERROR") or not e.get("replan_from_version"):
            raise ValidationError("This event has no plans to rebuild.")
        for key in ("coa_set_id", "suggested_key", "suggested_label", "recommendation_reason", "replan_seconds", "error"):
            e.pop(key, None)
        e["status"], e["replan_started"] = "REPLANNING", False
        _save_events(s, events)
        db.commit()
    _start_replan(s.id, idx, user.id)


def record_decision(db: Session, s: ReplaySession, idx: int, decision: Dict[str, Any]) -> None:
    with _lock(s.id):
        db.refresh(s)
        events = [dict(e) for e in s.events_json]
        if not 0 <= idx < len(events):
            raise NotFoundError("Exercise event", str(idx))
        events[idx]["decision"] = {**decision, "decided_wall_at": _now().isoformat()}
        events[idx]["status"] = "DECIDED"
        _save_events(s, events)
        db.commit()


# ---------------------------------------------------------------------------
# Read model
# ---------------------------------------------------------------------------

def summary(db: Session, s: ReplaySession) -> Dict[str, Any]:
    """Outcome figures measured from this exercise (no invented baselines)."""
    events = s.events_json
    applied = [e for e in events if e["status"] not in ("PENDING",)]
    replans = [e for e in events if e.get("replan_seconds") is not None]
    decided = [e for e in events if e.get("decision")]

    version = _active_version(db, s.scenario_id)
    original = (
        db.query(ScheduleVersion)
        .filter(ScheduleVersion.scenario_id == s.scenario_id, ScheduleVersion.version_number == 1)
        .first()
    )
    current = check_schedule_conflicts(db, version.id) if version else None
    untouched = check_schedule_conflicts(db, original.id) if original else None
    tasks = {t.id: t for t in db.query(Task).filter(Task.scenario_id == s.scenario_id)}
    assigned = {a.task_id for a in db.query(Assignment).filter(Assignment.schedule_version_id == version.id)} if version else set()
    crit = [t for t in tasks.values() if t.priority == "CRITICAL"]

    def latency(e: dict) -> Optional[float]:
        try:
            return (datetime.fromisoformat(e["decision"]["decided_wall_at"]) - datetime.fromisoformat(e["applied_wall_at"])).total_seconds()
        except (KeyError, TypeError, ValueError):
            return None

    lat = [x for x in (latency(e) for e in decided) if x is not None]
    return {
        "events_applied": len(applied),
        "replans": len(replans),
        "avg_replan_seconds": round(sum(e["replan_seconds"] for e in replans) / len(replans), 2) if replans else None,
        "decisions": len(decided),
        "avg_decision_seconds": round(sum(lat) / len(lat), 1) if lat else None,
        "active_version": version.version_number if version else None,
        "active_conflicts": current.conflict_count if current else None,
        "active_unassigned": current.unassigned_task_count if current else None,
        # What the original plan would look like now if nobody had replanned
        "original_plan_conflicts": untouched.conflict_count if untouched else None,
        "original_plan_unassigned": untouched.unassigned_task_count if untouched else None,
        "critical_tasks": len(crit),
        "critical_covered": sum(t.id in assigned for t in crit),
    }


def scenario_window(db: Session, s: ReplaySession) -> Dict[str, Any]:
    start = scenario_start(db, s.scenario_id)
    return {"start": start.isoformat() if start else None, "end_min": SCRIPTS[s.script_key]["end_min"]}
