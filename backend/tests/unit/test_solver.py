from datetime import datetime, timedelta, timezone
from app.models.all_models import Scenario, Resource, ResourceAvailability, Task, TaskRequirement
from app.engine.solver import solve_schedule_scenario


def test_solver_produces_optimal_schedule(db_session):
    """The CP-SAT solver must solve the seeded scenario and return FEASIBLE or OPTIMAL."""
    scenario = db_session.query(Scenario).first()
    resources = db_session.query(Resource).filter_by(scenario_id=scenario.id).all()
    availabilities = db_session.query(ResourceAvailability).join(Resource).filter(Resource.scenario_id == scenario.id).all()
    tasks = db_session.query(Task).filter_by(scenario_id=scenario.id).all()

    result = solve_schedule_scenario(
        scenario=scenario,
        resources=resources,
        availabilities=availabilities,
        tasks=tasks,
        time_limit_seconds=10
    )

    assert result.solver_status in ["OPTIMAL", "FEASIBLE"]
    assert len(result.assignments) > 0
    assert result.objective_value is not None


def test_solver_detects_infeasible_or_unassigned_when_no_qualified_resource(db_session):
    """If a task requires an impossible qualification, it should be flagged as unassigned or explained."""
    scenario = db_session.query(Scenario).first()
    resources = db_session.query(Resource).filter_by(scenario_id=scenario.id).all()
    availabilities = db_session.query(ResourceAvailability).join(Resource).filter(Resource.scenario_id == scenario.id).all()

    now = datetime.now(timezone.utc)
    impossible_task = Task(
        scenario_id=scenario.id,
        name="Mission Impossible Qualification",
        duration_minutes=60,
        earliest_start=now,
        latest_finish=now + timedelta(hours=5),
        priority="CRITICAL"
    )
    db_session.add(impossible_task)
    db_session.flush()

    db_session.add(TaskRequirement(
        task_id=impossible_task.id,
        requirement_type="QUALIFICATION",
        requirement_value="NON_EXISTENT_QUANTUM_DRIVE"
    ))
    db_session.commit()

    tasks = db_session.query(Task).filter_by(scenario_id=scenario.id).all()

    result = solve_schedule_scenario(
        scenario=scenario,
        resources=resources,
        availabilities=availabilities,
        tasks=tasks,
        time_limit_seconds=10
    )

    # The impossible task should either be in unassigned_tasks or result in infeasibility explanation
    assert impossible_task.id in result.unassigned_tasks or len(result.infeasibility_reasons) > 0


def test_solver_respects_maintenance_window_on_only_resource():
    """Regression: blackouts were appended after AddNoOverlap and silently ignored."""
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from app.engine.solver import solve_schedule_scenario

    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    plane = SimpleNamespace(id="r1", name="Only-Plane", status="AVAILABLE", metadata_json={"qualifications": ["HEAVY_AIRLIFT"]})
    task = SimpleNamespace(
        id="t1", name="Lift", priority="HIGH", duration_minutes=120,
        earliest_start=t0, latest_finish=t0 + timedelta(hours=6),
        requirements=[SimpleNamespace(requirement_type="QUALIFICATION", requirement_value="HEAVY_AIRLIFT")],
    )
    maintenance = SimpleNamespace(id="m1", resource_id="r1", available=False, start_at=t0, end_at=t0 + timedelta(hours=3))

    result = solve_schedule_scenario(
        scenario=None, resources=[plane], availabilities=[maintenance], tasks=[task], time_limit_seconds=5
    )
    assert result.solver_status in ("OPTIMAL", "FEASIBLE")
    (a,) = result.assignments
    assert a["start_at"] >= t0 + timedelta(hours=3)


def test_solver_ignores_blackouts_that_ended_before_the_horizon():
    """Regression: a past window clipped to [0, 0] with size 1 made the whole model infeasible."""
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from app.engine.solver import solve_schedule_scenario

    t0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    plane = SimpleNamespace(id="r1", name="P", status="AVAILABLE", metadata_json={"qualifications": ["X"]})
    task = SimpleNamespace(
        id="t1", name="T", priority="HIGH", duration_minutes=60, earliest_start=t0, latest_finish=t0 + timedelta(hours=3),
        requirements=[SimpleNamespace(requirement_type="QUALIFICATION", requirement_value="X")],
    )
    past = SimpleNamespace(id="old", resource_id="r1", available=False, start_at=t0 - timedelta(hours=5), end_at=t0 - timedelta(hours=2))

    result = solve_schedule_scenario(scenario=None, resources=[plane], availabilities=[past], tasks=[task], time_limit_seconds=5)
    assert result.solver_status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1
