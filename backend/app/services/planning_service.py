"""
Assigning one mission by hand: find every aircraft + crew that can fly it without moving anything
else in the active plan, rank the options, and turn the chosen one into a proposal for review.

The slot search respects the same rules as the optimiser: qualifications, stores carried and held,
service ceiling, maintenance, threat and airspace windows, critical weather, crew currency, rest,
shift and duty. The independent validator re-checks the chosen option before it becomes a proposal.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.engine.solver import ScheduleSolverResult
from app.models.all_models import Assignment, Resource, ResourceAvailability, ScheduleVersion, Task, User
from app.services.audit_service import log_audit_event
from app.services.ops_constraints import (
    above_ceiling, carries, crew_can_fly, scenario_layers, solver_ops_kwargs, store_demand,
)
from app.services.proposal_service import persist_proposal, validate_without_saving
from app.services.risk_service import assess_plan
from app.services.weather_impact import site_hours, task_weather_windows

Interval = Tuple[datetime, datetime]
MAX_OPTIONS = 8


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def active_version(db: Session, scenario_id: str) -> Optional[ScheduleVersion]:
    return (
        db.query(ScheduleVersion)
        .filter(ScheduleVersion.scenario_id == scenario_id, ScheduleVersion.status == "APPROVED")
        .order_by(ScheduleVersion.version_number.desc())
        .first()
    )


def plan_rows(db: Session, version: Optional[ScheduleVersion]) -> List[Assignment]:
    """The active plan's sorties, without those aborted on the day."""
    if not version:
        return []
    return [a for a in db.query(Assignment).filter(Assignment.schedule_version_id == version.id) if a.exec_status != "ABORTED"]


def _as_dict(a: Assignment) -> Dict[str, Any]:
    return {"task_id": a.task_id, "resource_id": a.resource_id, "crew_id": a.crew_id,
            "start_at": _utc(a.start_at), "end_at": _utc(a.end_at),
            "exec_status": a.exec_status, "actual_start": a.actual_start, "actual_end": a.actual_end}


def _earliest(lo: datetime, hi: datetime, minutes: int, blocked: List[Interval]) -> Optional[datetime]:
    """Earliest start in [lo, hi - minutes] whose interval avoids every blocked one."""
    dur = timedelta(minutes=minutes)
    for start in sorted({lo, *[e for _, e in blocked if lo <= e <= hi - dur]}):
        end = start + dur
        if end > hi:
            break
        if all(not (s < end and start < e) for s, e in blocked):
            return start
    return None


