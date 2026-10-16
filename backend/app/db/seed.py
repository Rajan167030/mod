import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.core.security import get_password_hash
from app.core.permissions import UserRole
from app.models.all_models import (
    User, Scenario, Resource, ResourceAvailability, Task, TaskRequirement,
    ScheduleVersion, Assignment, AuditEvent
)
from app.models.weather_models import Location
from app.core.config import settings
from app.db.demo_contested import CONTESTED_SCENARIO_NAME, seed_contested_scenario


# -------------------------------------------------------
# Synthetic locations (fictional sites; coordinates are used
# to fetch live public weather for the surrounding area)
# -------------------------------------------------------
DEMO_LOCATIONS = [
    {
        "name": "Alpha Forward Base (FICTIONAL)",
        "latitude": 34.15,
        "longitude": 77.58,
        "location_type": "BASE",
        "metadata_json": {"description": "Primary forward staging area — synthetic data only", "elevation_m": 3500},
    },
    {
        "name": "Bravo Logistics Hub (FICTIONAL)",
        "latitude": 32.72,
        "longitude": 74.85,
        "location_type": "LOGISTICS_HUB",
        "metadata_json": {"description": "Central logistics and supply distribution hub — synthetic data only", "elevation_m": 1200},
    },
    {
        "name": "Charlie Weather Station (FICTIONAL)",
        "latitude": 33.88,
        "longitude": 75.32,
        "location_type": "WEATHER_STATION",
        "metadata_json": {"description": "High-altitude weather monitoring post — synthetic data only", "elevation_m": 4200},
    },
    {
        "name": "Delta Valley Waypoint (FICTIONAL)",
        "latitude": 34.52,
        "longitude": 76.14,
        "location_type": "WAYPOINT",
        "metadata_json": {"description": "Transit waypoint through valley corridor — synthetic data only", "elevation_m": 2800},
    },
    {
        "name": "Echo Mountain Pass POI (FICTIONAL)",
        "latitude": 35.10,
        "longitude": 76.90,
        "location_type": "POI",
        "metadata_json": {"description": "Strategic observation point at high pass — synthetic data only", "elevation_m": 4800},
    },
    {
        "name": "Foxtrot Medevac Rally Point (FICTIONAL)",
        "latitude": 33.25,
        "longitude": 75.78,
        "location_type": "BASE",
        "metadata_json": {"description": "Emergency medical evacuation rally point — synthetic data only", "elevation_m": 1800},
    },
]


def seed_locations(db: Session, scenario_id: str) -> int:
    """Add the demo locations to a scenario that has none. Returns the number added."""
    if db.query(Location).filter_by(scenario_id=scenario_id).first():
        return 0
    for loc_data in DEMO_LOCATIONS:
        db.add(Location(id=str(uuid.uuid4()), scenario_id=scenario_id, **loc_data))
    return len(DEMO_LOCATIONS)


def _ensure_contested(db: Session) -> None:
    if not settings.SEED_CONTESTED_DEMO:
        return
    if db.query(Scenario).filter_by(name=CONTESTED_SCENARIO_NAME).first():
        return
    planner = db.query(User).filter_by(email="planner@airops.demo").first()
    seed_contested_scenario(db, planner.id if planner else None)
    db.commit()
    print(f"Seeded contested demo scenario: {CONTESTED_SCENARIO_NAME}")


