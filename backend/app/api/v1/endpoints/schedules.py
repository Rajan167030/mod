from typing import List, Optional
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.all_models import (
    ScheduleVersion, Assignment, Scenario, Resource, Task, User
)
from app.core.permissions import UserRole
from app.core.errors import NotFoundError
from app.api.deps import get_current_user, require_roles
from app.services.audit_service import log_audit_event
from app.services.conflict_service import check_schedule_conflicts
from app.schemas.all_schemas import (
    ScheduleVersionResponse, AssignmentResponse, ValidationResult
)

router = APIRouter(tags=["Schedules"])


@router.get("/scenarios/{scenario_id}/schedules", response_model=List[ScheduleVersionResponse])
def list_scenario_schedules(
    scenario_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all schedule versions for a scenario."""
    schedules = db.query(ScheduleVersion).filter(
        ScheduleVersion.scenario_id == scenario_id
    ).order_by(ScheduleVersion.version_number.desc()).all()
    return schedules


@router.get("/schedules/{schedule_id}", response_model=ScheduleVersionResponse)
def get_schedule(
    schedule_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieve full schedule version with decorated assignment details."""
    schedule = db.query(ScheduleVersion).filter(ScheduleVersion.id == schedule_id).first()
    if not schedule:
        raise NotFoundError("ScheduleVersion", schedule_id)

    # Decorate assignments with task and resource names for frontend clarity
    assignments = db.query(Assignment).filter(Assignment.schedule_version_id == schedule_id).all()
    tasks_map = {t.id: t for t in db.query(Task).filter(Task.scenario_id == schedule.scenario_id).all()}
    res_map = {r.id: r for r in db.query(Resource).filter(Resource.scenario_id == schedule.scenario_id).all()}

    assignment_payloads = []
    for a in assignments:
        t = tasks_map.get(a.task_id)
        r = res_map.get(a.resource_id)
        assignment_payloads.append(AssignmentResponse(
            id=a.id,
            schedule_version_id=a.schedule_version_id,
            task_id=a.task_id,
            resource_id=a.resource_id,
            start_at=a.start_at,
            end_at=a.end_at,
            task_name=t.name if t else "Unknown Task",
            resource_name=r.name if r else "Unknown Resource",
            priority=t.priority if t else "MEDIUM",
            task_location_id=t.location_id if t else None,
        ))

    return ScheduleVersionResponse(
        id=schedule.id,
        scenario_id=schedule.scenario_id,
        version_number=schedule.version_number,
        parent_version_id=schedule.parent_version_id,
        status=schedule.status,
        created_by=schedule.created_by,
        created_at=schedule.created_at,
        assignments=assignment_payloads
    )


@router.post("/schedules/{schedule_id}/validate", response_model=ValidationResult)
@router.post("/schedules/{schedule_id}/conflicts/check", response_model=ValidationResult)
def validate_schedule(
    schedule_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Execute independent conflict validation across 5 hard constraint dimensions."""
    result = check_schedule_conflicts(db, schedule_id)
    return result
