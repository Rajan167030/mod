from typing import List, Optional
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.all_models import Task, TaskRequirement, User
from app.models.weather_models import Location
from app.core.permissions import UserRole
from app.core.errors import NotFoundError, ValidationError
from app.api.deps import get_current_user, require_roles
from app.services.audit_service import log_audit_event
from app.schemas.all_schemas import (
    TaskCreate, TaskUpdate, TaskResponse
)

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.get("", response_model=List[TaskResponse])
def list_tasks(
    scenario_id: Optional[str] = None,
    priority: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List tasks with optional scenario, priority, and status filters."""
    query = db.query(Task)
    if scenario_id:
        query = query.filter(Task.scenario_id == scenario_id)
    if priority:
        query = query.filter(Task.priority == priority)
    if status:
        query = query.filter(Task.status == status)
    return query.order_by(Task.earliest_start.asc()).all()


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN))
):
    """Create a new mission task with operational requirements."""
    if payload.location_id:
        loc = db.query(Location).filter_by(id=payload.location_id).first()
        if not loc or loc.scenario_id != payload.scenario_id:
            raise ValidationError("location_id must be a site in the same scenario.")
    task = Task(
        scenario_id=payload.scenario_id,
        name=payload.name,
        description=payload.description,
        duration_minutes=payload.duration_minutes,
        earliest_start=payload.earliest_start,
        latest_finish=payload.latest_finish,
        priority=payload.priority,
        status=payload.status,
        location_id=payload.location_id,
    )
    db.add(task)
    db.flush()

    # Add requirements
    for req in payload.requirements:
        db.add(TaskRequirement(
            task_id=task.id,
            requirement_type=req.requirement_type,
            requirement_value=req.requirement_value
        ))

    log_audit_event(
        db,
        action="TASK_CREATED",
        entity_type="TASK",
        entity_id=task.id,
        actor=current_user,
        metadata={"name": task.name, "priority": task.priority, "duration": task.duration_minutes}
    )
    db.commit()
    db.refresh(task)
    return task


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get single task details by ID."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise NotFoundError("Task", task_id)
    return task


@router.patch("/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: str,
    payload: TaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN))
):
    """Update task parameters, window, or priority."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise NotFoundError("Task", task_id)

    update_data = payload.model_dump(exclude_unset=True)
    for k, v in update_data.items():
        setattr(task, k, v)

    log_audit_event(
        db,
        action="TASK_UPDATED",
        entity_type="TASK",
        entity_id=task.id,
        actor=current_user,
        metadata=update_data
    )
    db.commit()
    db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN))
):
    """Delete a task and its requirements."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise NotFoundError("Task", task_id)

    log_audit_event(
        db,
        action="TASK_DELETED",
        entity_type="TASK",
        entity_id=task.id,
        actor=current_user,
        metadata={"name": task.name}
    )
    db.delete(task)
    db.commit()
    return None
