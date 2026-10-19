"""Threats and airspace, crews, stores and predicted sortie risk."""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.errors import NotFoundError
from app.core.permissions import UserRole
from app.db.session import get_db
from app.models.all_models import Assignment, Resource, Scenario, ScheduleVersion, Task, User
from app.models.ops_models import Crew, OpsZone, StoreItem
from app.models.weather_models import Location
from app.schemas.ops_schemas import (
    CrewCreate, CrewResponse, CrewUpdate, StoreCreate, StoreResponse, StoreUpdate, ZoneCreate, ZoneResponse,
)
from app.services.audit_service import log_audit_event
from app.services.ops_constraints import affected_task_ids, carries, is_active, store_demand
from app.services.risk_service import assess_plan

router = APIRouter(tags=["Operational layers"])
editors = require_roles(UserRole.PLANNER, UserRole.ADMIN)


def _scenario(db: Session, scenario_id: str) -> Scenario:
    sc = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not sc:
        raise NotFoundError("Scenario", scenario_id)
    return sc


def _active_plan(db: Session, scenario_id: str) -> List[Assignment]:
    version = (
        db.query(ScheduleVersion)
        .filter(ScheduleVersion.scenario_id == scenario_id, ScheduleVersion.status == "APPROVED")
        .order_by(ScheduleVersion.version_number.desc())
        .first()
    )
    return db.query(Assignment).filter(Assignment.schedule_version_id == version.id).all() if version else []


