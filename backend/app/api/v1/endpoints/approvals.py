from datetime import datetime, timezone
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.all_models import (
    OptimisationRun, ScheduleVersion, Approval, User
)
from app.core.permissions import UserRole
from app.core.errors import NotFoundError, ValidationError, VersionConflictError
from app.api.deps import get_current_user, require_roles
from app.services.audit_service import log_audit_event
from app.services.conflict_service import check_schedule_conflicts
from app.schemas.all_schemas import (
    ApprovalDecisionRequest, ApprovalResponse
)

router = APIRouter(tags=["Approvals"])


@router.post("/optimisation-runs/{run_id}/approve", response_model=ApprovalResponse)
def approve_proposal(
    run_id: str,
    payload: ApprovalDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.REVIEWER, UserRole.ADMIN))
):
    """
    Approve an optimisation run's proposed schedule version.
    Enforces independent validation check and stale parent version protection.
    """
    run = db.query(OptimisationRun).filter(OptimisationRun.id == run_id).first()
    if not run:
        raise NotFoundError("OptimisationRun", run_id)

    proposed_schedule = db.query(ScheduleVersion).filter(
        ScheduleVersion.id == run.schedule_version_id
    ).first()
    if not proposed_schedule:
        raise NotFoundError("Proposed ScheduleVersion", run.schedule_version_id)

    if proposed_schedule.status == "APPROVED":
        raise ValidationError("This proposal has already been approved.")

    # 1. Independent validation requirement
    val_result = check_schedule_conflicts(db, proposed_schedule.id)
    if not val_result.is_valid:
        raise ValidationError(
            f"Cannot approve proposal: Independent validator detected {val_result.conflict_count} critical conflicts."
        )

    # 2. Check stale parent version protection
    if proposed_schedule.parent_version_id:
        parent = db.query(ScheduleVersion).filter(ScheduleVersion.id == proposed_schedule.parent_version_id).first()
        if parent and parent.status == "SUPERSEDED":
            raise VersionConflictError(
                "Stale approval request: The baseline parent schedule has already been superseded by a newer version."
            )

    # 3. Mark previous active/approved schedules as SUPERSEDED
    db.query(ScheduleVersion).filter(
        ScheduleVersion.scenario_id == proposed_schedule.scenario_id,
        ScheduleVersion.id != proposed_schedule.id,
        ScheduleVersion.status == "APPROVED"
    ).update({"status": "SUPERSEDED"})

    # 4. Promote proposed schedule to APPROVED
    proposed_schedule.status = "APPROVED"

    # 5. Record Approval
    approval = Approval(
        optimisation_run_id=run.id,
        reviewer_id=current_user.id,
        decision="APPROVED",
        reason=payload.reason
    )
    db.add(approval)
    db.flush()

    # 6. Audit Trail
    log_audit_event(
        db,
        action="PROPOSAL_APPROVED",
        entity_type="SCHEDULE_VERSION",
        entity_id=proposed_schedule.id,
        actor=current_user,
        metadata={
            "optimisation_run_id": run.id,
            "version_number": proposed_schedule.version_number,
            "reason": payload.reason
        }
    )
    db.commit()
    db.refresh(approval)

    return ApprovalResponse(
        id=approval.id,
        optimisation_run_id=approval.optimisation_run_id,
        reviewer_id=approval.reviewer_id,
        reviewer_email=current_user.email,
        decision=approval.decision,
        reason=approval.reason,
        created_at=approval.created_at
    )


@router.post("/optimisation-runs/{run_id}/reject", response_model=ApprovalResponse)
def reject_proposal(
    run_id: str,
    payload: ApprovalDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.REVIEWER, UserRole.ADMIN))
):
    """
    Reject an optimisation run's proposed schedule version with mandatory justification.
    """
    run = db.query(OptimisationRun).filter(OptimisationRun.id == run_id).first()
    if not run:
        raise NotFoundError("OptimisationRun", run_id)

    proposed_schedule = db.query(ScheduleVersion).filter(
        ScheduleVersion.id == run.schedule_version_id
    ).first()
    if not proposed_schedule:
        raise NotFoundError("Proposed ScheduleVersion", run.schedule_version_id)

    proposed_schedule.status = "REJECTED"

    approval = Approval(
        optimisation_run_id=run.id,
        reviewer_id=current_user.id,
        decision="REJECTED",
        reason=payload.reason
    )
    db.add(approval)
    db.flush()

    log_audit_event(
        db,
        action="PROPOSAL_REJECTED",
        entity_type="SCHEDULE_VERSION",
        entity_id=proposed_schedule.id,
        actor=current_user,
        metadata={
            "optimisation_run_id": run.id,
            "version_number": proposed_schedule.version_number,
            "reason": payload.reason
        }
    )
    db.commit()
    db.refresh(approval)

    return ApprovalResponse(
        id=approval.id,
        optimisation_run_id=approval.optimisation_run_id,
        reviewer_id=approval.reviewer_id,
        reviewer_email=current_user.email,
        decision=approval.decision,
        reason=approval.reason,
        created_at=approval.created_at
    )
