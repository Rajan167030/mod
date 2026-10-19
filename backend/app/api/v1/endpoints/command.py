"""Assigning missions by hand, force capacity, and running the plan on the day."""
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.permissions import UserRole
from app.db.session import get_db
from app.models.all_models import User
from app.schemas.all_schemas import as_utc
from app.services import capacity_service, execution_service, planning_service

router = APIRouter(tags=["Command"])
planners = require_roles(UserRole.PLANNER, UserRole.ADMIN)


class AssignRequest(BaseModel):
    resource_id: str
    crew_id: Optional[str] = None
    start_at: datetime

    @field_validator("start_at")
    @classmethod
    def _utc(cls, v):
        return as_utc(v)


class SortieAction(BaseModel):
    action: Literal["launch", "land", "abort"]
    at: Optional[datetime] = None
    reason: Optional[str] = Field(None, max_length=500)
    # Abort because of the aircraft: block it for this many hours from now
    ground_hours: Optional[float] = Field(None, gt=0, le=72)

    @field_validator("at")
    @classmethod
    def _utc(cls, v):
        return as_utc(v)


@router.get("/tasks/{task_id}/options")
def task_options(task_id: str, from_now: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Every aircraft and crew that can fly this mission without moving the rest of the active plan."""
    return planning_service.task_options(db, task_id, not_before=datetime.now(timezone.utc) if from_now else None)


@router.post("/tasks/{task_id}/assign")
def assign(task_id: str, payload: AssignRequest, db: Session = Depends(get_db), user: User = Depends(planners)):
    """Put the mission on the chosen aircraft and crew as a proposal; a reviewer approves it."""
    return planning_service.assign_option(db, task_id, payload.resource_id, payload.crew_id, payload.start_at, user)


@router.get("/capacity/{scenario_id}")
def capacity(scenario_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return capacity_service.capacity(db, scenario_id)


@router.get("/execution/{scenario_id}")
def execution_board(scenario_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return execution_service.board(db, scenario_id)


@router.post("/execution/sortie/{assignment_id}")
def sortie_action(assignment_id: str, payload: SortieAction, db: Session = Depends(get_db), user: User = Depends(planners)):
    return execution_service.act(db, assignment_id, payload.action, user, payload.at, payload.reason, payload.ground_hours)
