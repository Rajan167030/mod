"""
Alert rules: conditions a planner wants watched on a scenario's active plan. Evaluated on demand
(the header polls), each fired alert points at the object it is about so it can be opened directly.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.models.alert_models import AlertRule
from app.models.all_models import Scenario, User
from app.services.ontology_service import _Snapshot, _needs, _quals, _utc
from app.services.weather_impact import exposure

KINDS: Dict[str, Dict[str, Any]] = {
    "CRITICAL_UNASSIGNED": {"label": "Task has no aircraft", "threshold": None, "unit": None},
    "TASK_DELAY": {"label": "Task starts late", "threshold": 60, "unit": "minutes after its window opens"},
    "WEATHER_EXPOSURE": {"label": "Sortie inside a weather limit", "threshold": None, "unit": None},
    "RULE_CONFLICTS": {"label": "Active plan breaks a rule", "threshold": None, "unit": None},
    "AIRCRAFT_HOURS": {"label": "Aircraft flying too long", "threshold": 8, "unit": "planned flying hours"},
    "SINGLE_SOURCE": {"label": "Capability held by one aircraft", "threshold": None, "unit": None},
}
PRIORITY_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

DEFAULT_RULES = [
    dict(name="Critical or high task without an aircraft", kind="CRITICAL_UNASSIGNED", min_priority="HIGH", severity="CRITICAL"),
    dict(name="High-priority task more than 60 min late", kind="TASK_DELAY", threshold=60, min_priority="HIGH", severity="WARNING"),
    dict(name="Sortie flies into critical weather", kind="WEATHER_EXPOSURE", min_priority="LOW", severity="CRITICAL"),
    dict(name="Active plan has rule conflicts", kind="RULE_CONFLICTS", severity="CRITICAL"),
    dict(name="Aircraft planned over 8 h flying", kind="AIRCRAFT_HOURS", threshold=8, severity="WARNING"),
    dict(name="Capability needed by priority work held by one aircraft", kind="SINGLE_SOURCE", min_priority="HIGH", severity="WARNING"),
]


def rules(db: Session, scenario_id: str, user: Optional[User] = None) -> List[AlertRule]:
    if not db.query(Scenario).filter(Scenario.id == scenario_id).first():
        raise NotFoundError("Scenario", scenario_id)
    existing = db.query(AlertRule).filter(AlertRule.scenario_id == scenario_id).order_by(AlertRule.created_at).all()
    if existing:
        return existing
    # First visit: start the scenario with a sensible rule set the planner can edit
    for r in DEFAULT_RULES:
        db.add(AlertRule(scenario_id=scenario_id, created_by=user.id if user else None, **r))
    db.commit()
    return db.query(AlertRule).filter(AlertRule.scenario_id == scenario_id).order_by(AlertRule.created_at).all()


def validate_rule(kind: str, severity: str, min_priority: str) -> None:
    if kind not in KINDS:
        raise ValidationError(f"kind must be one of {', '.join(KINDS)}")
    if severity not in ("WARNING", "CRITICAL"):
        raise ValidationError("severity must be WARNING or CRITICAL")
    if min_priority not in PRIORITY_RANK:
        raise ValidationError("min_priority must be LOW, MEDIUM, HIGH or CRITICAL")


def evaluate(db: Session, scenario_id: str, user: Optional[User] = None) -> Dict[str, Any]:
    active_rules = [r for r in rules(db, scenario_id, user) if r.enabled]
    s = _Snapshot(db, scenario_id)
    fired: List[Dict[str, Any]] = []

    def fire(rule: AlertRule, message: str, obj_type: Optional[str] = None, obj_id: Optional[str] = None, title: str = "") -> None:
        fired.append({
            "rule_id": rule.id, "rule": rule.name, "kind": rule.kind, "severity": rule.severity, "message": message,
            "object": {"type": obj_type, "id": obj_id, "title": title} if obj_type else None,
        })

    for rule in active_rules:
        floor = PRIORITY_RANK.get(rule.min_priority, 0)
        if rule.kind == "CRITICAL_UNASSIGNED":
            for t in s.tasks.values():
                if PRIORITY_RANK.get(t.priority, 0) >= floor and t.id not in s.plan:
                    fire(rule, f"{t.name} ({t.priority.lower()}) has no aircraft in plan v{s.version.version_number if s.version else '—'}.", "task", t.id, t.name)
        elif rule.kind == "TASK_DELAY":
            limit = rule.threshold or 60
            for t in s.tasks.values():
                a = s.plan.get(t.id)
                if a and PRIORITY_RANK.get(t.priority, 0) >= floor:
                    late = (_utc(a.start_at) - _utc(t.earliest_start)).total_seconds() / 60
                    if late > limit:
                        fire(rule, f"{t.name} starts {int(late)} min after its window opens (limit {int(limit)}).", "task", t.id, t.name)
        elif rule.kind == "WEATHER_EXPOSURE":
            for t in s.tasks.values():
                a = s.plan.get(t.id)
                if not a or PRIORITY_RANK.get(t.priority, 0) < floor:
                    continue
                level = exposure(_utc(a.start_at), _utc(a.end_at), s.hours.get(t.location_id))
                if level == "CRITICAL" or (level == "WARNING" and rule.severity == "WARNING"):
                    site = s.sites.get(t.location_id)
                    fire(rule, f"{t.name} flies through a {level.lower()} hour at {site.name if site else 'its site'}.", "task", t.id, t.name)
        elif rule.kind == "RULE_CONFLICTS":
            if s.check and s.check.conflict_count:
                for c in s.check.conflicts[:10]:
                    fire(rule, c.explanation, "aircraft" if c.resource_id else None, c.resource_id, c.resource_name or "")
        elif rule.kind == "AIRCRAFT_HOURS":
            limit = rule.threshold or 8
            for r in s.resources.values():
                hours = sum(
                    (_utc(a.end_at) - _utc(a.start_at)).total_seconds() / 3600
                    for a in s.plan.values() if a.resource_id == r.id
                )
                if hours > limit:
                    fire(rule, f"{r.name} is planned for {hours:.1f} h of flying (limit {limit:g} h).", "aircraft", r.id, r.name)
        elif rule.kind == "SINGLE_SOURCE":
            serviceable = [r for r in s.resources.values() if r.status not in ("GROUNDED", "UNAVAILABLE")]
            for cap in sorted({c for t in s.tasks.values() for c in _needs(t) if PRIORITY_RANK.get(t.priority, 0) >= floor}):
                holders = [r for r in serviceable if cap in _quals(r)]
                if len(holders) <= 1:
                    who = holders[0].name if holders else "no serviceable aircraft"
                    fire(rule, f"{cap.replace('_', ' ').lower()} is held only by {who}.", "capability", cap, cap)

    order = {"CRITICAL": 0, "WARNING": 1}
    fired.sort(key=lambda f: order.get(f["severity"], 2))
    return {
        "scenario_id": scenario_id,
        "evaluated_at": datetime.now(timezone.utc),
        "active_version": s.version.version_number if s.version else None,
        "rules_checked": len(active_rules),
        "critical": sum(f["severity"] == "CRITICAL" for f in fired),
        "warning": sum(f["severity"] == "WARNING" for f in fired),
        "alerts": fired,
    }
