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
    DisruptionCreate, DisruptionResponse, ValidationResult, RESOURCE_STATUSES, as_utc
)

router = APIRouter(tags=["Disruptions"])


def _number(params: dict, key: str, default: float, lo: float, hi: float) -> float:
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
        raise ValidationError(f"{key} must be a number between {lo:g} and {hi:g}.")
    return value


def _timestamp(params: dict, key: str):
    raw = params.get(key)
    if not raw:
        return None
    try:
        return as_utc(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
    except ValueError:
        raise ValidationError(f"{key} must be an ISO 8601 timestamp.")


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
        new_status = str(params.get("new_status", "GROUNDED")).upper()
        if new_status not in RESOURCE_STATUSES:
            raise ValidationError(f"new_status must be one of {', '.join(RESOURCE_STATUSES)}.")
        resource.status = new_status

    elif dtype == "WINDOW_SHIFT":
        # Add an emergency blackout window
        resource_id = params.get("resource_id")
        resource = db.query(Resource).filter(
            Resource.id == resource_id, Resource.scenario_id == scenario_id
        ).first()
        if not resource:
            raise ValidationError(f"Resource '{resource_id}' not found in scenario.")

        start_at = _timestamp(params, "blackout_start") or datetime.now(timezone.utc)
        end_at = _timestamp(params, "blackout_end") or start_at + timedelta(hours=8)
        if end_at <= start_at:
            raise ValidationError("blackout_end must be after blackout_start.")

        blackout = ResourceAvailability(
            resource_id=resource.id,
            start_at=start_at,
            end_at=end_at,
            available=False
        )
        db.add(blackout)

    elif dtype == "DURATION_SURGE":
        task_id = params.get("task_id")
        surge_minutes = int(_number(params, "surge_minutes", 60, -24 * 60, 24 * 60))
        task = db.query(Task).filter(Task.id == task_id, Task.scenario_id == scenario_id).first()
        if not task:
            raise ValidationError(f"Task '{task_id}' not found in scenario.")
        if task.duration_minutes + surge_minutes <= 0:
            raise ValidationError("The surge would leave the task with no duration.")
        task.duration_minutes += surge_minutes

    elif dtype == "DEADLINE_TIGHTEN":
        task_id = params.get("task_id")
        tighten_hours = _number(params, "tighten_hours", 4, 0, 24 * 7)
        task = db.query(Task).filter(Task.id == task_id, Task.scenario_id == scenario_id).first()
        if not task:
            raise ValidationError(f"Task '{task_id}' not found in scenario.")
        new_finish = task.latest_finish - timedelta(hours=tighten_hours)
        if new_finish <= task.earliest_start:
            raise ValidationError("Tightening by that much would end the window before it starts.")
        task.latest_finish = new_finish

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
