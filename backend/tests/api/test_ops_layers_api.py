"""Threats and airspace, crews, stores and predicted risk: solver, validator, API and helpers."""
from datetime import timedelta, timezone

import pytest

from app.db.demo_contested import seed_contested_scenario, upgrade_contested_layers
from app.models.all_models import Assignment, Resource, ScheduleVersion, Task, User
from app.models.ops_models import Crew, OpsZone, StoreItem
from app.models.weather_models import Location
from app.services import copilot_service
from app.services.conflict_service import check_schedule_conflicts
from app.services.ops_constraints import zone_contains


@pytest.fixture
def contested(db_session):
    planner = db_session.query(User).filter_by(email="planner@airops.demo").first()
    sc = seed_contested_scenario(db_session, planner.id)
    db_session.commit()
    return sc.id


def _utc(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _plan(db, scenario_id):
    v = db.query(ScheduleVersion).filter_by(scenario_id=scenario_id, status="APPROVED").one()
    return v, db.query(Assignment).filter_by(schedule_version_id=v.id).all()


def _optimise(client, headers, schedule_id):
    res = client.post(f"/api/v1/schedules/{schedule_id}/optimisation-runs", headers=headers,
                      json={"schedule_id": schedule_id, "solver_time_limit_seconds": 8})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["solver_status"] in ("OPTIMAL", "FEASIBLE"), body
    return body


def test_seeded_plan_is_crewed_and_respects_every_layer(db_session, contested):
    v, plan = _plan(db_session, contested)
    assert plan and all(a.crew_id for a in plan)
    assert check_schedule_conflicts(db_session, v.id).is_valid

    tasks = {t.id: t for t in db_session.query(Task).filter_by(scenario_id=contested)}
    res = {r.id: r for r in db_session.query(Resource).filter_by(scenario_id=contested)}
    sites = {loc.id: loc for loc in db_session.query(Location).filter_by(scenario_id=contested)}
    for z in db_session.query(OpsZone).filter_by(scenario_id=contested, effect="BLOCK"):
        for a in plan:
            site = sites.get(tasks[a.task_id].location_id)
            if not site or not zone_contains(z, site.latitude, site.longitude):
                continue
            overlaps = _utc(a.start_at) < _utc(z.active_until) and _utc(z.active_from) < _utc(a.end_at)
            if overlaps:
                # Only protected aircraft fly inside an exempting zone, nobody inside the others
                assert z.exempt_capability and z.exempt_capability in res[a.resource_id].metadata_json["qualifications"], (z.name, tasks[a.task_id].name)


def test_layer_endpoints(client, contested, planner_headers):
    zones = client.get(f"/api/v1/zones/{contested}", headers=planner_headers).json()
    sam = next(z for z in zones if z["kind"] == "SAM")
    assert sam["exempt_capability"] == "DASS" and any(t["name"].startswith("WL-16") for t in sam["affected_tasks"])
    assert any(z["polygon"] for z in zones)

    crews = client.get(f"/api/v1/crews/{contested}", headers=planner_headers).json()
    assert len(crews) == 9 and sum(c["planned_sorties"] for c in crews) > 0
    stores = {s["store_type"]: s for s in client.get(f"/api/v1/stores/{contested}", headers=planner_headers).json()}
    assert stores["FLARE_SET"]["planned_use"] <= stores["FLARE_SET"]["quantity"]
    assert "ALH-Rudra-01" in stores["ATGM"]["carriers"]


def test_schedule_shows_crew_names(client, db_session, contested, planner_headers):
    v, _ = _plan(db_session, contested)
    body = client.get(f"/api/v1/schedules/{v.id}", headers=planner_headers).json()
    assert all(a["crew_name"] for a in body["assignments"])


def test_validator_catches_crew_rest_and_duty(db_session, contested):
    v, plan = _plan(db_session, contested)
    crew = db_session.get(Crew, plan[0].crew_id)
    mine = sorted((a for a in plan if a.crew_id == crew.id), key=lambda a: a.start_at)
    other = next(a for a in plan if a.crew_id != crew.id and db_session.get(Resource, a.resource_id).resource_type in crew.aircraft_types
                 and abs((a.start_at - mine[0].end_at).total_seconds()) < 4 * 3600)
    other.crew_id = crew.id
    crew.max_duty_minutes = 60
    db_session.flush()
    codes = {c.code for c in check_schedule_conflicts(db_session, v.id).conflicts}
    assert "CREW_DUTY_EXCEEDED" in codes
    db_session.rollback()


def test_crew_unfit_forces_a_replan_without_that_crew(client, db_session, contested, planner_headers):
    v, plan = _plan(db_session, contested)
    busiest = max({a.crew_id for a in plan}, key=lambda cid: sum(a.crew_id == cid for a in plan))
    res = client.patch(f"/api/v1/crews/crew/{busiest}", headers=planner_headers, json={"status": "UNFIT"})
    assert res.status_code == 200 and res.json()["status"] == "UNFIT"
    db_session.expire_all()
    assert "CREW_UNAVAILABLE" in {c.code for c in check_schedule_conflicts(db_session, v.id).conflicts}

    run = _optimise(client, planner_headers, v.id)
    assert run["validation"]["is_valid"], run["validation"]["conflicts"]
    new = db_session.query(Assignment).filter_by(schedule_version_id=run["new_schedule_version_id"]).all()
    assert new and busiest not in {a.crew_id for a in new}


def test_short_stores_are_shared_by_priority(client, db_session, contested, planner_headers):
    v, _ = _plan(db_session, contested)
    flares = db_session.query(StoreItem).filter_by(scenario_id=contested, store_type="FLARE_SET").one()
    res = client.patch(f"/api/v1/stores/item/{flares.id}", headers=planner_headers, json={"quantity": 3})
    assert res.status_code == 200
    db_session.expire_all()  # the API wrote through its own session
    assert "STORES_SHORTFALL" in {c.code for c in check_schedule_conflicts(db_session, v.id).conflicts}

    run = _optimise(client, planner_headers, v.id)
    assert run["validation"]["is_valid"]
    tasks = {t.id: t for t in db_session.query(Task).filter_by(scenario_id=contested)}
    flown = [tasks[a.task_id] for a in db_session.query(Assignment).filter_by(schedule_version_id=run["new_schedule_version_id"])
             if any(r.requirement_value.startswith("FLARE_SET") for r in tasks[a.task_id].requirements)]
    assert len(flown) == 3
    # The critical casualty evacuation keeps its flares
    assert any(t.name.startswith("WL-11") for t in flown)


def test_new_no_fly_zone_clears_its_site(client, db_session, contested, planner_headers):
    v, _ = _plan(db_session, contested)
    alpha = db_session.query(Location).filter_by(scenario_id=contested, name="Alpha FOB").one()
    res = client.post(f"/api/v1/zones/{contested}", headers=planner_headers, json={
        "name": "Exercise no-fly box, Alpha", "category": "AIRSPACE", "kind": "NO_FLY", "effect": "BLOCK",
        "center_lat": alpha.latitude, "center_lon": alpha.longitude, "radius_km": 10, "source": "NOTAM", "confidence": 1,
    })
    assert res.status_code == 201, res.text
    assert len(res.json()["affected_tasks"]) >= 3
    db_session.expire_all()
    assert "AIRSPACE_VIOLATION" in {c.code for c in check_schedule_conflicts(db_session, v.id).conflicts}

    run = _optimise(client, planner_headers, v.id)
    tasks = {t.id: t for t in db_session.query(Task).filter_by(scenario_id=contested)}
    new = db_session.query(Assignment).filter_by(schedule_version_id=run["new_schedule_version_id"]).all()
    assert not any(tasks[a.task_id].location_id == alpha.id for a in new)
    assert run["validation"]["is_valid"]


@pytest.mark.parametrize("body", [
    {"name": "No shape", "category": "THREAT", "kind": "SAM"},
    {"name": "Bad kind", "category": "THREAT", "kind": "LASER", "center_lat": 34, "center_lon": 77, "radius_km": 5},
    {"name": "Backwards", "category": "THREAT", "kind": "SAM", "center_lat": 34, "center_lon": 77, "radius_km": 5,
     "active_from": "2026-10-20T12:00:00Z", "active_until": "2026-10-20T10:00:00Z"},
    {"name": "Two points", "category": "AIRSPACE", "kind": "RESTRICTED", "polygon": [[34, 77], [34.1, 77.1]]},
])
def test_zone_input_is_checked(client, contested, planner_headers, body):
    assert client.post(f"/api/v1/zones/{contested}", headers=planner_headers, json=body).status_code == 422


def test_viewer_cannot_change_layers(client, db_session, contested, viewer_headers):
    crew = db_session.query(Crew).filter_by(scenario_id=contested).first()
    assert client.patch(f"/api/v1/crews/crew/{crew.id}", headers=viewer_headers, json={"status": "UNFIT"}).status_code == 403


def test_risk_report_explains_each_score(client, db_session, contested, planner_headers):
    v, plan = _plan(db_session, contested)
    body = client.get(f"/api/v1/risk/schedules/{v.id}", headers=planner_headers).json()
    assert body["summary"]["sorties"] == len(plan)
    scores = [s["score"] for s in body["sorties"]]
    assert scores == sorted(scores, reverse=True) and 0 <= min(scores) <= max(scores) <= 100
    top = body["sorties"][0]
    assert top["factors"] and top["crew_name"]
    # Flying inside the SAM zone under DASS protection is a named risk factor
    assert any("SAM" in f["detail"] for s in body["sorties"] for f in s["factors"])


def test_courses_of_action_report_risk_and_crews(client, db_session, contested, planner_headers):
    v, _ = _plan(db_session, contested)
    body = client.post(f"/api/v1/schedules/{v.id}/courses-of-action", headers=planner_headers,
                       json={"include_weather": False, "time_limit_seconds": 4}).json()
    course = next(c for c in body["courses"] if c["metrics"])
    assert course["metrics"]["risk_average"] is not None and course["metrics"]["validator_pass"]
    assert all(o["crew_name"] for o in course["tasks"] if o["resource_id"])


def test_branch_copies_layers(client, db_session, contested, planner_headers):
    res = client.post(f"/api/v1/branches/{contested}", headers=planner_headers, json={"name": "Layer copy"})
    assert res.status_code in (200, 201), res.text
    branch = res.json()["id"]
    assert db_session.query(Crew).filter_by(scenario_id=branch).count() == 9
    assert db_session.query(OpsZone).filter_by(scenario_id=branch).count() == 3
    v, plan = _plan(db_session, branch)
    assert all(a.crew_id for a in plan) and check_schedule_conflicts(db_session, v.id).is_valid


def test_upgrade_adds_layers_to_an_older_scenario(db_session, contested):
    v, plan = _plan(db_session, contested)
    for a in plan:
        a.crew_id = None
    for model in (Crew, StoreItem, OpsZone):
        db_session.query(model).filter_by(scenario_id=contested).delete()
    db_session.flush()

    from app.models.all_models import Scenario
    assert upgrade_contested_layers(db_session, db_session.get(Scenario, contested)) is True
    assert upgrade_contested_layers(db_session, db_session.get(Scenario, contested)) is False  # idempotent
    assert db_session.query(Crew).filter_by(scenario_id=contested).count() >= 9
    assert sum(a.crew_id is not None for a in plan) >= len(plan) - 2


def test_copilot_layer_tools(db_session, contested):
    threats = copilot_service.tool_get_threats(db_session, contested, {})
    assert {z["type"].split(" / ")[1] for z in threats["zones"]} >= {"SAM", "MANPADS", "RESTRICTED"}
    ready = copilot_service.tool_get_readiness(db_session, contested, {})
    assert len(ready["crews"]) == 9 and {s["type"] for s in ready["stores"]} == {"FLARE_SET", "ROCKET_POD", "ATGM"}
    risk = copilot_service.tool_get_risk(db_session, contested, {})
    assert risk["riskiest_sorties"] and risk["riskiest_sorties"][0]["reasons"]
