"""Alert rules (CRUD) and on-demand evaluation against a scenario's active plan."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.errors import NotFoundError
from app.core.permissions import UserRole
from app.db.session import get_db
from app.models.alert_models import AlertRule
from app.models.all_models import User
from app.services import alerts_service
from app.services.audit_service import log_audit_event

router = APIRouter(prefix="/alert-rules", tags=["Alerts"])


class RuleIn(BaseModel):
    name: str = Field(..., min_length=3, max_length=200)
    kind: str
    threshold: Optional[float] = Field(None, ge=0)
    min_priority: str = "HIGH"
    severity: str = "WARNING"
    enabled: bool = True


class RuleOut(RuleIn):
    id: str
    scenario_id: str
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/kinds")
def kinds(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return alerts_service.KINDS


@router.get("/{scenario_id}", response_model=List[RuleOut])
def list_rules(scenario_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return alerts_service.rules(db, scenario_id, user)


@router.get("/{scenario_id}/evaluate")
def evaluate(scenario_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return alerts_service.evaluate(db, scenario_id, user)


@router.post("/{scenario_id}", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(
    scenario_id: str, payload: RuleIn, db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN)),
):
    alerts_service.rules(db, scenario_id, user)  # validates the scenario and seeds defaults
    alerts_service.validate_rule(payload.kind, payload.severity, payload.min_priority)
    rule = AlertRule(scenario_id=scenario_id, created_by=user.id, **payload.model_dump())
    db.add(rule)
    db.flush()
    log_audit_event(db, action="ALERT_RULE_CREATED", entity_type="ALERT_RULE", entity_id=rule.id, actor=user, metadata=payload.model_dump())
    db.commit()
    return rule


@router.put("/rule/{rule_id}", response_model=RuleOut)
def update_rule(
    rule_id: str, payload: RuleIn, db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN)),
):
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise NotFoundError("Alert rule", rule_id)
    alerts_service.validate_rule(payload.kind, payload.severity, payload.min_priority)
    for k, v in payload.model_dump().items():
        setattr(rule, k, v)
    log_audit_event(db, action="ALERT_RULE_UPDATED", entity_type="ALERT_RULE", entity_id=rule.id, actor=user, metadata=payload.model_dump())
    db.commit()
    return rule


@router.delete("/rule/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(UserRole.PLANNER, UserRole.ADMIN))):
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise NotFoundError("Alert rule", rule_id)
    log_audit_event(db, action="ALERT_RULE_DELETED", entity_type="ALERT_RULE", entity_id=rule.id, actor=user, metadata={"name": rule.name})
    db.delete(rule)
    db.commit()
