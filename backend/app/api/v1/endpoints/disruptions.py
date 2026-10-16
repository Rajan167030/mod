from typing import List
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.all_models import (
    Scenario, Disruption, Resource, ResourceAvailability, Task, ScheduleVersion, User
)
from app.core.permissions import UserRole
from app.core.errors import NotFoundError, ValidationError
from app.api.deps import get_current_user, require_roles
from app.services.audit_service import log_audit_event
from app.services.conflict_service import check_schedule_conflicts
from app.schemas.all_schemas import (
    DisruptionCreate, DisruptionResponse, ValidationResult
)

router = APIRouter(tags=["Disruptions"])


@router.get("/scenarios/{scenario_id}/disruptions", response_model=List[DisruptionResponse])
def list_disruptions(
    scenario_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List historical synthetic disruptions applied to this scenario."""
    return db.query(Disruption).filter(
        Disruption.scenario_id == scenario_id
    ).order_by(Disruption.created_at.desc()).all()


@router.post("/scenarios/{scenario_id}/disruptions", response_model=DisruptionResponse, status_code=status.HTTP_201_CREATED)
def apply_synthetic_disruption(
    scenario_id: str,
    payload: DisruptionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN))
):
    """
    Inject a synthetic disruption into the scenario state, saving the disruption record,
    updating relevant entity states, and triggering conflict evaluation.
    """
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not scenario:
        raise NotFoundError("Scenario", scenario_id)

    dtype = payload.type
    params = payload.payload_json

    # 1. Apply perturbation based on type
    if dtype == "RESOURCE_UNAVAILABLE":
        resource_id = params.get("resource_id")
        resource = db.query(Resource).filter(
            Resource.id == resource_id, Resource.scenario_id == scenario_id
        ).first()
        if not resource:
            raise ValidationError(f"Resource '{resource_id}' not found in scenario.")
        resource.status = params.get("new_status", "GROUNDED")

    elif dtype == "WINDOW_SHIFT":
        # Add an emergency blackout window
        resource_id = params.get("resource_id")
        resource = db.query(Resource).filter(
            Resource.id == resource_id, Resource.scenario_id == scenario_id
        ).first()
        if not resource:
            raise ValidationError(f"Resource '{resource_id}' not found in scenario.")

        start_at_raw = params.get("blackout_start")
        end_at_raw = params.get("blackout_end")
        start_at = datetime.fromisoformat(start_at_raw) if start_at_raw else datetime.now(timezone.utc)
        end_at = datetime.fromisoformat(end_at_raw) if end_at_raw else start_at + timedelta(hours=8)

        blackout = ResourceAvailability(
            resource_id=resource.id,
            start_at=start_at,
            end_at=end_at,
            available=False
        )
        db.add(blackout)

    elif dtype == "DURATION_SURGE":
        task_id = params.get("task_id")
        surge_minutes = params.get("surge_minutes", 60)
        task = db.query(Task).filter(Task.id == task_id, Task.scenario_id == scenario_id).first()
        if not task:
            raise ValidationError(f"Task '{task_id}' not found in scenario.")
        task.duration_minutes += surge_minutes

    elif dtype == "DEADLINE_TIGHTEN":
        task_id = params.get("task_id")
        tighten_hours = params.get("tighten_hours", 4)
        task = db.query(Task).filter(Task.id == task_id, Task.scenario_id == scenario_id).first()
        if not task:
            raise ValidationError(f"Task '{task_id}' not found in scenario.")
        task.latest_finish -= timedelta(hours=tighten_hours)

    else:
        raise ValidationError(f"Unsupported disruption type: '{dtype}'")

    # 2. Record Disruption in database
    disruption = Disruption(
        scenario_id=scenario_id,
        type=dtype,
        payload_json=params,
        created_by=current_user.id
    )
    db.add(disruption)
    db.flush()

    log_audit_event(
        db,
        action="DISRUPTION_INJECTED",
        entity_type="DISRUPTION",
        entity_id=disruption.id,
        actor=current_user,
        metadata={"type": dtype, "parameters": params}
    )
    db.commit()
    db.refresh(disruption)

    return disruption
