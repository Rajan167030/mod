"""
Courses of Action endpoints: generate alternative plans side by side, then adopt one
as a proposal for review. Adoption never activates a schedule on its own.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.errors import ValidationError
from app.core.permissions import UserRole
from app.db.session import get_db
from app.models.all_models import ScheduleVersion, User
from app.schemas.coa_schemas import CoaAdoptResponse, CoaRequest, CoaSetResponse
from app.services.audit_service import log_audit_event
from app.services.coa_service import (
    PROFILES,
    generate_courses_of_action,
    get_result_for_adoption,
    get_stored_set,
)
from app.services.proposal_service import persist_proposal

router = APIRouter(tags=["Courses of Action"])


@router.post("/schedules/{schedule_id}/courses-of-action", response_model=CoaSetResponse)
def create_courses_of_action(
    schedule_id: str,
    payload: CoaRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN)),
):
    """Solve the schedule under each planning intent and return the plans for comparison."""
    if not 1 <= payload.time_limit_seconds <= 60:
        raise ValidationError("time_limit_seconds must be between 1 and 60.")
    result = generate_courses_of_action(
        db, schedule_id, current_user, payload.include_weather, payload.time_limit_seconds
    )
    log_audit_event(
        db,
        action="COA_GENERATED",
        entity_type="SCHEDULE_VERSION",
        entity_id=schedule_id,
        actor=current_user,
        metadata={
            "coa_set_id": result.coa_set_id,
            "include_weather": payload.include_weather,
            "recommended": next((c.key for c in result.courses if c.recommended), None),
        },
    )
    db.commit()
    return result


@router.get("/courses-of-action/{coa_set_id}", response_model=CoaSetResponse)
def get_courses_of_action(
    coa_set_id: str,
    current_user: User = Depends(get_current_user),
):
    return get_stored_set(coa_set_id).response


@router.post("/courses-of-action/{coa_set_id}/{key}/adopt", response_model=CoaAdoptResponse)
def adopt_course_of_action(
    coa_set_id: str,
    key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN)),
):
    """Store the chosen plan as a PROPOSED schedule version; it still needs reviewer approval."""
    entry, result = get_result_for_adoption(coa_set_id, key)
    baseline = db.query(ScheduleVersion).filter(ScheduleVersion.id == entry.baseline_id).first()
    if baseline is None or baseline.status in ("SUPERSEDED", "REJECTED"):
        raise ValidationError("The baseline these plans were built from is no longer current. Generate new plans.")

    profile = next(p for p in PROFILES if p.key == key)
    result.metrics = {**(result.metrics or {}), "course_of_action": key, "coa_set_id": coa_set_id}
    now = datetime.now(timezone.utc)
    version, run, _ = persist_proposal(db, baseline, result, current_user, now, now)

    log_audit_event(
        db,
        action="COA_ADOPTED",
        entity_type="OPTIMISATION_RUN",
        entity_id=run.id,
        actor=current_user,
        metadata={
            "coa_set_id": coa_set_id,
            "course_of_action": key,
            "label": profile.label,
            "proposed_version_id": version.id if version else None,
        },
    )
    db.commit()
    return CoaAdoptResponse(
        run_id=run.id,
        proposed_version_id=version.id if version else None,
        proposed_version_number=version.version_number if version else None,
        status=run.status,
    )
