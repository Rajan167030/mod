from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.all_models import (
    ScheduleVersion, Assignment, Resource, ResourceAvailability, Task, TaskRequirement
)
from app.schemas.all_schemas import ConflictItem, ValidationResult
from app.services.ops_constraints import (
    above_ceiling, capabilities, carries, ceiling_m, crew_can_fly, is_active, scenario_layers, site_elevation_m,
    store_demand, zones_at_site,
)


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _layer_conflicts(db: Session, scenario_id: str, assignments: List[Assignment],
                     tasks: Dict[str, Task], resources: Dict[str, Resource]) -> List[ConflictItem]:
    """Crews, stores and zones, checked from the stored plan without the solver."""
    layers = scenario_layers(db, scenario_id)
    crews = {c.id: c for c in layers.crews}
    out: List[ConflictItem] = []

    def item(code: str, a: Assignment, text: str) -> ConflictItem:
        t, r = tasks.get(a.task_id), resources.get(a.resource_id)
        return ConflictItem(
            code=code, severity="CRITICAL", resource_id=a.resource_id, resource_name=r.name if r else None,
            task_ids=[a.task_id], task_names=[t.name] if t else [],
            conflict_start=a.start_at, conflict_end=a.end_at, explanation=text,
        )

    # Crews
    by_crew: Dict[str, List[Assignment]] = {}
    for a in assignments:
        t_name = tasks[a.task_id].name if a.task_id in tasks else a.task_id
        if not a.crew_id:
            if crews:
                out.append(item("CREW_MISSING", a, f"'{t_name}' has an aircraft but no crew."))
            continue
        c = crews.get(a.crew_id)
        if not c:
            out.append(item("CREW_MISSING", a, f"'{t_name}' names a crew that is not in this scenario."))
            continue
        by_crew.setdefault(c.id, []).append(a)
        r = resources.get(a.resource_id)
        if c.status != "AVAILABLE":
            out.append(item("CREW_UNAVAILABLE", a, f"{c.name} is {c.status} but is flying '{t_name}'."))
        if r and not crew_can_fly(c, r.resource_type):
            out.append(item("CREW_NOT_CURRENT", a, f"{c.name} is not current on {r.resource_type.replace('_', ' ').lower()} ({r.name})."))
        if c.duty_start and _utc(a.start_at) < c.duty_start or c.duty_end and _utc(a.end_at) > c.duty_end:
            out.append(item("CREW_OFF_SHIFT", a, f"'{t_name}' falls outside the duty shift of {c.name}."))
    for cid, asns in by_crew.items():
        c = crews[cid]
        asns.sort(key=lambda a: _utc(a.start_at))
        for prev, nxt in zip(asns, asns[1:]):
            gap = (_utc(nxt.start_at) - _utc(prev.end_at)).total_seconds() / 60
            if gap < c.min_rest_minutes:
                prev_name = tasks[prev.task_id].name if prev.task_id in tasks else prev.task_id
                what = "overlaps" if gap < 0 else f"follows after only {int(gap)} min rest (minimum {c.min_rest_minutes})"
                out.append(item("CREW_REST_VIOLATION", nxt, f"{c.name}: this sortie {what} '{prev_name}'."))
        flown = sum(int((_utc(a.end_at) - _utc(a.start_at)).total_seconds() // 60) for a in asns) + c.duty_used_minutes
        if flown > c.max_duty_minutes:
            out.append(item("CREW_DUTY_EXCEEDED", asns[-1], f"{c.name} would fly {flown} min against a {c.max_duty_minutes}-min duty limit."))

    # Stores
    held: Dict[str, int] = {}
    for st in layers.stores:
        held[st.store_type] = held.get(st.store_type, 0) + st.quantity
    used: Dict[str, List[Assignment]] = {}
    for a in assignments:
        t, r = tasks.get(a.task_id), resources.get(a.resource_id)
        if not t:
            continue
        for kind, qty in store_demand(t).items():
            used.setdefault(kind, []).extend([a] * qty)
            if r and not carries(r, kind):
                out.append(item("STORES_INCOMPATIBLE", a, f"{r.name} cannot carry {kind.replace('_', ' ').lower()} needed for '{t.name}'."))
    for kind, asns in used.items():
        if len(asns) > held.get(kind, 0):
            out.append(item("STORES_SHORTFALL", asns[-1], f"Plan needs {len(asns)} × {kind.replace('_', ' ').lower()} but only {held.get(kind, 0)} are held."))

    # Altitude: the site must be within the aircraft's service ceiling
    for a in assignments:
        t, r = tasks.get(a.task_id), resources.get(a.resource_id)
        site = layers.sites.get(t.location_id) if t and t.location_id else None
        if r and above_ceiling(r, site):
            out.append(item("ABOVE_SERVICE_CEILING", a, f"{site.name} is at {site_elevation_m(site):.0f} m, above the {ceiling_m(r):.0f} m ceiling of {r.name}."))

    # Threat zones and airspace
    for a in assignments:
        t, r = tasks.get(a.task_id), resources.get(a.resource_id)
        site = layers.sites.get(t.location_id) if t and t.location_id else None
        for z in zones_at_site(layers.zones, site):
            if z.effect != "BLOCK" or not is_active(z, a.start_at, a.end_at):
                continue
            if z.exempt_capability and r and z.exempt_capability in capabilities(r):
                continue
            code = "THREAT_ZONE_ENTRY" if z.category == "THREAT" else "AIRSPACE_VIOLATION"
            need = f" without {z.exempt_capability}" if z.exempt_capability else ""
            out.append(item(code, a, f"'{t.name}' flies into {z.name} at {site.name} while it is active{need}."))
    return out


def check_schedule_conflicts(db: Session, schedule_id: str) -> ValidationResult:
    """
    Independent pure-Python conflict validation engine.
    Independently inspects all assignments without relying on the solver.
    """
    schedule = db.query(ScheduleVersion).filter(ScheduleVersion.id == schedule_id).first()
    if not schedule:
        return ValidationResult(
            schedule_id=schedule_id,
            is_valid=False,
            total_assignments=0,
            conflict_count=1,
            conflicts=[ConflictItem(
                code="SCHEDULE_NOT_FOUND",
                severity="CRITICAL",
                explanation=f"Schedule version {schedule_id} does not exist."
            )]
        )

    assignments: List[Assignment] = [
        a for a in db.query(Assignment).filter(Assignment.schedule_version_id == schedule_id)
        if a.exec_status != "ABORTED"
    ]
    # Sorties already flown are history: they count as done but are not re-checked against rules
    all_assignments = assignments
    assignments = [a for a in all_assignments if a.exec_status != "COMPLETED"]

    # Pre-fetch resources and tasks in this scenario
    resources: Dict[str, Resource] = {
        r.id: r for r in db.query(Resource).filter(Resource.scenario_id == schedule.scenario_id).all()
    }
    tasks: Dict[str, Task] = {
        t.id: t for t in db.query(Task).filter(Task.scenario_id == schedule.scenario_id).all()
    }
    availabilities: List[ResourceAvailability] = db.query(ResourceAvailability).join(Resource).filter(
        Resource.scenario_id == schedule.scenario_id
    ).all()

    # Group availabilities by resource
    res_blackouts: Dict[str, List[ResourceAvailability]] = {}
    for a in availabilities:
        if not a.available:
            res_blackouts.setdefault(a.resource_id, []).append(a)

    conflicts: List[ConflictItem] = []

    # 1. Check Double Booking of Tasks (One task assigned to multiple resources)
    task_assignment_counts: Dict[str, List[Assignment]] = {}
    for asn in assignments:
        task_assignment_counts.setdefault(asn.task_id, []).append(asn)

    for task_id, asns in task_assignment_counts.items():
        if len(asns) > 1:
            task_obj = tasks.get(task_id)
            t_name = task_obj.name if task_obj else task_id
            conflicts.append(ConflictItem(
                code="DOUBLE_BOOKING",
                severity="CRITICAL",
                task_ids=[task_id],
                task_names=[t_name],
                explanation=f"Task '{t_name}' is assigned {len(asns)} times simultaneously across different resources."
            ))

    # 2. Check Resource Overlaps (Single capacity resource assigned to overlapping tasks)
    res_assignments: Dict[str, List[Assignment]] = {}
    for asn in assignments:
        res_assignments.setdefault(asn.resource_id, []).append(asn)

    for res_id, asns in res_assignments.items():
        res_obj = resources.get(res_id)
        r_name = res_obj.name if res_obj else res_id

        # Sort assignments by start_at
        sorted_asns = sorted(asns, key=lambda x: x.start_at)
        for i in range(len(sorted_asns)):
            for j in range(i + 1, len(sorted_asns)):
                a1 = sorted_asns[i]
                a2 = sorted_asns[j]

                # Check if a1 overlaps with a2
                if a1.end_at > a2.start_at and a1.start_at < a2.end_at:
                    t1_obj = tasks.get(a1.task_id)
                    t2_obj = tasks.get(a2.task_id)
                    t1_name = t1_obj.name if t1_obj else a1.task_id
                    t2_name = t2_obj.name if t2_obj else a2.task_id

                    overlap_start = max(a1.start_at, a2.start_at)
                    overlap_end = min(a1.end_at, a2.end_at)
                    diff_mins = int((overlap_end - overlap_start).total_seconds() / 60)

                    conflicts.append(ConflictItem(
                        code="RESOURCE_OVERLAP",
                        severity="CRITICAL",
                        resource_id=res_id,
                        resource_name=r_name,
                        task_ids=[a1.task_id, a2.task_id],
                        task_names=[t1_name, t2_name],
                        conflict_start=overlap_start,
                        conflict_end=overlap_end,
                        explanation=f"Resource '{r_name}' is overbooked: '{t1_name}' overlaps with '{t2_name}' by {diff_mins} minutes."
                    ))

    # 3. Check Resource Blackouts & Unavailability
    for asn in assignments:
        res_obj = resources.get(asn.resource_id)
        task_obj = tasks.get(asn.task_id)
        r_name = res_obj.name if res_obj else asn.resource_id
        t_name = task_obj.name if task_obj else asn.task_id

        # If resource itself is grounded/maintenance
        if res_obj and res_obj.status in ["GROUNDED", "MAINTENANCE", "UNAVAILABLE"]:
            conflicts.append(ConflictItem(
                code="RESOURCE_UNAVAILABLE",
                severity="CRITICAL",
                resource_id=asn.resource_id,
                resource_name=r_name,
                task_ids=[asn.task_id],
                task_names=[t_name],
                conflict_start=asn.start_at,
                conflict_end=asn.end_at,
                explanation=f"Resource '{r_name}' is currently {res_obj.status} but assigned to task '{t_name}'."
            ))

        # Check blackout windows
        blackouts = res_blackouts.get(asn.resource_id, [])
        for bo in blackouts:
            if asn.end_at > bo.start_at and asn.start_at < bo.end_at:
                overlap_start = max(asn.start_at, bo.start_at)
                overlap_end = min(asn.end_at, bo.end_at)
                diff_mins = int((overlap_end - overlap_start).total_seconds() / 60)
                conflicts.append(ConflictItem(
                    code="AVAILABILITY_BREACH",
                    severity="CRITICAL",
                    resource_id=asn.resource_id,
                    resource_name=r_name,
                    task_ids=[asn.task_id],
                    task_names=[t_name],
                    conflict_start=overlap_start,
                    conflict_end=overlap_end,
                    explanation=f"Assignment of '{t_name}' breaches maintenance/downtime window of '{r_name}' by {diff_mins} mins."
                ))

    # 4. Check Task Time Windows (Earliest Start & Latest Finish)
    for asn in assignments:
        task_obj = tasks.get(asn.task_id)
        if not task_obj:
            continue

        res_obj = resources.get(asn.resource_id)
        r_name = res_obj.name if res_obj else asn.resource_id

        if asn.start_at < task_obj.earliest_start:
            early_mins = int((task_obj.earliest_start - asn.start_at).total_seconds() / 60)
            conflicts.append(ConflictItem(
                code="TIME_WINDOW_VIOLATION",
                severity="CRITICAL",
                resource_id=asn.resource_id,
                resource_name=r_name,
                task_ids=[asn.task_id],
                task_names=[task_obj.name],
                conflict_start=asn.start_at,
                conflict_end=task_obj.earliest_start,
                explanation=f"Task '{task_obj.name}' scheduled {early_mins} mins prior to permitted earliest start time."
            ))

        if asn.end_at > task_obj.latest_finish:
            late_mins = int((asn.end_at - task_obj.latest_finish).total_seconds() / 60)
            conflicts.append(ConflictItem(
                code="TIME_WINDOW_VIOLATION",
                severity="CRITICAL",
                resource_id=asn.resource_id,
                resource_name=r_name,
                task_ids=[asn.task_id],
                task_names=[task_obj.name],
                conflict_start=task_obj.latest_finish,
                conflict_end=asn.end_at,
                explanation=f"Task '{task_obj.name}' finishes {late_mins} mins past strict deadline."
            ))

    # 5. Check Qualification / Eligibility Match
    for asn in assignments:
        task_obj = tasks.get(asn.task_id)
        res_obj = resources.get(asn.resource_id)
        if not task_obj or not res_obj:
            continue

        res_meta = res_obj.metadata_json or {}
        res_quals = set(res_meta.get("qualifications", []))

        for req in task_obj.requirements:
            if req.requirement_type == "QUALIFICATION":
                if req.requirement_value not in res_quals:
                    conflicts.append(ConflictItem(
                        code="ELIGIBILITY_MISMATCH",
                        severity="CRITICAL",
                        resource_id=res_obj.id,
                        resource_name=res_obj.name,
                        task_ids=[task_obj.id],
                        task_names=[task_obj.name],
                        explanation=f"Resource '{res_obj.name}' lacks qualification '{req.requirement_value}' required for task '{task_obj.name}'."
                    ))

    # 6-8. Crews, stores, threat zones and airspace
    conflicts.extend(_layer_conflicts(db, schedule.scenario_id, assignments, tasks, resources))

    # Identify Unassigned Tasks
    assigned_task_ids = {a.task_id for a in all_assignments}
    unassigned_tasks = [t_id for t_id in tasks.keys() if t_id not in assigned_task_ids]

    is_valid = len(conflicts) == 0

    return ValidationResult(
        schedule_id=schedule_id,
        is_valid=is_valid,
        total_assignments=len(all_assignments),
        conflict_count=len(conflicts),
        conflicts=conflicts,
        unassigned_task_count=len(unassigned_tasks),
        unassigned_task_ids=unassigned_tasks
    )
