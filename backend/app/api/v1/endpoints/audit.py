from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.all_models import AuditEvent, User
from app.core.permissions import UserRole
from app.api.deps import require_roles
from app.schemas.all_schemas import AuditEventResponse

router = APIRouter(prefix="/audit-events", tags=["Audit Ledger"])


@router.get("", response_model=List[AuditEventResponse])
def list_audit_events(
    entity_type: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.REVIEWER, UserRole.ADMIN, UserRole.PLANNER))
):
    """Retrieve immutable audit ledger records with filtering and pagination."""
    query = db.query(AuditEvent)
    if entity_type:
        query = query.filter(AuditEvent.entity_type == entity_type)
    if action:
        query = query.filter(AuditEvent.action == action)

    events = query.order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit).all()

    # Pre-fetch user emails for display
    user_ids = {e.actor_id for e in events if e.actor_id}
    users = {u.id: u.email for u in db.query(User).filter(User.id.in_(user_ids)).all()}

    return [
        AuditEventResponse(
            id=e.id,
            actor_id=e.actor_id,
            actor_email=users.get(e.actor_id),
            action=e.action,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            metadata_json=e.metadata_json,
            created_at=e.created_at
        ) for e in events
    ]
