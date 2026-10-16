import uuid
from datetime import datetime, timedelta, timezone
from app.models.all_models import (
    Scenario, Resource, ResourceAvailability, Task, TaskRequirement,
    ScheduleVersion, Assignment
)
from app.services.conflict_service import check_schedule_conflicts


def test_baseline_schedule_has_zero_conflicts(db_session):
    """The seeded baseline schedule must be 100% valid with 0 conflicts."""
    schedule = db_session.query(ScheduleVersion).filter_by(version_number=1).first()
    assert schedule is not None

    result = check_schedule_conflicts(db_session, schedule.id)
    assert result.is_valid is True
    assert result.conflict_count == 0
    assert len(result.conflicts) == 0


def test_detects_resource_overlap(db_session):
    """Inject overlapping tasks on the same resource and verify detection."""
    schedule = db_session.query(ScheduleVersion).filter_by(version_number=1).first()
    resource = db_session.query(Resource).filter_by(name="C-130-Alpha").first()
    scenario = db_session.query(Scenario).first()

    now = datetime.now(timezone.utc)
    # Create two overlapping tasks on this resource
    t1 = Task(scenario_id=scenario.id, name="Overlap T1", duration_minutes=60, earliest_start=now, latest_finish=now + timedelta(hours=5))
    t2 = Task(scenario_id=scenario.id, name="Overlap T2", duration_minutes=60, earliest_start=now, latest_finish=now + timedelta(hours=5))
    db_session.add_all([t1, t2])
    db_session.flush()

    # Overlapping times: 10:00-11:00 and 10:30-11:30
    db_session.add(Assignment(schedule_version_id=schedule.id, task_id=t1.id, resource_id=resource.id, start_at=now, end_at=now + timedelta(hours=1)))
    db_session.add(Assignment(schedule_version_id=schedule.id, task_id=t2.id, resource_id=resource.id, start_at=now + timedelta(minutes=30), end_at=now + timedelta(minutes=90)))
    db_session.commit()

    result = check_schedule_conflicts(db_session, schedule.id)
    assert result.is_valid is False
    assert any(c.code == "RESOURCE_OVERLAP" and resource.id == c.resource_id for c in result.conflicts)


def test_detects_availability_blackout(db_session):
    """Inject assignment during resource blackout window."""
    schedule = db_session.query(ScheduleVersion).filter_by(version_number=1).first()
    resource = db_session.query(Resource).filter_by(name="C-130-Bravo").first()
    scenario = db_session.query(Scenario).first()

    now = datetime.now(timezone.utc)
    # Add blackout window
    db_session.add(ResourceAvailability(
        resource_id=resource.id,
        start_at=now + timedelta(hours=10),
        end_at=now + timedelta(hours=14),
        available=False
    ))
    # Add assignment intersecting the blackout
    t = Task(scenario_id=scenario.id, name="Blackout Task", duration_minutes=120, earliest_start=now, latest_finish=now + timedelta(hours=20))
    db_session.add(t)
    db_session.flush()

    db_session.add(Assignment(
        schedule_version_id=schedule.id,
        task_id=t.id,
        resource_id=resource.id,
        start_at=now + timedelta(hours=11),
        end_at=now + timedelta(hours=13)
    ))
    db_session.commit()

    result = check_schedule_conflicts(db_session, schedule.id)
    assert result.is_valid is False
    assert any(c.code == "AVAILABILITY_BREACH" for c in result.conflicts)


def test_detects_time_window_violations(db_session):
    """Inject task scheduled past its strict deadline."""
    schedule = db_session.query(ScheduleVersion).filter_by(version_number=1).first()
    resource = db_session.query(Resource).first()
    scenario = db_session.query(Scenario).first()

    now = datetime.now(timezone.utc)
    # Task deadline is 2 hours from now
    t = Task(
        scenario_id=scenario.id,
        name="Late Task",
        duration_minutes=60,
        earliest_start=now,
        latest_finish=now + timedelta(hours=2)
    )
    db_session.add(t)
    db_session.flush()

    # Assign task to finish at hour 3 (1 hour late)
    db_session.add(Assignment(
        schedule_version_id=schedule.id,
        task_id=t.id,
        resource_id=resource.id,
        start_at=now + timedelta(hours=2),
        end_at=now + timedelta(hours=3)
    ))
    db_session.commit()

    result = check_schedule_conflicts(db_session, schedule.id)
    assert result.is_valid is False
    assert any(c.code == "TIME_WINDOW_VIOLATION" for c in result.conflicts)


def test_detects_eligibility_mismatch(db_session):
    """Assign task requiring heavy airlift to a light helicopter without that qualification."""
    schedule = db_session.query(ScheduleVersion).filter_by(version_number=1).first()
    helicopter = db_session.query(Resource).filter_by(name="ALH-Dhruv-01").first()
    scenario = db_session.query(Scenario).first()

    now = datetime.now(timezone.utc)
    t = Task(
        scenario_id=scenario.id,
        name="Heavy Load Cargo",
        duration_minutes=60,
        earliest_start=now,
        latest_finish=now + timedelta(hours=10)
    )
    db_session.add(t)
    db_session.flush()

    db_session.add(TaskRequirement(
        task_id=t.id,
        requirement_type="QUALIFICATION",
        requirement_value="HEAVY_AIRLIFT"
    ))
    db_session.flush()

    db_session.add(Assignment(
        schedule_version_id=schedule.id,
        task_id=t.id,
        resource_id=helicopter.id,
        start_at=now + timedelta(hours=1),
        end_at=now + timedelta(hours=2)
    ))
    db_session.commit()

    result = check_schedule_conflicts(db_session, schedule.id)
    assert result.is_valid is False
    assert any(c.code == "ELIGIBILITY_MISMATCH" for c in result.conflicts)