def seed_database(db: Session | None = None) -> None:
    """Seed the database with deterministic demo data."""
    should_close = False
    if db is None:
        from app.db.migrate import upgrade_to_head
        upgrade_to_head()
        db = SessionLocal()
        should_close = True

    try:
        # Check if users already exist
        existing_user = db.query(User).filter_by(email="admin@airops.demo").first()
        if existing_user:
            # Databases seeded before locations existed: backfill them
            added = sum(seed_locations(db, sid) for (sid,) in db.query(Scenario.id).all())
            if added:
                db.commit()
                print(f"Backfilled {added} demo locations.")
            _ensure_contested(db)
            print("Database already seeded. Skipping seed execution.")
            return

        print("Seeding demo users...")
        users = {
            "admin": User(
                id=str(uuid.uuid4()),
                email="admin@airops.demo",
                password_hash=get_password_hash("AdminPass123!"),
                role=UserRole.ADMIN.value,
                is_active=True
            ),
            "planner": User(
                id=str(uuid.uuid4()),
                email="planner@airops.demo",
                password_hash=get_password_hash("PlannerPass123!"),
                role=UserRole.PLANNER.value,
                is_active=True
            ),
            "reviewer": User(
                id=str(uuid.uuid4()),
                email="reviewer@airops.demo",
                password_hash=get_password_hash("ReviewerPass123!"),
                role=UserRole.REVIEWER.value,
                is_active=True
            ),
            "viewer": User(
                id=str(uuid.uuid4()),
                email="viewer@airops.demo",
                password_hash=get_password_hash("ViewerPass123!"),
                role=UserRole.VIEWER.value,
                is_active=True
            )
        }
        for u in users.values():
            db.add(u)
        db.flush()

        # Audit initial system bootstrap
        db.add(AuditEvent(
            actor_id=users["admin"].id,
            action="SYSTEM_BOOTSTRAP",
            entity_type="SYSTEM",
            entity_id=None,
            metadata_json={"description": "System database initialized and seeded with default demo roles."}
        ))

        print("Seeding baseline scenario...")
        now_base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        scenario = Scenario(
            id=str(uuid.uuid4()),
            name="Northern Corridor Relief & Air Supply Op (SYNTHETIC)",
            description="Synthetic high-tempo humanitarian logistics operation across forward mountain bases and logistic hubs.",
            status="ACTIVE",
            created_by=users["planner"].id,
            created_at=now_base,
            updated_at=now_base
        )
        db.add(scenario)
        db.flush()

        # Resources
        print("Seeding resources...")
        resource_data = [
            ("C-130-Alpha", "HEAVY_AIRCRAFT", {"max_payload_kg": 20000, "qualifications": ["HEAVY_AIRLIFT", "NIGHT_OPS"]}),
            ("C-130-Bravo", "HEAVY_AIRCRAFT", {"max_payload_kg": 20000, "qualifications": ["HEAVY_AIRLIFT"]}),
            ("IL-76-Heavy", "HEAVY_AIRCRAFT", {"max_payload_kg": 40000, "qualifications": ["SUPER_HEAVY_AIRLIFT"]}),
            ("Mi-17-Raptor-1", "TACTICAL_HELICOPTER", {"max_payload_kg": 4000, "qualifications": ["HIGH_ALTITUDE", "SEARCH_RESCUE"]}),
            ("Mi-17-Raptor-2", "TACTICAL_HELICOPTER", {"max_payload_kg": 4000, "qualifications": ["HIGH_ALTITUDE", "MEDEVAC"]}),
            ("ALH-Dhruv-01", "LIGHT_HELICOPTER", {"max_payload_kg": 1500, "qualifications": ["FORWARD_RECON", "QUICK_MEDEVAC"]}),
            ("ALH-Dhruv-02", "LIGHT_HELICOPTER", {"max_payload_kg": 1500, "qualifications": ["FORWARD_RECON"]}),
            ("Crew-Squad-Alpha", "CREW_SQUAD", {"qualifications": ["HEAVY_AIRLIFT", "NIGHT_OPS"]}),
            ("Crew-Squad-Bravo", "CREW_SQUAD", {"qualifications": ["HIGH_ALTITUDE", "SEARCH_RESCUE"]}),
            ("Crew-Squad-Charlie", "CREW_SQUAD", {"qualifications": ["MEDEVAC", "QUICK_MEDEVAC"]}),
            ("Bay-Alpha-Maintenance", "MAINTENANCE_BAY", {"capacity": 1, "qualifications": ["INSPECTION_OVERHAUL"]}),
            ("Forward-Fuel-Depot-North", "SUPPORT_FACILITY", {"capacity": 2, "qualifications": ["REFUEL_RAPID"]}),
        ]

        resources = []
        for name, rtype, meta in resource_data:
            res = Resource(
                id=str(uuid.uuid4()),
                scenario_id=scenario.id,
                name=name,
                resource_type=rtype,
                status="AVAILABLE",
                metadata_json=meta
            )
            db.add(res)
            resources.append(res)
        db.flush()

        # Add availability windows for resources (120-hour operational horizon)
        for res in resources:
            # Fully available window
            db.add(ResourceAvailability(
                resource_id=res.id,
                start_at=now_base,
                end_at=now_base + timedelta(hours=120),
                available=True
            ))
            # One planned maintenance blackout window for C-130-Bravo at hour 36 to 44
            if res.name == "C-130-Bravo":
                db.add(ResourceAvailability(
                    resource_id=res.id,
                    start_at=now_base + timedelta(hours=36),
                    end_at=now_base + timedelta(hours=44),
                    available=False
                ))

        print("Seeding tasks and requirements...")
        raw_tasks = [
            ("TASK-01: Critical Medical Supplies to Sector 4", 120, 2, 12, "CRITICAL", "HEAVY_AIRLIFT"),
            ("TASK-02: Emergency Medevac Casualty Extraction", 90, 4, 10, "CRITICAL", "MEDEVAC"),
            ("TASK-03: Generator & Communications Equipment Air-drop", 180, 6, 20, "HIGH", "HEAVY_AIRLIFT"),
            ("TASK-04: High Altitude Valley Reconnaissance", 90, 8, 16, "MEDIUM", "HIGH_ALTITUDE"),
            ("TASK-05: Food & Water Rations Air-drop Sector 7", 150, 10, 24, "HIGH", "HEAVY_AIRLIFT"),
            ("TASK-06: Forward Air Controller Personnel Transit", 60, 12, 22, "MEDIUM", "FORWARD_RECON"),
            ("TASK-07: Heavy Engineering Plant Delivery", 240, 14, 32, "HIGH", "SUPER_HEAVY_AIRLIFT"),
            ("TASK-08: Urgent Trauma Doctor Insertion", 60, 5, 11, "CRITICAL", "QUICK_MEDEVAC"),
            ("TASK-09: Mobile Satellite Uplink Deployment", 120, 16, 28, "MEDIUM", "HIGH_ALTITUDE"),
            ("TASK-10: Winter Shelter Packs Airdrop Alpha", 150, 18, 30, "HIGH", "HEAVY_AIRLIFT"),
            ("TASK-11: Routine Fuel Bladder Relay", 120, 24, 40, "LOW", "HEAVY_AIRLIFT"),
            ("TASK-12: High-Altitude Perimeter Patrol", 90, 26, 36, "MEDIUM", "HIGH_ALTITUDE"),
            ("TASK-13: Second Wave Medical Relief Transit", 120, 28, 42, "HIGH", "MEDEVAC"),
            ("TASK-14: Drone Communications Relay Escort", 90, 30, 44, "LOW", "FORWARD_RECON"),
            ("TASK-15: Spare Engine Logistics Transit", 180, 32, 48, "MEDIUM", "HEAVY_AIRLIFT"),
            ("TASK-16: Night Reconnaissance Sweep", 120, 34, 46, "HIGH", "NIGHT_OPS"),
        ]

        tasks = []
        for title, dur, e_hr, l_hr, prio, req in raw_tasks:
            t = Task(
                id=str(uuid.uuid4()),
                scenario_id=scenario.id,
                name=title,
                description=f"Automated mission task: {title}",
                duration_minutes=dur,
                earliest_start=now_base + timedelta(hours=e_hr),
                latest_finish=now_base + timedelta(hours=l_hr),
                priority=prio,
                status="SCHEDULED"
            )
            db.add(t)
            tasks.append(t)
            db.flush()

            # Task Requirement
            db.add(TaskRequirement(
                task_id=t.id,
                requirement_type="QUALIFICATION",
                requirement_value=req
            ))

        print("Seeding baseline schedule version and initial assignments...")
        baseline_version = ScheduleVersion(
            id=str(uuid.uuid4()),
            scenario_id=scenario.id,
            version_number=1,
            parent_version_id=None,
            status="APPROVED",
            created_by=users["planner"].id,
            created_at=now_base
        )
        db.add(baseline_version)
        db.flush()

        # Map each task to an eligible resource with conflict-free timings
        c130_a = next(r for r in resources if r.name == "C-130-Alpha")
        c130_b = next(r for r in resources if r.name == "C-130-Bravo")
        il76 = next(r for r in resources if r.name == "IL-76-Heavy")
        mi17_1 = next(r for r in resources if r.name == "Mi-17-Raptor-1")
        mi17_2 = next(r for r in resources if r.name == "Mi-17-Raptor-2")
        alh1 = next(r for r in resources if r.name == "ALH-Dhruv-01")
        alh2 = next(r for r in resources if r.name == "ALH-Dhruv-02")

        # Deterministic conflict-free initial assignments:
        assignment_plan = [
            (tasks[0], c130_a, 2, 4),      # Task 1 on C-130-A: hrs 2-4
            (tasks[1], mi17_2, 4, 5.5),    # Task 2 on Mi-17-2: hrs 4-5.5
            (tasks[2], c130_b, 6, 9),      # Task 3 on C-130-B: hrs 6-9
            (tasks[3], mi17_1, 8, 9.5),    # Task 4 on Mi-17-1: hrs 8-9.5
            (tasks[4], c130_a, 10, 12.5),  # Task 5 on C-130-A: hrs 10-12.5
            (tasks[5], alh2, 12, 13),      # Task 6 on ALH-2: hrs 12-13
            (tasks[6], il76, 14, 18),      # Task 7 on IL-76: hrs 14-18
            (tasks[7], alh1, 5, 6),        # Task 8 on ALH-1: hrs 5-6
            (tasks[8], mi17_1, 16, 18),    # Task 9 on Mi-17-1: hrs 16-18
            (tasks[9], c130_a, 18, 20.5),  # Task 10 on C-130-A: hrs 18-20.5
            (tasks[10], c130_b, 24, 26),   # Task 11 on C-130-B: hrs 24-26
            (tasks[11], mi17_1, 26, 27.5), # Task 12 on Mi-17-1: hrs 26-27.5
            (tasks[12], mi17_2, 28, 30),   # Task 13 on Mi-17-2: hrs 28-30
            (tasks[13], alh2, 30, 31.5),   # Task 14 on ALH-2: hrs 30-31.5
            (tasks[14], c130_a, 32, 35),   # Task 15 on C-130-A: hrs 32-35
            (tasks[15], c130_a, 36, 38),   # Task 16 on C-130-A: hrs 36-38
        ]

        for t, res, s_h, e_h in assignment_plan:
            start_dt = now_base + timedelta(hours=s_h)
            end_dt = now_base + timedelta(hours=e_h)
            db.add(Assignment(
                schedule_version_id=baseline_version.id,
                task_id=t.id,
                resource_id=res.id,
                start_at=start_dt,
                end_at=end_dt
            ))

        print("Seeding synthetic demonstration locations...")
        seed_locations(db, scenario.id)

        db.commit()
        _ensure_contested(db)
        print("Database seeded successfully with users, scenario, resources, tasks, baseline schedule, and synthetic locations!")

    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
        raise
    finally:
        if should_close:
            db.close()


if __name__ == "__main__":
    seed_database()
