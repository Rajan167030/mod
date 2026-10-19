"""
Live exercise endpoints. Each GET advances the simulated clock and applies due events;
replanning runs in the background. Decisions go through the normal adopt/approve path.
"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.api.v1.endpoints.approvals import approve_proposal
from app.api.v1.endpoints.coa import adopt_course_of_action
from app.core.errors import PermissionDeniedError, ValidationError
from app.core.permissions import UserRole, has_required_role
from app.db.session import get_db
from app.models.all_models import ScheduleVersion, User
from app.models.replay_models import ReplaySession
from app.schemas.all_schemas import ApprovalDecisionRequest
from app.services import replay_service as rs

router = APIRouter(prefix="/replays", tags=["Live exercise"])


class ReplayStart(BaseModel):
    script: str = "winter_lift"
    speed: float = 60.0


class ReplayControl(BaseModel):
    action: Literal["pause", "resume", "speed", "skip"]
    speed: Optional[float] = None


class ReplayDecision(BaseModel):
    action: Literal["adopt", "approve", "replan"]
    course: Optional[str] = None  # COA key, for adopt
    run_id: Optional[str] = None  # for approve
    reason: str = Field("", max_length=500)


class ReplayState(BaseModel):
    id: str
    scenario_id: str
    script: str
    title: str
    status: str
    speed: float
    speeds: List[float]
    sim_t0: datetime
    sim_now: datetime
    end_min: int
    active_version_id: Optional[str]
    active_version_number: Optional[int]
    events: List[Dict[str, Any]]
    summary: Dict[str, Any]


def _state(db: Session, s: ReplaySession) -> ReplayState:
    version = rs._active_version(db, s.scenario_id)
    return ReplayState(
        id=s.id,
        scenario_id=s.scenario_id,
        script=s.script_key,
        title=rs.SCRIPTS[s.script_key]["title"],
        status=s.status,
        speed=s.speed,
        speeds=list(rs.SPEEDS),
        sim_t0=s.sim_t0,
        sim_now=rs.sim_now(s),
        end_min=rs.SCRIPTS[s.script_key]["end_min"],
        active_version_id=version.id if version else None,
        active_version_number=version.version_number if version else None,
        events=s.events_json,
        summary=rs.summary(db, s),
    )


@router.post("", response_model=ReplayState, status_code=status.HTTP_201_CREATED)
def start(
    payload: ReplayStart,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN)),
):
    s = rs.start_replay(db, user, payload.script, payload.speed)
    return _state(db, s)


@router.get("/latest", response_model=Optional[ReplayState])
def latest(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Most recent exercise that still exists, so the page can reconnect after a reload."""
    s = db.query(ReplaySession).order_by(ReplaySession.created_at.desc()).first()
    if not s:
        return None
    rs.tick(db, s, user)
    return _state(db, s)


@router.get("/{replay_id}", response_model=ReplayState)
def get_state(replay_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = rs.get_session(db, replay_id)
    rs.tick(db, s, user)
    return _state(db, s)


@router.post("/{replay_id}/control", response_model=ReplayState)
def control(
    replay_id: str,
    payload: ReplayControl,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN)),
):
    s = rs.control(db, rs.get_session(db, replay_id), payload.action, payload.speed)
    rs.tick(db, s, user)
    return _state(db, s)


@router.post("/{replay_id}/events/{idx}/decision", response_model=ReplayState)
def decide(
    replay_id: str,
    idx: int,
    payload: ReplayDecision,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    adopt   (planner/admin): store the chosen course of action as a proposal
    approve (reviewer/admin): approve that proposal, making it the active plan
    replan  (planner/admin): solve the event's courses of action again (e.g. after they expired)
    """
    s = rs.get_session(db, replay_id)
    if not 0 <= idx < len(s.events_json):
        raise ValidationError("Unknown event.")
    event = s.events_json[idx]

    if payload.action == "replan":
        if not has_required_role(user.role, [UserRole.PLANNER, UserRole.ADMIN]):
            raise PermissionDeniedError("re-plan an exercise event")
        rs.restart_replan(db, s, idx, user)
    elif payload.action == "adopt":
        if not has_required_role(user.role, [UserRole.PLANNER, UserRole.ADMIN]):
            raise PermissionDeniedError("adopt a plan")
        if not event.get("coa_set_id") or not payload.course:
            raise ValidationError("No plans are ready for this event yet.")
        adopted = adopt_course_of_action(event["coa_set_id"], payload.course, db=db, current_user=user)
        rs.record_decision(db, s, idx, {
            "stage": "ADOPTED", "course": payload.course, "run_id": adopted.run_id,
            "version_id": adopted.proposed_version_id, "version_number": adopted.proposed_version_number,
            "by": user.email,
        })
    else:
        if not has_required_role(user.role, [UserRole.REVIEWER, UserRole.ADMIN]):
            raise PermissionDeniedError("approve a plan")
        decision = event.get("decision") or {}
        run_id = payload.run_id or decision.get("run_id")
        if not run_id:
            raise ValidationError("Adopt a plan before approving it.")
        reason = payload.reason.strip() or f"Exercise: approved response to '{event['title']}'."
        if len(reason) < 10:
            raise ValidationError("Give a reason of at least 10 characters.")
        approve_proposal(run_id, ApprovalDecisionRequest(decision="APPROVED", reason=reason), db=db, current_user=user)
        rs.record_decision(db, s, idx, {**decision, "stage": "APPROVED", "approved_by": user.email, "reason": reason})

    db.refresh(s)
    return _state(db, s)


@router.delete("/{replay_id}", status_code=status.HTTP_204_NO_CONTENT)
def close(
    replay_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN)),
):
    rs.close_replay(db, rs.get_session(db, replay_id), user)
