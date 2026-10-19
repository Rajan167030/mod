"""
Whole-scenario operations: delete, clone and rebase (shift every time to a new start).
SQLite does not enforce ON DELETE CASCADE unless foreign keys are switched on, so
children are deleted explicitly in dependency order.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.models.all_models import (
    Approval,
    Assignment,
    Disruption,
    OptimisationRun,
    Resource,
    ResourceAvailability,
    Scenario,
    ScheduleVersion,
    Task,
    TaskRequirement,
)
from app.models.alert_models import AlertRule
from app.models.ops_models import Crew, OpsZone, StoreItem
from app.models.replay_models import ReplaySession, WeatherInject
from app.models.weather_models import Location, WeatherRecord


def delete_scenario(db: Session, scenario_id: str) -> None:
    """Remove a scenario and everything that belongs to it. Audit events are kept. Caller commits."""
    version_ids = [v for (v,) in db.query(ScheduleVersion.id).filter(ScheduleVersion.scenario_id == scenario_id)]
    task_ids = [t for (t,) in db.query(Task.id).filter(Task.scenario_id == scenario_id)]
    resource_ids = [r for (r,) in db.query(Resource.id).filter(Resource.scenario_id == scenario_id)]
    location_ids = [loc for (loc,) in db.query(Location.id).filter(Location.scenario_id == scenario_id)]
    run_ids = [r for (r,) in db.query(OptimisationRun.id).filter(OptimisationRun.schedule_version_id.in_(version_ids))]

    db.query(Approval).filter(Approval.optimisation_run_id.in_(run_ids)).delete(synchronize_session=False)
    db.query(OptimisationRun).filter(OptimisationRun.id.in_(run_ids)).delete(synchronize_session=False)
    db.query(Assignment).filter(Assignment.schedule_version_id.in_(version_ids)).delete(synchronize_session=False)
    db.query(ScheduleVersion).filter(ScheduleVersion.id.in_(version_ids)).delete(synchronize_session=False)
    for layer in (Crew, StoreItem, OpsZone):
        db.query(layer).filter(layer.scenario_id == scenario_id).delete(synchronize_session=False)
    db.query(TaskRequirement).filter(TaskRequirement.task_id.in_(task_ids)).delete(synchronize_session=False)
    db.query(Task).filter(Task.id.in_(task_ids)).delete(synchronize_session=False)
    db.query(ResourceAvailability).filter(ResourceAvailability.resource_id.in_(resource_ids)).delete(synchronize_session=False)
    db.query(Resource).filter(Resource.id.in_(resource_ids)).delete(synchronize_session=False)
    db.query(ReplaySession).filter(ReplaySession.scenario_id == scenario_id).delete(synchronize_session=False)
    db.query(AlertRule).filter(AlertRule.scenario_id == scenario_id).delete(synchronize_session=False)
    # Branches of this scenario stay, detached from it
    db.query(Scenario).filter(Scenario.parent_scenario_id == scenario_id).update({"parent_scenario_id": None}, synchronize_session=False)
    db.query(WeatherInject).filter(WeatherInject.scenario_id == scenario_id).delete(synchronize_session=False)
    db.query(WeatherRecord).filter(WeatherRecord.location_id.in_(location_ids)).delete(synchronize_session=False)
    db.query(Location).filter(Location.id.in_(location_ids)).delete(synchronize_session=False)
    db.query(Disruption).filter(Disruption.scenario_id == scenario_id).delete(synchronize_session=False)
    db.query(Scenario).filter(Scenario.id == scenario_id).delete(synchronize_session=False)
    db.flush()


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def scenario_start(db: Session, scenario_id: str) -> Optional[datetime]:
    """The scenario's clock zero: its earliest availability window, else its earliest task window."""
    starts = [
        _utc(a.start_at)
        for a in db.query(ResourceAvailability).join(Resource).filter(Resource.scenario_id == scenario_id)
    ] or [_utc(t.earliest_start) for t in db.query(Task).filter(Task.scenario_id == scenario_id)]
    return min(starts) if starts else None