def task_options(db: Session, task_id: str, not_before: Optional[datetime] = None) -> Dict[str, Any]:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise NotFoundError("Task", task_id)
    sid = task.scenario_id
    version = active_version(db, sid)
    plan = plan_rows(db, version)
    others = [a for a in plan if a.task_id != task.id]
    current = next((a for a in plan if a.task_id == task.id), None)

    resources = db.query(Resource).filter(Resource.scenario_id == sid).all()
    layers = scenario_layers(db, sid)
    site = layers.sites.get(task.location_id) if task.location_id else None
    ops, _ = solver_ops_kwargs(db, sid, [task], resources)
    wx_hard, _ = task_weather_windows([task], site_hours(db, sid)) if task.location_id else ({}, {})
    task_blocked = [(_utc(s), _utc(e)) for s, e in ops["task_hard_windows"].get(task.id, []) + wx_hard.get(task.id, [])]

    blackouts: Dict[str, List[Interval]] = {}
    for b in db.query(ResourceAvailability).join(Resource).filter(Resource.scenario_id == sid, ResourceAvailability.available.is_(False)):
        blackouts.setdefault(b.resource_id, []).append((_utc(b.start_at), _utc(b.end_at)))
    busy: Dict[str, List[Interval]] = {}
    crew_busy: Dict[str, List[Interval]] = {}
    crew_flown: Dict[str, int] = {}
    for a in others:
        busy.setdefault(a.resource_id, []).append((_utc(a.start_at), _utc(a.end_at)))
        if a.crew_id:
            crew_busy.setdefault(a.crew_id, []).append((_utc(a.start_at), _utc(a.end_at)))
            crew_flown[a.crew_id] = crew_flown.get(a.crew_id, 0) + int((_utc(a.end_at) - _utc(a.start_at)).total_seconds() // 60)

    # Stores: what the rest of the plan already uses
    held: Dict[str, int] = {}
    for st in layers.stores:
        held[st.store_type] = held.get(st.store_type, 0) + st.quantity
    used: Dict[str, int] = {}
    tasks_by_id = {t.id: t for t in db.query(Task).filter(Task.scenario_id == sid)}
    for a in others:
        for kind, qty in store_demand(tasks_by_id[a.task_id]).items():
            used[kind] = used.get(kind, 0) + qty
    demand = store_demand(task)
    short = [f"{kind}: needs {qty}, {held.get(kind, 0) - used.get(kind, 0)} left" for kind, qty in demand.items()
             if held.get(kind, 0) - used.get(kind, 0) < qty]

    lo, hi = _utc(task.earliest_start), _utc(task.latest_finish)
    if not_before and _utc(not_before) > lo:
        lo = _utc(not_before).replace(second=0, microsecond=0)
    needed = [r.requirement_value for r in task.requirements if r.requirement_type == "QUALIFICATION"]
    crews_all = layers.crews if layers.crews else None

    options, ruled_out = [], []
    for r in sorted(resources, key=lambda x: x.name):
        quals = set((r.metadata_json or {}).get("qualifications", []))
        reason = None
        if r.status in ("GROUNDED", "UNAVAILABLE"):
            reason = f"{r.status.lower()}"
        elif any(q not in quals for q in needed):
            reason = "lacks " + ", ".join(q for q in needed if q not in quals)
        elif any(not carries(r, k) for k in demand):
            reason = "cannot carry " + ", ".join(k for k in demand if not carries(r, k))
        elif above_ceiling(r, site):
            reason = f"{site.name} is above its service ceiling"
        if reason:
            ruled_out.append({"aircraft": r.name, "reason": reason})
            continue
        blocked = busy.get(r.id, []) + blackouts.get(r.id, []) + task_blocked + \
            [(_utc(s), _utc(e)) for s, e in ops["pair_hard_windows"].get((task.id, r.id), [])]

        best = None
        candidates = [c for c in (crews_all or []) if c.status == "AVAILABLE" and crew_can_fly(c, r.resource_type)]
        if crews_all is None:
            start = _earliest(lo, hi, task.duration_minutes, blocked)
            best = (start, None) if start else None
        for c in candidates:
            if c.max_duty_minutes - c.duty_used_minutes - crew_flown.get(c.id, 0) < task.duration_minutes:
                continue
            rest = timedelta(minutes=c.min_rest_minutes)
            crew_blocked = [(s - rest, e + rest) for s, e in crew_busy.get(c.id, [])]
            clo = max(lo, c.duty_start) if c.duty_start else lo
            chi = min(hi, c.duty_end) if c.duty_end else hi
            start = _earliest(clo, chi, task.duration_minutes, blocked + crew_blocked) if clo < chi else None
            if start and (best is None or start < best[0]):
                best = (start, c)
        if not best:
            ruled_out.append({"aircraft": r.name, "reason": "no free slot with a rested, current crew inside the window"})
            continue
        start, crew = best
        options.append({
            "resource_id": r.id, "resource_name": r.name, "resource_type": r.resource_type,
            "model": (r.metadata_json or {}).get("model"),
            "crew_id": crew.id if crew else None, "crew_name": crew.name if crew else None,
            "start_at": start, "end_at": start + timedelta(minutes=task.duration_minutes),
            "delay_minutes": int((start - _utc(task.earliest_start)).total_seconds() // 60),
        })

    # Predicted risk of each option, in the context of the rest of the plan
    base = [_as_dict(a) for a in others]
    for o in options:
        report = assess_plan(db, sid, base + [{**o, "task_id": task.id}])
        row = next((x for x in report["sorties"] if x["task_id"] == task.id), None)
        o["risk"] = row["score"] if row else 0
        o["risk_factors"] = [f["detail"] for f in row["factors"]][:4] if row else []
    options.sort(key=lambda o: (o["start_at"], o["risk"]))

    return {
        "task_id": task.id, "task_name": task.name, "priority": task.priority,
        "window": [lo, hi], "duration_minutes": task.duration_minutes,
        "site": site.name if site else None,
        "plan_version": version.version_number if version else None,
        "currently": {"resource_id": current.resource_id, "start_at": _utc(current.start_at)} if current else None,
        "stores_short": short,
        "options": options[:MAX_OPTIONS] if not short else [],
        "ruled_out": ruled_out,
    }


def assign_option(db: Session, task_id: str, resource_id: str, crew_id: Optional[str], start_at: datetime, user: User) -> Dict[str, Any]:
    """Add (or move) one mission in a copy of the active plan and submit it for review."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise NotFoundError("Task", task_id)
    version = active_version(db, task.scenario_id)
    if not version:
        raise ValidationError("This scenario has no approved plan to add the mission to.")
    start = _utc(start_at)
    new = {"task_id": task.id, "resource_id": resource_id, "crew_id": crew_id,
           "start_at": start, "end_at": start + timedelta(minutes=task.duration_minutes)}
    assignments = [_as_dict(a) for a in plan_rows(db, version) if a.task_id != task.id] + [new]

    check = validate_without_saving(db, version, assignments)
    if not check.is_valid:
        raise ValidationError("That option breaks a rule: " + "; ".join(c.explanation for c in check.conflicts[:3]))

    now = datetime.now(timezone.utc)
    result = ScheduleSolverResult(
        solver_status="FEASIBLE", objective_value=None, assignments=assignments, unassigned_tasks=[],
        execution_time_seconds=0.0,
        metrics={"source": "manual assignment", "task": task.name, "assigned_tasks": len(assignments)},
        infeasibility_reasons=[],
    )
    proposal, run, validation = persist_proposal(db, version, result, user, now, now)
    log_audit_event(db, action="MISSION_ASSIGNED", entity_type="TASK", entity_id=task.id, actor=user,
                    metadata={"resource_id": resource_id, "crew_id": crew_id, "start_at": start, "proposal": proposal.id})
    db.commit()
    return {"run_id": run.id, "proposed_version_id": proposal.id, "proposed_version_number": proposal.version_number,
            "validation_ok": bool(validation and validation.is_valid)}
