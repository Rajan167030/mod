"""Scenario branches: copy a scenario to try changes, compare any two scenarios side by side."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.permissions import UserRole
from app.db.session import get_db
from app.models.all_models import User
from app.services import branch_service

router = APIRouter(prefix="/branches", tags=["Scenario branches"])


class BranchIn(BaseModel):
    name: Optional[str] = Field(None, max_length=255)


@router.post("/{scenario_id}", status_code=status.HTTP_201_CREATED)
def create_branch(
    scenario_id: str, payload: BranchIn, db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN)),
):
    b = branch_service.create_branch(db, scenario_id, payload.name, user)
    return {"id": b.id, "name": b.name, "parent_scenario_id": b.parent_scenario_id}


@router.get("/compare")
def compare(
    a: str = Query(...), b: str = Query(...),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return branch_service.compare(db, a, b)


@router.delete("/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_branch(
    scenario_id: str, db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN)),
):
    branch_service.delete_branch(db, scenario_id, user)