def clone_scenario(
    db: Session,
    source_id: str,
    name: str,
    description: Optional[str],
    created_by: Optional[str],
    new_t0: Optional[datetime] = None,
) -> Scenario:
    """
    Deep-copy a scenario (sites, resources, availability, tasks and its approved schedule).
    With new_t0, every time is shifted so the source's earliest task window opens at new_t0.
    Caller commits.
    """
    src = db.query(Scenario).filter(Scenario.id == source_id).first()
    tasks = db.query(Task).filter(Task.scenario_id == source_id).all()
    shift = timedelta(0)
    if new_t0:
        anchor = scenario_start(db, source_id)
        if anchor:
            shift = _utc(new_t0) - anchor

    def mv(dt: datetime) -> datetime:
        return _utc(dt) + shift

    now = datetime.now(timezone.utc)
    dst = Scenario(
        id=str(uuid.uuid4()), name=name, description=description or src.description,
        status="ACTIVE", created_by=created_by, created_at=now, updated_at=now,
    )
    db.add(dst)
    db.flush()

    loc_map: Dict[str, str] = {}
    for loc in db.query(Location).filter(Location.scenario_id == source_id):
        new = Location(
            id=str(uuid.uuid4()), scenario_id=dst.id, name=loc.name, latitude=loc.latitude,
            longitude=loc.longitude, location_type=loc.location_type, metadata_json=loc.metadata_json,
        )
        db.add(new)
        loc_map[loc.id] = new.id

    res_map: Dict[str, str] = {}
    for r in db.query(Resource).filter(Resource.scenario_id == source_id):
        new = Resource(
            id=str(uuid.uuid4()), scenario_id=dst.id, name=r.name, resource_type=r.resource_type,
            status=r.status, metadata_json=r.metadata_json,
        )
        db.add(new)
        res_map[r.id] = new.id
    db.flush()

    crew_map: Dict[str, str] = {}
    for c in db.query(Crew).filter(Crew.scenario_id == source_id):
        new = Crew(
            id=str(uuid.uuid4()), scenario_id=dst.id, name=c.name, aircraft_types=list(c.aircraft_types or []),
            status=c.status, max_duty_minutes=c.max_duty_minutes, min_rest_minutes=c.min_rest_minutes,
            duty_used_minutes=c.duty_used_minutes, notes=c.notes,
            duty_start=mv(c.duty_start) if c.duty_start else None,
            duty_end=mv(c.duty_end) if c.duty_end else None,
        )
        db.add(new)
        crew_map[c.id] = new.id
    for st in db.query(StoreItem).filter(StoreItem.scenario_id == source_id):
        db.add(StoreItem(
            scenario_id=dst.id, store_type=st.store_type, name=st.name, category=st.category,
            quantity=st.quantity, unit=st.unit,
        ))
    for z in db.query(OpsZone).filter(OpsZone.scenario_id == source_id):
        db.add(OpsZone(
            scenario_id=dst.id, name=z.name, category=z.category, kind=z.kind, effect=z.effect,
            center_lat=z.center_lat, center_lon=z.center_lon, radius_km=z.radius_km, polygon_json=z.polygon_json,
            active_from=mv(z.active_from) if z.active_from else None,
            active_until=mv(z.active_until) if z.active_until else None,
            exempt_capability=z.exempt_capability, source=z.source, confidence=z.confidence, notes=z.notes,
        ))
    db.flush()

    for a in db.query(ResourceAvailability).filter(ResourceAvailability.resource_id.in_(list(res_map))):
        db.add(ResourceAvailability(
            resource_id=res_map[a.resource_id], start_at=mv(a.start_at), end_at=mv(a.end_at), available=a.available,
        ))

    task_map: Dict[str, str] = {}
    for t in tasks:
        new = Task(
            id=str(uuid.uuid4()), scenario_id=dst.id, name=t.name, description=t.description,
            duration_minutes=t.duration_minutes, earliest_start=mv(t.earliest_start),
            latest_finish=mv(t.latest_finish), priority=t.priority, status=t.status,
            location_id=loc_map.get(t.location_id) if t.location_id else None,
        )
        db.add(new)
        task_map[t.id] = new.id
        for req in t.requirements:
            db.add(TaskRequirement(task_id=new.id, requirement_type=req.requirement_type, requirement_value=req.requirement_value))
    db.flush()

    source_version = (
        db.query(ScheduleVersion)
        .filter(ScheduleVersion.scenario_id == source_id, ScheduleVersion.status == "APPROVED")
        .order_by(ScheduleVersion.version_number.desc())
        .first()
    )
    if source_version:
        version = ScheduleVersion(scenario_id=dst.id, version_number=1, status="APPROVED", created_by=created_by)
        db.add(version)
        db.flush()
        for a in db.query(Assignment).filter(Assignment.schedule_version_id == source_version.id):
            if a.task_id in task_map and a.resource_id in res_map:
                db.add(Assignment(
                    schedule_version_id=version.id, task_id=task_map[a.task_id], resource_id=res_map[a.resource_id],
                    crew_id=crew_map.get(a.crew_id) if a.crew_id else None,
                    start_at=mv(a.start_at), end_at=mv(a.end_at),
                ))
    db.flush()
    return dst
