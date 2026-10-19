"""
Scenario branches: copy a scenario to try changes safely, then compare it with its parent
(or any other scenario) on the same measures, task by task.
"""
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.models.all_models import Scenario, User
from app.services.audit_service import log_audit_event
from app.services.ontology_service import _Snapshot, _utc
from app.services.scenario_admin import clone_scenario, delete_scenario
from app.services.weather_impact import exposure

PRIORITY_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def create_branch(db: Session, source_id: str, name: Optional[str], user: User) -> Scenario:
    source = db.query(Scenario).filter(Scenario.id == source_id).first()
    if not source:
        raise NotFoundError("Scenario", source_id)
    branch = clone_scenario(
        db, source_id,
        name=(name or f"Branch of {source.name}")[:255],
        description=f"Branch of '{source.name}' for trying changes. Compare it with the parent before acting.",
        created_by=user.id,
    )
    branch.parent_scenario_id = source.id
    log_audit_event(db, action="SCENARIO_BRANCHED", entity_type="SCENARIO", entity_id=branch.id, actor=user,
                    metadata={"parent_scenario_id": source.id, "name": branch.name})
    db.commit()
    return branch


def delete_branch(db: Session, scenario_id: str, user: User) -> None:
    sc = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not sc:
        raise NotFoundError("Scenario", scenario_id)
    if not sc.parent_scenario_id:
        raise ValidationError("Only branches can be deleted here.")
    name = sc.name
    delete_scenario(db, scenario_id)
    log_audit_event(db, action="BRANCH_DELETED", entity_type="SCENARIO", entity_id=scenario_id, actor=user, metadata={"name": name})
    db.commit()


def _measures(s: _Snapshot) -> Dict[str, Any]:
    delay = 0.0
    hours = 0.0
    exposed_crit = exposed_warn = 0
    for t in s.tasks.values():
        a = s.plan.get(t.id)
        if not a:
            continue
        delay += max(0.0, (_utc(a.start_at) - _utc(t.earliest_start)).total_seconds() / 60)
        hours += (_utc(a.end_at) - _utc(a.start_at)).total_seconds() / 3600
        level = exposure(_utc(a.start_at), _utc(a.end_at), s.hours.get(t.location_id))
        exposed_crit += level == "CRITICAL"
        exposed_warn += level == "WARNING"
    unassigned = [t for t in s.tasks.values() if t.id not in s.plan]
    return {
        "Plan version": s.version.version_number if s.version else None,
        "Aircraft": len(s.resources),
        "Serviceable aircraft": sum(r.status not in ("GROUNDED", "UNAVAILABLE") for r in s.resources.values()),
        "Tasks": len(s.tasks),
        "Tasks flown": len(s.tasks) - len(unassigned),
        "Critical without aircraft": sum(t.priority == "CRITICAL" for t in unassigned),
        "High without aircraft": sum(t.priority == "HIGH" for t in unassigned),
        "Rule conflicts": s.check.conflict_count if s.check else 0,
        "Total delay (min)": int(delay),
        "Planned flying (h)": round(hours, 1),
        "Sorties in critical weather": exposed_crit,
        "Sorties in warning weather": exposed_warn,
    }


# For each measure: is a higher number better (True), worse (False), or neutral (None)
DIRECTION = {
    "Plan version": None, "Aircraft": True, "Serviceable aircraft": True, "Tasks": None, "Tasks flown": True,
    "Critical without aircraft": False, "High without aircraft": False, "Rule conflicts": False,
    "Total delay (min)": False, "Planned flying (h)": None, "Sorties in critical weather": False,
    "Sorties in warning weather": False,
}


def compare(db: Session, a_id: str, b_id: str) -> Dict[str, Any]:
    a, b = _Snapshot(db, a_id), _Snapshot(db, b_id)
    ma, mb = _measures(a), _measures(b)
    measures = [
        {"name": k, "a": ma[k], "b": mb[k], "higher_is_better": DIRECTION[k]}
        for k in ma
    ]

    a_tasks = {t.name: t for t in a.tasks.values()}
    b_tasks = {t.name: t for t in b.tasks.values()}

    def placement(s: _Snapshot, t) -> Optional[Dict[str, Any]]:
        asg = s.plan.get(t.id)
        if not asg:
            return None
        return {"aircraft": s.resources[asg.resource_id].name if asg.resource_id in s.resources else None,
                "start": _utc(asg.start_at), "end": _utc(asg.end_at)}

    changes = []
    for name in sorted(set(a_tasks) | set(b_tasks)):
        ta, tb = a_tasks.get(name), b_tasks.get(name)
        pa = placement(a, ta) if ta else None
        pb = placement(b, tb) if tb else None
        if ta and not tb:
            kind = "ONLY_IN_A"
        elif tb and not ta:
            kind = "ONLY_IN_B"
        elif pa is None and pb is None:
            continue  # same in both: no aircraft either side
        elif pa is None:
            kind = "FLOWN_ONLY_IN_B"
        elif pb is None:
            kind = "FLOWN_ONLY_IN_A"
        elif pa["aircraft"] != pb["aircraft"]:
            kind = "DIFFERENT_AIRCRAFT"
        elif pa["start"] != pb["start"]:
            kind = "DIFFERENT_TIME"
        else:
            continue
        changes.append({"task": name, "priority": (ta or tb).priority, "change": kind, "a": pa, "b": pb})
    changes.sort(key=lambda c: (-PRIORITY_RANK.get(c["priority"], 0), c["task"]))

    return {
        "a": {"id": a.scenario.id, "name": a.scenario.name},
        "b": {"id": b.scenario.id, "name": b.scenario.name},
        "measures": measures,
        "changes": changes,
        "identical_tasks": len(set(a_tasks) & set(b_tasks)) - sum(c["change"] not in ("ONLY_IN_A", "ONLY_IN_B") for c in changes),
    }
