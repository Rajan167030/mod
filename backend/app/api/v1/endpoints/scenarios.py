from typing import List, Optional
from datetime import datetime, timezone, timedelta
import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.all_models import (
    Scenario, Resource, ResourceAvailability, Task, TaskRequirement,
    ScheduleVersion, Assignment, User
)
from app.core.permissions import UserRole
from app.core.errors import NotFoundError
from app.api.deps import get_current_user, require_roles
from app.services.audit_service import log_audit_event
from app.schemas.all_schemas import (
    ScenarioCreate, ScenarioUpdate, ScenarioResponse
)

router = APIRouter(prefix="/scenarios", tags=["Scenarios"])


@router.get("", response_model=List[ScenarioResponse])
def list_scenarios(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieve all scenarios."""
    query = db.query(Scenario)
    if status:
        query = query.filter(Scenario.status == status)
    return query.order_by(Scenario.created_at.desc()).all()


@router.post("", response_model=ScenarioResponse, status_code=status.HTTP_201_CREATED)
def create_scenario(
    payload: ScenarioCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN))
):
    """Create a new operational planning scenario."""
    scenario = Scenario(
        name=payload.name,
        description=payload.description,
        status=payload.status,
        created_by=current_user.id
    )
    db.add(scenario)
    db.flush()

    log_audit_event(
        db,
        action="SCENARIO_CREATED",
        entity_type="SCENARIO",
        entity_id=scenario.id,
        actor=current_user,
        metadata={"name": scenario.name}
    )
    db.commit()
    db.refresh(scenario)
    return scenario


@router.get("/{scenario_id}", response_model=ScenarioResponse)
def get_scenario(
    scenario_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get scenario details by ID."""
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not scenario:
        raise NotFoundError("Scenario", scenario_id)
    return scenario


@router.patch("/{scenario_id}", response_model=ScenarioResponse)
def update_scenario(
    scenario_id: str,
    payload: ScenarioUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN))
):
    """Update scenario metadata or status."""
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not scenario:
        raise NotFoundError("Scenario", scenario_id)

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(scenario, field, value)

    log_audit_event(
        db,
        action="SCENARIO_UPDATED",
        entity_type="SCENARIO",
        entity_id=scenario.id,
        actor=current_user,
        metadata=update_data
    )
    db.commit()
    db.refresh(scenario)
    return scenario


@router.post("/{scenario_id}/generate-data")
def generate_synthetic_data(
    scenario_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN))
):
    """Generate or augment synthetic resources and tasks for a scenario."""
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not scenario:
        raise NotFoundError("Scenario", scenario_id)

    now_base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    # Add synthetic tactical air resources
    new_res_specs = [
        (f"IL-76-Cargo-{uuid.uuid4().hex[:4].upper()}", "HEAVY_AIRCRAFT", ["HEAVY_AIRLIFT", "NIGHT_OPS"]),
        (f"Mi-17-Support-{uuid.uuid4().hex[:4].upper()}", "TACTICAL_HELICOPTER", ["HIGH_ALTITUDE", "SEARCH_RESCUE"]),
        (f"ALH-Dhruv-{uuid.uuid4().hex[:4].upper()}", "LIGHT_HELICOPTER", ["FORWARD_RECON", "QUICK_MEDEVAC"])
    ]

    created_resources = []
    for name, rtype, quals in new_res_specs:
        res = Resource(
            scenario_id=scenario.id,
            name=name,
            resource_type=rtype,
            status="AVAILABLE",
            metadata_json={"qualifications": quals}
        )
        db.add(res)
        db.flush()
        created_resources.append(res)

        db.add(ResourceAvailability(
            resource_id=res.id,
            start_at=now_base,
            end_at=now_base + timedelta(hours=96),
            available=True
        ))

    # Add 5 synthetic tasks
    created_tasks = []
    task_specs = [
        ("Emergency Oxygen Cylinder Resupply", 90, 4, 14, "CRITICAL", "HEAVY_AIRLIFT"),
        ("Remote High-Pass Mountain Weather Sensor", 60, 6, 12, "MEDIUM", "HIGH_ALTITUDE"),
        ("Urgent Doctor Evacuation Unit", 75, 8, 16, "CRITICAL", "QUICK_MEDEVAC"),
        ("Air Base Aviation Turbine Fuel Consignment", 180, 12, 28, "HIGH", "HEAVY_AIRLIFT"),
        ("Perimeter Border Search Sweep", 90, 14, 22, "LOW", "FORWARD_RECON")
    ]

    for title, dur, e_h, l_h, prio, req in task_specs:
        task = Task(
            scenario_id=scenario.id,
            name=title,
            description=f"Generated synthetic mission item: {title}",
            duration_minutes=dur,
            earliest_start=now_base + timedelta(hours=e_h),
            latest_finish=now_base + timedelta(hours=l_h),
            priority=prio,
            status="PENDING"
        )
        db.add(task)
        db.flush()
        created_tasks.append(task)

        db.add(TaskRequirement(
            task_id=task.id,
            requirement_type="QUALIFICATION",
            requirement_value=req
        ))

    log_audit_event(
        db,
        action="SYNTHETIC_DATA_GENERATED",
        entity_type="SCENARIO",
        entity_id=scenario.id,
        actor=current_user,
        metadata={"resources_added": len(created_resources), "tasks_added": len(created_tasks)}
    )
    db.commit()

    return {
        "message": "Synthetic dataset successfully augmented",
        "scenario_id": scenario.id,
        "resources_generated": len(created_resources),
        "tasks_generated": len(created_tasks)
    }
