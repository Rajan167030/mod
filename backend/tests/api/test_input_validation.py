"""Bad input is rejected with a clear 4xx instead of being stored or crashing the server."""
import pytest

from app.db.demo_contested import seed_contested_scenario
from app.models.all_models import AuditEvent, Task, User

T0, T4 = "2026-10-20T10:00:00Z", "2026-10-20T14:00:00Z"


@pytest.fixture
def contested(db_session):
    planner = db_session.query(User).filter_by(email="planner@airops.demo").first()
    sc = seed_contested_scenario(db_session, planner.id)
    db_session.commit()
    return sc.id


@pytest.fixture
def task(db_session, contested):
    return db_session.query(Task).filter_by(scenario_id=contested).order_by(Task.name).first()


def _task(scenario_id, **over):
    body = {"scenario_id": scenario_id, "name": "New sortie", "duration_minutes": 60,
            "earliest_start": T0, "latest_finish": T4}
    return {**body, **over}


@pytest.mark.parametrize("over", [
    {"earliest_start": T4, "latest_finish": T0},           # finishes before it starts
    {"duration_minutes": 300},                             # longer than its 4-hour window
    {"priority": "SUPER"},
    {"status": "lol"},
])
def test_create_task_rejects_bad_values(client, contested, planner_headers, over):
    res = client.post("/api/v1/tasks", headers=planner_headers, json=_task(contested, **over))
    assert res.status_code == 422, res.text


def test_create_task_needs_a_real_scenario(client, planner_headers):
    assert client.post("/api/v1/tasks", headers=planner_headers, json=_task("nope")).status_code == 404


def test_create_task_normalises_priority_and_naive_times(client, contested, planner_headers):
    res = client.post(
        "/api/v1/tasks", headers=planner_headers,
        json=_task(contested, priority="high", earliest_start="2026-10-20T10:00:00", latest_finish=T4),
    )
    assert res.status_code == 201, res.text
    assert res.json()["priority"] == "HIGH"


def test_moving_a_task_window_saves_and_is_audited(client, db_session, task, planner_headers):
    """Used to fail with a 500: the audit log could not store datetimes."""
    res = client.patch(
        f"/api/v1/tasks/{task.id}", headers=planner_headers,
        json={"earliest_start": "2026-10-21T06:00:00Z", "latest_finish": "2026-10-21T18:00:00Z"},
    )
    assert res.status_code == 200, res.text
    event = db_session.query(AuditEvent).filter_by(action="TASK_UPDATED", entity_id=task.id).one()
    assert event.metadata_json["earliest_start"].startswith("2026-10-21")


@pytest.mark.parametrize("body", [
    {"duration_minutes": 0},
    {"duration_minutes": -30},
    {"duration_minutes": 100000},
    {"latest_finish": "2000-01-01T00:00:00Z"},  # before the stored earliest_start
    {"name": ""},
    {"name": None},
    {"priority": "lol"},
])
def test_patch_task_rejects_bad_values(client, task, planner_headers, body):
    res = client.patch(f"/api/v1/tasks/{task.id}", headers=planner_headers, json=body)
    assert res.status_code == 422, res.text


def test_resource_and_scenario_values_are_checked(client, contested, planner_headers, db_session):
    assert client.post("/api/v1/resources", headers=planner_headers,
                       json={"scenario_id": contested, "name": "X1", "resource_type": "AIRCRAFT", "status": "lol"}).status_code == 422
    assert client.post("/api/v1/resources", headers=planner_headers,
                       json={"scenario_id": "nope", "name": "X1", "resource_type": "AIRCRAFT"}).status_code == 404
    assert client.patch(f"/api/v1/scenarios/{contested}", headers=planner_headers, json={"name": ""}).status_code == 422
    assert client.patch(f"/api/v1/scenarios/{contested}", headers=planner_headers, json={"status": "lol"}).status_code == 422
    assert client.post("/api/v1/scenarios", headers=planner_headers, json={"name": "abc", "status": "lol"}).status_code == 422


