"""
Running the plan on the day: each sortie of the active plan is launched, landed or aborted, with
actual times. An abort (optionally grounding the aircraft for some hours) leaves the plan with work
to redo; re-planning from "now" keeps airborne and completed sorties fixed and re-solves the rest.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.models.all_models import Assignment, Resource, ResourceAvailability, ScheduleVersion, Task, User
from app.models.ops_models import Crew
from app.models.weather_models import Location
from app.services.audit_service import log_audit_event
from app.services.conflict_service import check_schedule_conflicts
from app.services.planning_service import active_version

ACTIONS = {
    "launch": ({"PLANNED"}, "AIRBORNE"),
    "land": ({"AIRBORNE"}, "COMPLETED"),
    "abort": ({"PLANNED", "AIRBORNE"}, "ABORTED"),
}


def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def board(db: Session, scenario_id: str) -> Dict[str, Any]:
    version = active_version(db, scenario_id)
    now = datetime.now(timezone.utc)
    if not version:
        return {"plan_version": None, "plan_id": None, "now": now, "sorties": [], "summary": {}, "check": None}
    tasks = {t.id: t for t in db.query(Task).filter(Task.scenario_id == scenario_id)}
    res = {r.id: r for r in db.query(Resource).filter(Resource.scenario_id == scenario_id)}
    crews = {c.id: c.name for c in db.query(Crew).filter(Crew.scenario_id == scenario_id)}
    sites = {loc.id: loc.name for loc in db.query(Location).filter(Location.scenario_id == scenario_id)}

    rows = []
    for a in db.query(Assignment).filter(Assignment.schedule_version_id == version.id).order_by(Assignment.start_at):
        t, r = tasks.get(a.task_id), res.get(a.resource_id)
        start, end = _utc(a.start_at), _utc(a.end_at)
        late = None
        if a.exec_status == "PLANNED" and start < now:
            late = int((now - start).total_seconds() // 60)
        rows.append({
            "assignment_id": a.id, "task_id": a.task_id, "task_name": t.name if t else a.task_id,
            "priority": t.priority if t else None, "site": sites.get(t.location_id) if t and t.location_id else None,
            "resource_id": a.resource_id, "resource_name": r.name if r else a.resource_id,
            "resource_status": r.status if r else None,
            "crew_name": crews.get(a.crew_id) if a.crew_id else None,
            "start_at": start, "end_at": end, "status": a.exec_status,
            "actual_start": _utc(a.actual_start), "actual_end": _utc(a.actual_end), "note": a.exec_note,
            "launch_delay_minutes": int((_utc(a.actual_start) - start).total_seconds() // 60) if a.actual_start else None,
            "overdue_minutes": late,
        })
    check = check_schedule_conflicts(db, version.id)
    count = lambda s: sum(x["status"] == s for x in rows)  # noqa: E731
    return {
        "plan_version": version.version_number, "plan_id": version.id, "now": now, "sorties": rows,
        "summary": {"planned": count("PLANNED"), "airborne": count("AIRBORNE"), "completed": count("COMPLETED"),
                    "aborted": count("ABORTED"), "overdue": sum(1 for x in rows if x["overdue_minutes"])},
        "check": {"valid": check.is_valid, "conflicts": check.conflict_count, "unassigned": check.unassigned_task_count,
                  "items": [c.explanation for c in check.conflicts[:6]]},
        "needs_replan": not check.is_valid or count("ABORTED") > 0,
    }


def act(db: Session, assignment_id: str, action: str, user: User, at: Optional[datetime] = None,
        reason: Optional[str] = None, ground_hours: Optional[float] = None) -> Dict[str, Any]:
    if action not in ACTIONS:
        raise ValidationError(f"action must be one of {', '.join(ACTIONS)}.")
    a = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not a:
        raise NotFoundError("Sortie", assignment_id)
    version = db.get(ScheduleVersion, a.schedule_version_id)
    if version.status != "APPROVED":
        raise ValidationError("Only sorties of the approved plan can be executed.")
    allowed, new_status = ACTIONS[action]
    if a.exec_status not in allowed:
        raise ValidationError(f"A {a.exec_status.lower()} sortie cannot be {'launched' if action == 'launch' else action + 'ed'}.")
    when = _utc(at) or datetime.now(timezone.utc)
    if action == "abort" and not (reason or "").strip():
        raise ValidationError("Give the reason for the abort.")

    a.exec_status = new_status
    if action == "launch":
        a.actual_start = when
    elif action == "land":
        if when < _utc(a.actual_start):
            raise ValidationError("Landing cannot be before take-off.")
        a.actual_end = when
    else:
        a.exec_note = reason.strip()[:500]
        if a.actual_start and not a.actual_end:
            a.actual_end = when  # aborted in flight: back on the ground now

    if ground_hours:
        if not 0 < ground_hours <= 72:
            raise ValidationError("ground_hours must be between 0 and 72.")
        res = db.get(Resource, a.resource_id)
        db.add(ResourceAvailability(resource_id=res.id, start_at=when, end_at=when + timedelta(hours=ground_hours), available=False))
    log_audit_event(db, action=f"SORTIE_{new_status}", entity_type="ASSIGNMENT", entity_id=a.id, actor=user,
                    metadata={"task_id": a.task_id, "at": when, "reason": reason, "ground_hours": ground_hours})
    db.commit()
    return board(db, version.scenario_id)
