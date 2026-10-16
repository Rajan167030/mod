"""
"Exercise WINTER LIFT": a deliberately tight training scenario where aircraft are scarce,
mission windows overlap and every task flies from a weather site. Small disruptions
force real trade-offs, which is what Courses of Action and the replay are built to show.
All names and sites are fictional; weather at the site coordinates is live.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.all_models import (
    Assignment,
    Resource,
    ResourceAvailability,
    Scenario,
    ScheduleVersion,
    Task,
    TaskRequirement,
)
from app.models.weather_models import Location

CONTESTED_SCENARIO_NAME = "Exercise WINTER LIFT (TRAINING)"
HORIZON_HOURS = 24

SITES = {
    "ALPHA": ("Alpha FOB", 34.15, 77.58, "BASE", 3500),
    "BRAVO": ("Bravo Logistics Hub", 32.72, 74.85, "LOGISTICS_HUB", 1200),
    "CHARLIE": ("Charlie Ridge Post", 33.88, 75.32, "WEATHER_STATION", 4200),
    "DELTA": ("Delta Valley LZ", 34.52, 76.14, "WAYPOINT", 2800),
    "ECHO": ("Echo Pass LZ", 35.10, 76.90, "POI", 4800),
    "FOXTROT": ("Foxtrot Medevac Point", 33.25, 75.78, "BASE", 1800),
}

AIRCRAFT = [
    ("C-130-Alpha", "HEAVY_AIRCRAFT", 20000, ["HEAVY_AIRLIFT", "NIGHT_OPS"]),
    ("C-130-Bravo", "HEAVY_AIRCRAFT", 20000, ["HEAVY_AIRLIFT"]),
    ("IL-76-Heavy", "HEAVY_AIRCRAFT", 40000, ["SUPER_HEAVY_AIRLIFT", "HEAVY_AIRLIFT"]),
    ("Mi-17-Raptor-1", "TACTICAL_HELICOPTER", 4000, ["HIGH_ALTITUDE", "SEARCH_RESCUE", "MEDEVAC"]),
    ("Mi-17-Raptor-2", "TACTICAL_HELICOPTER", 4000, ["HIGH_ALTITUDE", "MEDEVAC"]),
    ("ALH-Dhruv-01", "LIGHT_HELICOPTER", 1500, ["FORWARD_RECON", "QUICK_MEDEVAC", "HIGH_ALTITUDE"]),
    ("ALH-Dhruv-02", "LIGHT_HELICOPTER", 1500, ["FORWARD_RECON", "QUICK_MEDEVAC"]),
]

# (name, minutes, window open h, window close h, priority, qualification, site)
TASKS = [
    ("WL-01 Medical stores to Alpha FOB", 150, 1, 6, "CRITICAL", "HEAVY_AIRLIFT", "ALPHA"),
    ("WL-02 Rations drop, Delta Valley", 180, 2, 9, "HIGH", "HEAVY_AIRLIFT", "DELTA"),
    ("WL-03 Engineer plant to Bravo Hub", 240, 3, 12, "HIGH", "SUPER_HEAVY_AIRLIFT", "BRAVO"),
    ("WL-04 Shelter packs to Foxtrot", 150, 5, 11, "HIGH", "HEAVY_AIRLIFT", "FOXTROT"),
    ("WL-05 Fuel bladder relay, Alpha", 120, 6, 14, "LOW", "HEAVY_AIRLIFT", "ALPHA"),
    ("WL-06 Generator drop, Charlie Ridge", 180, 8, 16, "MEDIUM", "HEAVY_AIRLIFT", "CHARLIE"),
    ("WL-07 Night resupply, Alpha FOB", 150, 14, 20, "HIGH", "NIGHT_OPS", "ALPHA"),
    ("WL-08 Spare engine to Bravo Hub", 180, 10, 20, "MEDIUM", "HEAVY_AIRLIFT", "BRAVO"),
    ("WL-09 Second-wave medical, Foxtrot", 120, 12, 17, "CRITICAL", "HEAVY_AIRLIFT", "FOXTROT"),
    ("WL-10 Routine cargo, Bravo Hub", 120, 9, 18, "LOW", "HEAVY_AIRLIFT", "BRAVO"),
    ("WL-11 Casualty evacuation, Echo Pass", 90, 1, 5, "CRITICAL", "MEDEVAC", "ECHO"),
    ("WL-12 Doctor insertion, Charlie Ridge", 60, 2, 5, "CRITICAL", "QUICK_MEDEVAC", "CHARLIE"),
    ("WL-13 Route recce, Echo Pass", 120, 3, 10, "MEDIUM", "HIGH_ALTITUDE", "ECHO"),
    ("WL-14 SAR sweep, Delta Valley", 120, 4, 10, "HIGH", "SEARCH_RESCUE", "DELTA"),
    ("WL-15 Controller transit, Delta LZ", 60, 6, 12, "MEDIUM", "FORWARD_RECON", "DELTA"),
    ("WL-16 Relay mast install, Echo Pass", 120, 9, 16, "MEDIUM", "HIGH_ALTITUDE", "ECHO"),
    ("WL-17 Ridge patrol, Charlie", 90, 10, 18, "LOW", "HIGH_ALTITUDE", "CHARLIE"),
    ("WL-18 Medevac shuttle, Foxtrot", 90, 12, 18, "HIGH", "MEDEVAC", "FOXTROT"),
    ("WL-19 Relay escort, Delta Valley", 90, 14, 22, "LOW", "FORWARD_RECON", "DELTA"),
    ("WL-20 Dusk recce, Alpha approaches", 90, 18, 23, "HIGH", "FORWARD_RECON", "ALPHA"),
    ("WL-21 Snow survey, Echo Pass", 120, 16, 23, "LOW", "HIGH_ALTITUDE", "ECHO"),
]

# Planned maintenance that already squeezes heavy-lift capacity
MAINTENANCE = [("C-130-Bravo", 9, 13)]


def seed_contested_scenario(db: Session, created_by: Optional[str], t0: Optional[datetime] = None) -> Scenario:
    """Create the scenario with a solver-built, approved baseline. Caller commits."""
    from app.engine.solver import solve_schedule_scenario  # heavy import, only when seeding

    t0 = t0 or datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    scenario = Scenario(
        id=str(uuid.uuid4()),
        name=CONTESTED_SCENARIO_NAME,
        description=(
            "24-hour winter airlift with seven aircraft across six mountain sites. Capacity is tight by design: "
            "a single grounding or weather hold forces trade-offs between speed, stability and critical coverage."
        ),
        status="ACTIVE",
        created_by=created_by,
        # Real creation time (not the floored t0) so it lists as the newest scenario
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(scenario)
    db.flush()

    sites = {}
    for key, (name, lat, lon, kind, elev) in SITES.items():
        loc = Location(
            id=str(uuid.uuid4()),
            scenario_id=scenario.id,
            name=name,
            latitude=lat,
            longitude=lon,
            location_type=kind,
            metadata_json={"elevation_m": elev, "description": "Fictional training site; live weather at these coordinates."},
        )
        db.add(loc)
        sites[key] = loc

    resources = {}
    for name, rtype, payload, quals in AIRCRAFT:
        r = Resource(
            id=str(uuid.uuid4()),
            scenario_id=scenario.id,
            name=name,
            resource_type=rtype,
            status="AVAILABLE",
            metadata_json={"max_payload_kg": payload, "qualifications": quals},
        )
        db.add(r)
        resources[name] = r
    db.flush()

    for r in resources.values():
        db.add(ResourceAvailability(resource_id=r.id, start_at=t0, end_at=t0 + timedelta(hours=HORIZON_HOURS + 12), available=True))
    for name, start_h, end_h in MAINTENANCE:
        db.add(ResourceAvailability(
            resource_id=resources[name].id,
            start_at=t0 + timedelta(hours=start_h),
            end_at=t0 + timedelta(hours=end_h),
            available=False,
        ))

    tasks = []
    for name, minutes, open_h, close_h, prio, qual, site in TASKS:
        t = Task(
            id=str(uuid.uuid4()),
            scenario_id=scenario.id,
            name=name,
            description=f"{name}. Requires {qual.replace('_', ' ').lower()}.",
            duration_minutes=minutes,
            earliest_start=t0 + timedelta(hours=open_h),
            latest_finish=t0 + timedelta(hours=close_h),
            priority=prio,
            status="SCHEDULED",
            location_id=sites[site].id,
        )
        db.add(t)
        db.flush()
        db.add(TaskRequirement(task_id=t.id, requirement_type="QUALIFICATION", requirement_value=qual))
        tasks.append(t)
    db.flush()
    for t in tasks:
        db.refresh(t)

    availabilities = db.query(ResourceAvailability).join(Resource).filter(Resource.scenario_id == scenario.id).all()
    result = solve_schedule_scenario(
        scenario=scenario,
        resources=list(resources.values()),
        availabilities=availabilities,
        tasks=tasks,
        time_limit_seconds=10,
    )
    baseline = ScheduleVersion(
        scenario_id=scenario.id,
        version_number=1,
        status="APPROVED",
        created_by=created_by,
    )
    db.add(baseline)
    db.flush()
    for a in result.assignments:
        db.add(Assignment(
            schedule_version_id=baseline.id,
            task_id=a["task_id"],
            resource_id=a["resource_id"],
            start_at=a["start_at"],
            end_at=a["end_at"],
        ))
    assigned = {a["task_id"] for a in result.assignments}
    for t in tasks:
        t.status = "SCHEDULED" if t.id in assigned else "PENDING"
    db.flush()
    return scenario