def test_optimiser_limits(client, contested, planner_headers):
    plan = next(v for v in client.get(f"/api/v1/scenarios/{contested}/schedules", headers=planner_headers).json()
                if v["status"] == "APPROVED")
    for body in ({"solver_time_limit_seconds": 100000}, {"solver_time_limit_seconds": 0}, {"weight_unassigned": -1}):
        res = client.post(f"/api/v1/schedules/{plan['id']}/optimisation-runs", headers=planner_headers,
                          json={"schedule_id": plan["id"], **body})
        assert res.status_code == 422, (body, res.text)


def _disrupt(client, headers, scenario_id, dtype, payload):
    return client.post(f"/api/v1/scenarios/{scenario_id}/disruptions", headers=headers,
                       json={"scenario_id": scenario_id, "type": dtype, "payload_json": payload})


def test_disruption_parameters_are_checked(client, db_session, contested, task, planner_headers):
    aircraft = client.get(f"/api/v1/resources?scenario_id={contested}", headers=planner_headers).json()[0]["id"]
    bad = [
        ("WINDOW_SHIFT", {"resource_id": aircraft, "blackout_start": T4, "blackout_end": T0}),
        ("WINDOW_SHIFT", {"resource_id": aircraft, "blackout_start": "tomorrow"}),
        ("DURATION_SURGE", {"task_id": task.id, "surge_minutes": "lots"}),
        ("DURATION_SURGE", {"task_id": task.id, "surge_minutes": -task.duration_minutes}),
        ("DEADLINE_TIGHTEN", {"task_id": task.id, "tighten_hours": 24 * 7}),
        ("RESOURCE_UNAVAILABLE", {"resource_id": aircraft, "new_status": "lol"}),
    ]
    for dtype, payload in bad:
        res = _disrupt(client, planner_headers, contested, dtype, payload)
        assert res.status_code == 422, (dtype, payload, res.text)

    ok = _disrupt(client, planner_headers, contested, "WINDOW_SHIFT",
                  {"resource_id": aircraft, "blackout_start": T0, "blackout_end": T4})
    assert ok.status_code == 201, ok.text


@pytest.mark.parametrize("content", [
    bytes(range(256)) * 8,                                   # binary, not a CSV
    b'name,duration_minutes\n"unclosed,60\n' + b"x" * 200_000,  # runaway quoted field
], ids=["binary", "unclosed-quote"])
def test_import_rejects_unreadable_csv(client, contested, planner_headers, content):
    res = client.post(f"/api/v1/imports/{contested}/tasks/preview", headers=planner_headers,
                      files={"file": ("x.csv", content, "text/csv")})
    assert res.status_code == 422, res.text


def test_import_tolerates_rows_wider_than_the_header(client, contested, planner_headers):
    csv = b"name,priority,duration_minutes,earliest_start,latest_finish\nWL-90 Spare,HIGH,60,2026-10-20T10:00Z,2026-10-20T14:00Z,extra,cells\n"
    res = client.post(f"/api/v1/imports/{contested}/tasks/preview", headers=planner_headers,
                      files={"file": ("x.csv", csv, "text/csv")})
    assert res.status_code == 200, res.text
    assert res.json()["summary"]["total"] == 1


def test_csv_export_neutralises_formulas_and_prefers_the_approved_plan(client, db_session, contested, planner_headers):
    import csv, io

    plan = next(v for v in client.get(f"/api/v1/scenarios/{contested}/schedules", headers=planner_headers).json()
                if v["status"] == "APPROVED")
    scheduled = db_session.get(Task, plan["assignments"][0]["task_id"])
    scheduled.name = '=HYPERLINK("http://example.invalid")'
    db_session.commit()

    res = client.get(f"/api/v1/reports/scenario/{contested}/export-csv", headers=planner_headers)
    assert res.status_code == 200
    rows = list(csv.DictReader(io.StringIO(res.text)))
    assert {r["Plan_Status"] for r in rows} == {"APPROVED"}
    assert "'" + scheduled.name in {r["Task_Name"] for r in rows}
    assert not any(v.startswith("=") for r in rows for v in r.values())
    assert [r["Start_UTC"] for r in rows] == sorted(r["Start_UTC"] for r in rows)
