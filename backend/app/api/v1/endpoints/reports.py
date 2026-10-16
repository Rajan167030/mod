import io
import csv
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.all_models import (
    Scenario, Resource, Task, ScheduleVersion, Assignment, AuditEvent,
    OptimisationRun, User
)
from app.core.errors import NotFoundError
from app.api.deps import get_current_user
from app.services.conflict_service import check_schedule_conflicts
from app.schemas.all_schemas import DashboardKPI, AuditEventResponse

router = APIRouter(prefix="/reports", tags=["Reports & KPIs"])


@router.get("/dashboard", response_model=DashboardKPI)
def get_dashboard_kpis(
    scenario_id: Optional[str] = Query(None, description="Scenario to summarise; defaults to the newest"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """KPIs for one scenario, measured on its active (latest approved) schedule version."""
    total_scenarios = db.query(Scenario).count()
    scenario = (
        db.query(Scenario).filter(Scenario.id == scenario_id).first()
        if scenario_id
        else db.query(Scenario).order_by(Scenario.created_at.desc()).first()
    )
    if scenario_id and not scenario:
        raise NotFoundError("Scenario", scenario_id)
    sid = scenario.id if scenario else None

    total_resources = db.query(Resource).filter(Resource.scenario_id == sid).count()
    total_tasks = db.query(Task).filter(Task.scenario_id == sid).count()
    active = (
        db.query(ScheduleVersion)
        .filter(ScheduleVersion.scenario_id == sid, ScheduleVersion.status == "APPROVED")
        .order_by(ScheduleVersion.version_number.desc())
        .first()
    )

    assigned_tasks = 0
    active_conflicts = 0
    if active:
        assigned_tasks = len({a.task_id for a in db.query(Assignment).filter(Assignment.schedule_version_id == active.id)})
        active_conflicts = check_schedule_conflicts(db, active.id).conflict_count
    unassigned_tasks = max(0, total_tasks - assigned_tasks)

    version_ids = [v for (v,) in db.query(ScheduleVersion.id).filter(ScheduleVersion.scenario_id == sid)]
    latest_run = (
        db.query(OptimisationRun)
        .filter(OptimisationRun.schedule_version_id.in_(version_ids))
        .order_by(OptimisationRun.started_at.desc())
        .first()
    )
    latest_run_status = latest_run.solver_status if latest_run else "IDLE"

    completion_rate = round((assigned_tasks / total_tasks * 100), 1) if total_tasks > 0 else 0.0
    utilization_rate = round(min(100.0, (assigned_tasks / (total_resources * 2)) * 100), 1) if total_resources > 0 else 0.0

    recent_audits_raw = db.query(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(10).all()
    recent_audits = [
        AuditEventResponse(
            id=a.id,
            actor_id=a.actor_id,
            action=a.action,
            entity_type=a.entity_type,
            entity_id=a.entity_id,
            metadata_json=a.metadata_json,
            created_at=a.created_at
        ) for a in recent_audits_raw
    ]

    return DashboardKPI(
        scenario_id=sid,
        scenario_name=scenario.name if scenario else None,
        active_version_number=active.version_number if active else None,
        total_scenarios=total_scenarios,
        total_resources=total_resources,
        total_tasks=total_tasks,
        assigned_tasks=assigned_tasks,
        unassigned_tasks=unassigned_tasks,
        active_conflicts=active_conflicts,
        latest_optimisation_status=latest_run_status,
        schedule_completion_rate=completion_rate,
        resource_utilization_rate=utilization_rate,
        recent_audits=recent_audits
    )


@router.get("/scenario/{scenario_id}")
def get_scenario_report(
    scenario_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieve detailed operational report metrics for a specific scenario."""
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not scenario:
        raise NotFoundError("Scenario", scenario_id)

    resources = db.query(Resource).filter(Resource.scenario_id == scenario_id).all()
    tasks = db.query(Task).filter(Task.scenario_id == scenario_id).all()
    schedules = db.query(ScheduleVersion).filter(ScheduleVersion.scenario_id == scenario_id).all()

    approved_schedule = next((s for s in schedules if s.status == "APPROVED"), None)
    if not approved_schedule and schedules:
        approved_schedule = schedules[0]

    assigned_count = 0
    validation = None
    if approved_schedule:
        assignments = db.query(Assignment).filter(Assignment.schedule_version_id == approved_schedule.id).all()
        assigned_count = len(assignments)
        validation = check_schedule_conflicts(db, approved_schedule.id)

    # Priority distribution
    prio_counts: Dict[str, int] = {}
    for t in tasks:
        prio_counts[t.priority] = prio_counts.get(t.priority, 0) + 1

    return {
        "scenario_id": scenario.id,
        "scenario_name": scenario.name,
        "total_resources": len(resources),
        "total_tasks": len(tasks),
        "tasks_assigned": assigned_count,
        "tasks_unassigned": len(tasks) - assigned_count,
        "priority_distribution": prio_counts,
        "active_schedule_version": approved_schedule.version_number if approved_schedule else None,
        "schedule_status": approved_schedule.status if approved_schedule else "NO_SCHEDULE",
        "conflict_count": validation.conflict_count if validation else 0,
        "is_valid": validation.is_valid if validation else True
    }


@router.get("/scenario/{scenario_id}/export-csv")
def export_schedule_csv(
    scenario_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Safely export active schedule assignments to standard CSV."""
    schedule = db.query(ScheduleVersion).filter(
        ScheduleVersion.scenario_id == scenario_id,
        ScheduleVersion.status.in_(["APPROVED", "PROPOSED"])
    ).order_by(ScheduleVersion.version_number.desc()).first()

    if not schedule:
        raise NotFoundError("Schedule", f"for scenario {scenario_id}")

    assignments = db.query(Assignment).filter(Assignment.schedule_version_id == schedule.id).all()
    tasks = {t.id: t for t in db.query(Task).filter(Task.scenario_id == scenario_id).all()}
    resources = {r.id: r for r in db.query(Resource).filter(Resource.scenario_id == scenario_id).all()}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Assignment_ID", "Schedule_Version", "Task_Name", "Task_Priority",
        "Duration_Mins", "Resource_Name", "Resource_Type", "Start_UTC", "End_UTC"
    ])

    for a in assignments:
        t = tasks.get(a.task_id)
        r = resources.get(a.resource_id)
        writer.writerow([
            a.id,
            schedule.version_number,
            t.name if t else a.task_id,
            t.priority if t else "N/A",
            t.duration_minutes if t else 0,
            r.name if r else a.resource_id,
            r.resource_type if r else "N/A",
            a.start_at.isoformat(),
            a.end_at.isoformat()
        ])

    csv_data = output.getvalue()
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=schedule_v{schedule.version_number}_{scenario_id[:8]}.csv"}
    )
