from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.models.all_models import AuditEvent, User


def log_audit_event(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    actor: Optional[User] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> AuditEvent:
    """Safely log an audit event, stripping sensitive keys from metadata."""
    safe_metadata = {}
    if metadata:
        for k, v in metadata.items():
            # Filter out sensitive fields
            if any(secret in k.lower() for secret in ["password", "token", "secret", "key", "auth"]):
                continue
            safe_metadata[k] = v

    event = AuditEvent(
        actor_id=actor.id if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else None,
        metadata_json=safe_metadata
    )
    db.add(event)
    db.flush()
    return event
