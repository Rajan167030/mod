"""Assigning a mission by hand, force capacity, and running the plan on the day."""
from datetime import datetime, timedelta, timezone

import pytest

from app.db.demo_contested import seed_contested_scenario
from app.models.all_models import Assignment, Resource, ResourceAvailability, ScheduleVersion, Task, User
from app.models.ops_models import StoreItem
from app.models.weather_models import Location
from app.services.conflict_service import check_schedule_conflicts


@pytest.fixture
def contested(db_session):
    planner = db_session.query(User).filter_by(email="planner@airops.demo").first()
    sc = seed_contested_scenario(db_session, planner.id)
    db_session.commit()
    return sc.id


def _utc(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _plan(db, sid):
    v = db.query(ScheduleVersion).filter_by(scenario_id=sid, status="APPROVED").order_by(ScheduleVersion.version_number.desc()).first()
    return v, db.query(Assignment).filter_by(schedule_version_id=v.id).all()


def _new_task(client, headers, sid, db, site_name, qual, hours=(3, 12), minutes=60, priority="CRITICAL", stores=()):
    site = db.query(Location).filter_by(scenario_id=sid, name=site_name).one()
    t0 = min(_utc(t.earliest_start) for t in db.query(Task).filter_by(scenario_id=sid))
    body = {
        "scenario_id": sid, "name": f"WL-90 Urgent {qual.lower()}", "priority": priority, "duration_minutes": minutes,
        "earliest_start": (t0 + timedelta(hours=hours[0])).isoformat(), "latest_finish": (t0 + timedelta(hours=hours[1])).isoformat(),
        "location_id": site.id,
        "requirements": [{"requirement_type": "QUALIFICATION", "requirement_value": qual}]
        + [{"requirement_type": "STORE", "requirement_value": s} for s in stores],
    }
    res = client.post("/api/v1/tasks", headers=headers, json=body)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_options_fit_around_the_plan_and_assign_through_review(client, db_session, contested, planner_headers, reviewer_headers):
    tid = _new_task(client, planner_headers, contested, db_session, "Foxtrot Medevac Point", "MEDEVAC")
    body = client.get(f"/api/v1/tasks/{tid}/options", headers=planner_headers).json()
    assert body["options"], body
    v, plan = _plan(db_session, contested)
    for o in body["options"]:
        assert o["crew_name"] and 0 <= o["risk"] <= 100
        for a in plan:  # never on top of an existing sortie of that aircraft
            if a.resource_id == o["resource_id"]:
                assert not (_utc(a.start_at) < datetime.fromisoformat(o["end_at"]) and datetime.fromisoformat(o["start_at"]) < _utc(a.end_at))
    assert any("lacks MEDEVAC" in r["reason"] for r in body["ruled_out"])

    pick = body["options"][0]
    res = client.post(f"/api/v1/tasks/{tid}/assign", headers=planner_headers,
                      json={"resource_id": pick["resource_id"], "crew_id": pick["crew_id"], "start_at": pick["start_at"]})
    assert res.status_code == 200, res.text
    assert res.json()["validation_ok"]
    approved = client.post(f"/api/v1/optimisation-runs/{res.json()['run_id']}/approve", headers=reviewer_headers,
                           json={"decision": "APPROVED", "reason": "Urgent medevac fits without moving other sorties."})
    assert approved.status_code == 200, approved.text
    db_session.expire_all()
    v2, plan2 = _plan(db_session, contested)
    assert v2.version_number == v.version_number + 1 and any(a.task_id == tid for a in plan2)
    assert len(plan2) == len(plan) + 1 and check_schedule_conflicts(db_session, v2.id).is_valid


def test_options_respect_threat_windows_and_stores(client, db_session, contested, planner_headers):
    # Echo Pass sits in the SAM zone (DASS only) from +6h to +14h
    tid = _new_task(client, planner_headers, contested, db_session, "Echo Pass LZ", "HIGH_ALTITUDE", hours=(6, 18))
    opts = client.get(f"/api/v1/tasks/{tid}/options", headers=planner_headers).json()["options"]
    t0 = min(_utc(t.earliest_start) for t in db_session.query(Task).filter_by(scenario_id=contested)) - timedelta(hours=1)
    res = {r.id: r for r in db_session.query(Resource).filter_by(scenario_id=contested)}
    for o in opts:
        start = datetime.fromisoformat(o["start_at"])
        inside = start < t0 + timedelta(hours=14)
        if inside:
            assert "DASS" in res[o["resource_id"]].metadata_json["qualifications"], o

    flares = db_session.query(StoreItem).filter_by(scenario_id=contested, store_type="FLARE_SET").one()
    flares.quantity = 0
    db_session.commit()
    tid2 = _new_task(client, planner_headers, contested, db_session, "Echo Pass LZ", "MEDEVAC", stores=("FLARE_SET",))
    body = client.get(f"/api/v1/tasks/{tid2}/options", headers=planner_headers).json()
    assert body["options"] == [] and body["stores_short"]


def test_capacity_adds_up(client, db_session, contested, planner_headers):
    cap = client.get(f"/api/v1/capacity/{contested}", headers=planner_headers).json()
    v, plan = _plan(db_session, contested)
    planned = sum((_utc(a.end_at) - _utc(a.start_at)).total_seconds() for a in plan) / 3600
    assert abs(cap["summary"]["planned_hours"] - planned) < 0.2
    assert cap["summary"]["tasks_planned"] == len({a.task_id for a in plan})
    bravo = next(a for a in cap["aircraft"] if a["name"] == "C-130-Bravo")
    assert bravo["maintenance_hours"] == 4 and bravo["available_hours"] == cap["horizon"]["hours"] - 4
    assert len(cap["hourly"]) == round(cap["horizon"]["hours"]) and cap["types"] and cap["crews"]["total"] == 9


def test_launch_land_abort_and_replan_from_now(client, db_session, contested, planner_headers, viewer_headers):
    v, plan = _plan(db_session, contested)
    first, second = sorted(plan, key=lambda a: a.start_at)[:2]
    url = "/api/v1/execution/sortie/"
    assert client.post(url + first.id, headers=viewer_headers, json={"action": "launch"}).status_code == 403
    assert client.post(url + first.id, headers=planner_headers, json={"action": "land"}).status_code == 422
    assert client.post(url + first.id, headers=planner_headers, json={"action": "launch"}).status_code == 200
    board = client.post(url + first.id, headers=planner_headers, json={"action": "land"}).json()
    assert board["summary"]["completed"] == 1

    assert client.post(url + second.id, headers=planner_headers, json={"action": "abort"}).status_code == 422  # reason needed
    board = client.post(url + second.id, headers=planner_headers,
                        json={"action": "abort", "reason": "Bird strike on start-up", "ground_hours": 6}).json()
    assert board["summary"]["aborted"] == 1 and board["needs_replan"]
    db_session.expire_all()
    assert db_session.query(ResourceAvailability).filter_by(resource_id=second.resource_id, available=False).count() >= 1
    assert second.task_id in check_schedule_conflicts(db_session, v.id).unassigned_task_ids

    coa = client.post(f"/api/v1/schedules/{v.id}/courses-of-action", headers=planner_headers,
                      json={"include_weather": False, "time_limit_seconds": 4, "from_now": True}).json()

    passing = [c for c in coa["courses"] if c["metrics"] and c["metrics"]["validator_pass"]]
    assert passing, [(c["key"], c["metrics"] and (c["metrics"]["validator_pass"], c["metrics"]["validator_conflicts"])) for c in coa["courses"]]
    course = passing[0]
    adopted = client.post(f"/api/v1/courses-of-action/{coa['coa_set_id']}/{course['key']}/adopt", headers=planner_headers).json()
    new = db_session.query(Assignment).filter_by(schedule_version_id=adopted["proposed_version_id"]).all()
    kept = next(a for a in new if a.task_id == first.task_id)
    assert kept.exec_status == "COMPLETED" and kept.resource_id == first.resource_id  # what flew stays as flown
    assert all(not (a.task_id == second.task_id and a.resource_id == second.resource_id) for a in new)
