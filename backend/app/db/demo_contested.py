"""
"Exercise WINTER LIFT": a deliberately tight training scenario where aircraft are scarce,
mission windows overlap and every task flies from a weather site. Small disruptions
force real trade-offs, which is what Courses of Action and the replay are built to show.
It is contested: a reported SAM site, a MANPADS threat and a live-firing range limit
where and when aircraft may go; crews need rest; flares and weapons are limited.
All names, sites and threats are fictional; weather at the site coordinates is live.
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
from app.models.ops_models import Crew, OpsZone, StoreItem
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
    ("ALH-Rudra-01", "ATTACK_HELICOPTER", 1000, ["ARMED_ESCORT", "HIGH_ALTITUDE"]),
]

# Self-protection and what each aircraft can carry. DASS = defensive aids suite.
AIRCRAFT_FIT = {
    "C-130-Alpha": (["DASS"], ["FLARE_SET"]),
    "C-130-Bravo": ([], ["FLARE_SET"]),
    "IL-76-Heavy": ([], ["FLARE_SET"]),
    "Mi-17-Raptor-1": (["DASS"], ["FLARE_SET"]),
    "Mi-17-Raptor-2": ([], ["FLARE_SET"]),
    "ALH-Dhruv-01": ([], ["FLARE_SET"]),
    "ALH-Dhruv-02": ([], ["FLARE_SET"]),
    "ALH-Rudra-01": (["DASS"], ["FLARE_SET", "ROCKET_POD", "ATGM"]),
}

# (name, aircraft types, max duty min, min rest min, duty already flown min, shift (start h, end h) or None)
CREWS = [
    ("Hercules crew 1", ["HEAVY_AIRCRAFT"], 480, 60, 0, None),
    ("Hercules crew 2", ["HEAVY_AIRCRAFT"], 480, 60, 120, None),
    ("Gajraj crew", ["HEAVY_AIRCRAFT"], 480, 60, 0, None),
    ("Night heavy crew", ["HEAVY_AIRCRAFT"], 480, 60, 0, (12, 26)),
    ("Mi-17 crew 1", ["TACTICAL_HELICOPTER"], 420, 45, 0, None),
    ("Mi-17 crew 2", ["TACTICAL_HELICOPTER"], 420, 45, 240, None),
    ("ALH crew 1", ["LIGHT_HELICOPTER", "ATTACK_HELICOPTER"], 420, 45, 0, None),
    ("ALH crew 2", ["LIGHT_HELICOPTER"], 420, 45, 0, None),
    ("Rudra crew", ["ATTACK_HELICOPTER"], 360, 45, 0, None),
]

# (store type, name, category, quantity, unit)
STORES = [
    ("FLARE_SET", "Flare/chaff dispenser load", "COUNTERMEASURE", 6, "sets"),
    ("ROCKET_POD", "70 mm rocket pod", "WEAPON", 4, "pods"),
    ("ATGM", "Anti-tank guided missile", "WEAPON", 2, "missiles"),
]

# Sorties into Echo Pass carry flares; escorts carry weapons. Keyed by task code.
TASK_STORES = {
    "WL-11": ["FLARE_SET"], "WL-13": ["FLARE_SET"], "WL-16": ["FLARE_SET"], "WL-21": ["FLARE_SET"],
    "WL-30": ["ROCKET_POD:2", "FLARE_SET"], "WL-31": ["ATGM:2", "FLARE_SET"],
}

# Threats and airspace. Times are hours from the scenario start; None = always.
ZONES = [
    dict(name="Reported SAM site, Echo north", category="THREAT", kind="SAM", effect="BLOCK",
         center=(35.16, 76.93), radius_km=28, hours=(6, 14), exempt="DASS", source="ELINT", confidence=0.7,
         notes="Mobile SAM reported by ELINT. Only aircraft with a defensive aids suite may operate at Echo Pass while active."),
    dict(name="MANPADS threat, Charlie Ridge", category="THREAT", kind="MANPADS", effect="AVOID",
         center=(33.90, 75.30), radius_km=12, hours=None, exempt=None, source="HUMINT", confidence=0.5,
         notes="Shoulder-launched missile teams reported on the ridge. Avoid where possible."),
    dict(name="R-114 live firing range", category="AIRSPACE", kind="RESTRICTED", effect="BLOCK",
         polygon=[[34.62, 76.02], [34.62, 76.28], [34.42, 76.28], [34.42, 76.02]], hours=(15, 20), exempt=None,
         source="NOTAM", confidence=1.0, notes="Artillery live firing. No flying in the box while active."),
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
    ("WL-30 Armed escort, Echo Pass convoy", 90, 7, 13, "HIGH", "ARMED_ESCORT", "ECHO"),
    ("WL-31 Overwatch, Delta Valley LZ", 120, 3, 9, "MEDIUM", "ARMED_ESCORT", "DELTA"),
]

# Planned maintenance that already squeezes heavy-lift capacity
MAINTENANCE = [("C-130-Bravo", 9, 13)]


def add_operational_layers(db: Session, scenario_id: str, t0: datetime) -> None:
    """Crews, stores, threats and airspace for the scenario, plus aircraft fit and store needs. Caller commits."""
    for name, (caps, store_types) in AIRCRAFT_FIT.items():
        r = db.query(Resource).filter(Resource.scenario_id == scenario_id, Resource.name == name).first()
        if r:
            meta = dict(r.metadata_json or {})
            meta["qualifications"] = sorted(set(meta.get("qualifications", [])) | set(caps))
            meta["store_types"] = store_types
            r.metadata_json = meta
    for name, types, duty, rest, used, shift in CREWS:
        db.add(Crew(
            scenario_id=scenario_id, name=name, aircraft_types=types, status="AVAILABLE",
            max_duty_minutes=duty, min_rest_minutes=rest, duty_used_minutes=used,
            duty_start=t0 + timedelta(hours=shift[0]) if shift else None,
            duty_end=t0 + timedelta(hours=shift[1]) if shift else None,
        ))
    for kind, name, category, qty, unit in STORES:
        db.add(StoreItem(scenario_id=scenario_id, store_type=kind, name=name, category=category, quantity=qty, unit=unit))
    for z in ZONES:
        center = z.get("center")
        db.add(OpsZone(
            scenario_id=scenario_id, name=z["name"], category=z["category"], kind=z["kind"], effect=z["effect"],
            center_lat=center[0] if center else None, center_lon=center[1] if center else None,
            radius_km=z.get("radius_km"), polygon_json=z.get("polygon"),
            active_from=t0 + timedelta(hours=z["hours"][0]) if z["hours"] else None,
            active_until=t0 + timedelta(hours=z["hours"][1]) if z["hours"] else None,
            exempt_capability=z["exempt"], source=z["source"], confidence=z["confidence"], notes=z["notes"],
        ))
    for t in db.query(Task).filter(Task.scenario_id == scenario_id):
        code = t.name.split(" ", 1)[0]
        have = {r.requirement_value for r in t.requirements if r.requirement_type == "STORE"}
        for need in TASK_STORES.get(code, []):
            if need not in have:
                db.add(TaskRequirement(task_id=t.id, requirement_type="STORE", requirement_value=need))
    db.flush()


def _backfill_crews(db: Session, scenario_id: str) -> None:
    """Give sorties in existing plans a crew, greedily, respecting type, rest, duty and shift."""
    from app.services.ops_constraints import crew_can_fly

    crews = db.query(Crew).filter(Crew.scenario_id == scenario_id, Crew.status == "AVAILABLE").all()
    resources = {r.id: r for r in db.query(Resource).filter(Resource.scenario_id == scenario_id)}

    def utc(dt):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    versions = db.query(ScheduleVersion).filter(
        ScheduleVersion.scenario_id == scenario_id, ScheduleVersion.status.in_(["APPROVED", "PROPOSED"])
    )
    for v in versions:
        flown = {c.id: c.duty_used_minutes for c in crews}
        free_at = {}
        for a in db.query(Assignment).filter(Assignment.schedule_version_id == v.id).order_by(Assignment.start_at):
            r = resources.get(a.resource_id)
            start, end = utc(a.start_at), utc(a.end_at)
            minutes = int((end - start).total_seconds() // 60)
            fits = [
                c for c in crews
                if r and crew_can_fly(c, r.resource_type)
                and (c.id not in free_at or start >= free_at[c.id])
                and flown[c.id] + minutes <= c.max_duty_minutes
                and (c.duty_start is None or start >= utc(c.duty_start))
                and (c.duty_end is None or end <= utc(c.duty_end))
            ]
            if not fits:
                continue
            c = min(fits, key=lambda c: flown[c.id])
            a.crew_id = c.id
            flown[c.id] += minutes
            free_at[c.id] = end + timedelta(minutes=c.min_rest_minutes)
    db.flush()


def upgrade_contested_layers(db: Session, scenario: Scenario) -> bool:
    """
    Bring a Winter Lift scenario seeded before crews, stores and zones existed up to date,
    without removing anything: add the escort aircraft and tasks, the layers, a crew for any
    aircraft type no demo crew flies, then crew the existing plans. Returns True if it changed.
    """
    from app.services.scenario_admin import scenario_start

    if db.query(Crew).filter(Crew.scenario_id == scenario.id).first() or db.query(OpsZone).filter(OpsZone.scenario_id == scenario.id).first():
        return False
    t0 = scenario_start(db, scenario.id) or datetime.now(timezone.utc)
    sites = {loc.name: loc for loc in db.query(Location).filter(Location.scenario_id == scenario.id)}
    names = {r.name for r in db.query(Resource).filter(Resource.scenario_id == scenario.id)}
    for name, rtype, payload, quals in AIRCRAFT:
        if name not in names:
            r = Resource(scenario_id=scenario.id, name=name, resource_type=rtype, status="AVAILABLE",
                         metadata_json={"max_payload_kg": payload, "qualifications": quals})
            db.add(r)
            db.flush()
            db.add(ResourceAvailability(resource_id=r.id, start_at=t0, end_at=t0 + timedelta(hours=HORIZON_HOURS + 12), available=True))
    codes = {t.name.split(" ", 1)[0] for t in db.query(Task).filter(Task.scenario_id == scenario.id)}
    for name, minutes, open_h, close_h, prio, qual, site in TASKS:
        if name.split(" ", 1)[0] in codes:
            continue
        loc = sites.get(SITES[site][0])
        t = Task(scenario_id=scenario.id, name=name, description=f"{name}. Requires {qual.replace('_', ' ').lower()}.",
                 duration_minutes=minutes, earliest_start=t0 + timedelta(hours=open_h), latest_finish=t0 + timedelta(hours=close_h),
                 priority=prio, status="PENDING", location_id=loc.id if loc else None)
        db.add(t)
        db.flush()
        db.add(TaskRequirement(task_id=t.id, requirement_type="QUALIFICATION", requirement_value=qual))
    db.flush()
    add_operational_layers(db, scenario.id, t0)

    covered = {kind for _, types, *_ in CREWS for kind in types}
    for rtype in sorted({r.resource_type for r in db.query(Resource).filter(Resource.scenario_id == scenario.id)} - covered):
        db.add(Crew(scenario_id=scenario.id, name=f"{rtype.replace('_', ' ').title()} crew", aircraft_types=[rtype],
                    status="AVAILABLE", max_duty_minutes=480, min_rest_minutes=45, duty_used_minutes=0))
    db.flush()
    _backfill_crews(db, scenario.id)
    return True


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
    add_operational_layers(db, scenario.id, t0)
    for t in tasks:
        db.refresh(t)

    from app.services.ops_constraints import solver_ops_kwargs

    availabilities = db.query(ResourceAvailability).join(Resource).filter(Resource.scenario_id == scenario.id).all()
    result = solve_schedule_scenario(
        scenario=scenario,
        resources=list(resources.values()),
        availabilities=availabilities,
        tasks=tasks,
        time_limit_seconds=10,
        **solver_ops_kwargs(db, scenario.id, tasks, list(resources.values()))[0],
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
            crew_id=a.get("crew_id"),
            start_at=a["start_at"],
            end_at=a["end_at"],
        ))
    assigned = {a["task_id"] for a in result.assignments}
    for t in tasks:
        t.status = "SCHEDULED" if t.id in assigned else "PENDING"
    db.flush()
    return scenario