def _utc(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

def _zone_out(z: OpsZone, tasks: List[Task], sites: dict) -> ZoneResponse:
    by_id = {t.id: t for t in tasks}
    now = datetime.now(timezone.utc)
    return ZoneResponse(
        id=z.id, scenario_id=z.scenario_id, name=z.name, category=z.category, kind=z.kind, effect=z.effect,
        center_lat=z.center_lat, center_lon=z.center_lon, radius_km=z.radius_km, polygon=z.polygon_json,
        active_from=z.active_from, active_until=z.active_until, exempt_capability=z.exempt_capability,
        source=z.source, confidence=z.confidence, notes=z.notes, created_at=z.created_at,
        affected_tasks=[{"id": i, "name": by_id[i].name, "priority": by_id[i].priority} for i in affected_task_ids(z, tasks, sites)],
        active_now=is_active(z, now, now + timedelta(seconds=1)),
    )


@router.get("/zones/{scenario_id}", response_model=List[ZoneResponse])
def list_zones(scenario_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _scenario(db, scenario_id)
    tasks = db.query(Task).filter(Task.scenario_id == scenario_id).all()
    sites = {loc.id: loc for loc in db.query(Location).filter(Location.scenario_id == scenario_id)}
    zones = db.query(OpsZone).filter(OpsZone.scenario_id == scenario_id).order_by(OpsZone.category.desc(), OpsZone.name)
    return [_zone_out(z, tasks, sites) for z in zones]


@router.post("/zones/{scenario_id}", response_model=ZoneResponse, status_code=status.HTTP_201_CREATED)
def create_zone(scenario_id: str, payload: ZoneCreate, db: Session = Depends(get_db), user: User = Depends(editors)):
    _scenario(db, scenario_id)
    data = payload.model_dump()
    z = OpsZone(scenario_id=scenario_id, polygon_json=data.pop("polygon"), **data)
    if z.polygon_json:
        z.center_lat = z.center_lon = z.radius_km = None
    db.add(z)
    db.flush()
    log_audit_event(db, action="ZONE_CREATED", entity_type="ZONE", entity_id=z.id, actor=user,
                    metadata={"name": z.name, "kind": z.kind, "effect": z.effect})
    db.commit()
    db.refresh(z)
    tasks = db.query(Task).filter(Task.scenario_id == scenario_id).all()
    sites = {loc.id: loc for loc in db.query(Location).filter(Location.scenario_id == scenario_id)}
    return _zone_out(z, tasks, sites)


@router.delete("/zones/zone/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_zone(zone_id: str, db: Session = Depends(get_db), user: User = Depends(editors)):
    z = db.query(OpsZone).filter(OpsZone.id == zone_id).first()
    if not z:
        raise NotFoundError("Zone", zone_id)
    log_audit_event(db, action="ZONE_DELETED", entity_type="ZONE", entity_id=z.id, actor=user, metadata={"name": z.name})
    db.delete(z)
    db.commit()


# ---------------------------------------------------------------------------
# Crews
# ---------------------------------------------------------------------------

def _crew_rows(db: Session, scenario_id: str) -> List[CrewResponse]:
    plan = _active_plan(db, scenario_id)
    now = datetime.now(timezone.utc)
    out = []
    for c in db.query(Crew).filter(Crew.scenario_id == scenario_id).order_by(Crew.name):
        mine = [a for a in plan if a.crew_id == c.id]
        minutes = sum(int((_utc(a.end_at) - _utc(a.start_at)).total_seconds() // 60) for a in mine)
        upcoming = sorted(_utc(a.start_at) for a in mine if _utc(a.start_at) >= now)
        out.append(CrewResponse(
            id=c.id, scenario_id=c.scenario_id, name=c.name, aircraft_types=list(c.aircraft_types or []),
            status=c.status, max_duty_minutes=c.max_duty_minutes, min_rest_minutes=c.min_rest_minutes,
            duty_used_minutes=c.duty_used_minutes, duty_start=c.duty_start, duty_end=c.duty_end, notes=c.notes,
            planned_sorties=len(mine), planned_minutes=minutes,
            duty_ratio=round((c.duty_used_minutes + minutes) / max(1, c.max_duty_minutes), 2),
            next_sortie_at=upcoming[0] if upcoming else None,
        ))
    return out


@router.get("/crews/{scenario_id}", response_model=List[CrewResponse])
def list_crews(scenario_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _scenario(db, scenario_id)
    return _crew_rows(db, scenario_id)


@router.post("/crews/{scenario_id}", response_model=CrewResponse, status_code=status.HTTP_201_CREATED)
def create_crew(scenario_id: str, payload: CrewCreate, db: Session = Depends(get_db), user: User = Depends(editors)):
    _scenario(db, scenario_id)
    c = Crew(scenario_id=scenario_id, **payload.model_dump())
    db.add(c)
    db.flush()
    log_audit_event(db, action="CREW_CREATED", entity_type="CREW", entity_id=c.id, actor=user, metadata={"name": c.name})
    db.commit()
    return next(r for r in _crew_rows(db, scenario_id) if r.id == c.id)


@router.patch("/crews/crew/{crew_id}", response_model=CrewResponse)
def update_crew(crew_id: str, payload: CrewUpdate, db: Session = Depends(get_db), user: User = Depends(editors)):
    c = db.query(Crew).filter(Crew.id == crew_id).first()
    if not c:
        raise NotFoundError("Crew", crew_id)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    for k, v in changes.items():
        setattr(c, k, v)
    log_audit_event(db, action="CREW_UPDATED", entity_type="CREW", entity_id=c.id, actor=user, metadata=changes)
    db.commit()
    return next(r for r in _crew_rows(db, c.scenario_id) if r.id == c.id)


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------

def _store_rows(db: Session, scenario_id: str) -> List[StoreResponse]:
    tasks = {t.id: t for t in db.query(Task).filter(Task.scenario_id == scenario_id)}
    resources = db.query(Resource).filter(Resource.scenario_id == scenario_id).all()
    planned = {}
    for a in _active_plan(db, scenario_id):
        for kind, qty in (store_demand(tasks[a.task_id]) if a.task_id in tasks else {}).items():
            planned[kind] = planned.get(kind, 0) + qty
    demand = {}
    for t in tasks.values():
        for kind, qty in store_demand(t).items():
            demand[kind] = demand.get(kind, 0) + qty
    return [
        StoreResponse(
            id=s.id, scenario_id=s.scenario_id, store_type=s.store_type, name=s.name, category=s.category,
            quantity=s.quantity, unit=s.unit, planned_use=planned.get(s.store_type, 0), demand=demand.get(s.store_type, 0),
            carriers=[r.name for r in resources if carries(r, s.store_type)],
        )
        for s in db.query(StoreItem).filter(StoreItem.scenario_id == scenario_id).order_by(StoreItem.category, StoreItem.name)
    ]


@router.get("/stores/{scenario_id}", response_model=List[StoreResponse])
def list_stores(scenario_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _scenario(db, scenario_id)
    return _store_rows(db, scenario_id)


@router.post("/stores/{scenario_id}", response_model=StoreResponse, status_code=status.HTTP_201_CREATED)
def create_store(scenario_id: str, payload: StoreCreate, db: Session = Depends(get_db), user: User = Depends(editors)):
    _scenario(db, scenario_id)
    s = StoreItem(scenario_id=scenario_id, **payload.model_dump())
    db.add(s)
    db.flush()
    log_audit_event(db, action="STORE_CREATED", entity_type="STORE", entity_id=s.id, actor=user,
                    metadata={"store_type": s.store_type, "quantity": s.quantity})
    db.commit()
    return next(r for r in _store_rows(db, scenario_id) if r.id == s.id)


@router.patch("/stores/item/{store_id}", response_model=StoreResponse)
def update_store(store_id: str, payload: StoreUpdate, db: Session = Depends(get_db), user: User = Depends(editors)):
    s = db.query(StoreItem).filter(StoreItem.id == store_id).first()
    if not s:
        raise NotFoundError("Store", store_id)
    before = s.quantity
    s.quantity = payload.quantity
    log_audit_event(db, action="STORE_UPDATED", entity_type="STORE", entity_id=s.id, actor=user,
                    metadata={"store_type": s.store_type, "from": before, "to": s.quantity})
    db.commit()
    return next(r for r in _store_rows(db, s.scenario_id) if r.id == s.id)


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------

@router.get("/risk/schedules/{schedule_id}")
def schedule_risk(schedule_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    version = db.query(ScheduleVersion).filter(ScheduleVersion.id == schedule_id).first()
    if not version:
        raise NotFoundError("ScheduleVersion", schedule_id)
    report = assess_plan(db, version.scenario_id, db.query(Assignment).filter(Assignment.schedule_version_id == schedule_id).all())
    return {"schedule_id": schedule_id, "version_number": version.version_number, "status": version.status, **report}
