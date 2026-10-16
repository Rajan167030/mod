"""Contested demo scenario, scenario clone/rebase/delete, and course-of-action trade-offs."""
from datetime import datetime, timedelta, timezone

from app.db.demo_contested import TASKS, seed_contested_scenario
from app.models.all_models import Assignment, Resource, Scenario, ScheduleVersion, Task, User
from app.models.weather_models import Location
from app.services.coa_service import generate_courses_of_action
from app.services.conflict_service import check_schedule_conflicts
from app.services.scenario_admin import clone_scenario, delete_scenario, scenario_start


def _contested(db):
    planner = db.query(User).filter_by(email="planner@airops.demo").first()
    sc = seed_contested_scenario(db, planner.id, t0=datetime(2026, 10, 16, 6, tzinfo=timezone.utc))
    db.commit()
    return sc, planner


def test_contested_baseline_is_valid_and_site_linked(db_session):
    sc, _ = _contested(db_session)
    tasks = db_session.query(Task).filter_by(scenario_id=sc.id).all()
    assert len(tasks) == len(TASKS)
    assert all(t.location_id for t in tasks)

    baseline = db_session.query(ScheduleVersion).filter_by(scenario_id=sc.id, status="APPROVED").one()
    result = check_schedule_conflicts(db_session, baseline.id)
    assert result.is_valid, [c.explanation for c in result.conflicts]


def test_grounding_creates_real_trade_offs(db_session):
    sc, planner = _contested(db_session)
    db_session.query(Resource).filter_by(scenario_id=sc.id, name="C-130-Alpha").one().status = "GROUNDED"
    db_session.flush()
    baseline = db_session.query(ScheduleVersion).filter_by(scenario_id=sc.id).one()

    res = generate_courses_of_action(db_session, baseline.id, planner, include_weather=True, time_limit_seconds=5)
    distinct = [c for c in res.courses if not c.same_as]
    assert len(distinct) >= 2, "plans should differ once heavy-lift capacity is short"
    assert all(c.metrics.validator_pass for c in res.courses)
    # The only night-qualified aircraft is grounded, so the night resupply cannot fly in any plan
    for c in res.courses:
        night = next(t for t in c.tasks if t.task_name.startswith("WL-07"))
        assert night.resource_id is None


def test_clone_rebases_times_and_delete_removes_everything(db_session):
    sc, planner = _contested(db_session)
    new_t0 = datetime(2026, 12, 1, 0, tzinfo=timezone.utc)
    copy = clone_scenario(db_session, sc.id, "Replay copy", None, planner.id, new_t0=new_t0)
    db_session.commit()

    assert scenario_start(db_session, copy.id) == new_t0
    src_tasks = {t.name: t for t in db_session.query(Task).filter_by(scenario_id=sc.id)}
    for t in db_session.query(Task).filter_by(scenario_id=copy.id):
        offset = t.earliest_start.replace(tzinfo=timezone.utc) - new_t0
        src_offset = src_tasks[t.name].earliest_start.replace(tzinfo=timezone.utc) - datetime(2026, 10, 16, 6, tzinfo=timezone.utc)
        assert offset == src_offset
        assert t.location_id and db_session.get(Location, t.location_id).scenario_id == copy.id

    copied_version = db_session.query(ScheduleVersion).filter_by(scenario_id=copy.id).one()
    assert check_schedule_conflicts(db_session, copied_version.id).is_valid

    # ORM objects are unusable once their rows are gone, so keep plain ids
    copy_id, version_id = copy.id, copied_version.id
    delete_scenario(db_session, copy_id)
    db_session.commit()
    assert db_session.query(Scenario).filter_by(id=copy_id).count() == 0
    assert db_session.query(Task).filter_by(scenario_id=copy_id).count() == 0
    assert db_session.query(Assignment).filter_by(schedule_version_id=version_id).count() == 0
    # The source is untouched
    assert db_session.query(Task).filter_by(scenario_id=sc.id).count() == len(TASKS)
