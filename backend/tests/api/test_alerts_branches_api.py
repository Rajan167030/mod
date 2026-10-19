"""Alert rules (defaults, CRUD, evaluation) and scenario branches (create, compare, delete)."""
import pytest

from app.db.demo_contested import TASKS, seed_contested_scenario
from app.models.all_models import Resource, Scenario, User


@pytest.fixture
def contested(db_session):
    planner = db_session.query(User).filter_by(email="planner@airops.demo").first()
    sc = seed_contested_scenario(db_session, planner.id)
    db_session.commit()
    return sc.id


def test_default_rules_and_single_source_alert(client, contested, viewer_headers):
    rules = client.get(f"/api/v1/alert-rules/{contested}", headers=viewer_headers).json()
    assert {r["kind"] for r in rules} >= {"CRITICAL_UNASSIGNED", "TASK_DELAY", "SINGLE_SOURCE"}

    result = client.get(f"/api/v1/alert-rules/{contested}/evaluate", headers=viewer_headers).json()
    # NIGHT_OPS is needed by a HIGH task and held only by C-130-Alpha
    single = [a for a in result["alerts"] if a["kind"] == "SINGLE_SOURCE"]
    assert any(a["object"]["id"] == "NIGHT_OPS" for a in single)


def test_rule_fires_after_grounding_and_can_be_disabled(client, db_session, contested, planner_headers):
    rules = client.get(f"/api/v1/alert-rules/{contested}", headers=planner_headers).json()
    single = next(r for r in rules if r["kind"] == "SINGLE_SOURCE")

    db_session.query(Resource).filter_by(scenario_id=contested, name="C-130-Alpha").one().status = "GROUNDED"
    db_session.commit()
    fired = client.get(f"/api/v1/alert-rules/{contested}/evaluate", headers=planner_headers).json()["alerts"]
    night = next(a for a in fired if a["kind"] == "SINGLE_SOURCE" and a["object"]["id"] == "NIGHT_OPS")
    assert "no serviceable aircraft" in night["message"]

    body = {k: single[k] for k in ("name", "kind", "threshold", "min_priority", "severity")}
    assert client.put(f"/api/v1/alert-rules/rule/{single['id']}", headers=planner_headers, json={**body, "enabled": False}).status_code == 200
    fired = client.get(f"/api/v1/alert-rules/{contested}/evaluate", headers=planner_headers).json()["alerts"]
    assert not any(a["kind"] == "SINGLE_SOURCE" for a in fired)


def test_custom_rule_validation_and_rbac(client, contested, planner_headers, viewer_headers):
    rule = {"name": "Any aircraft over 1 h", "kind": "AIRCRAFT_HOURS", "threshold": 1, "min_priority": "LOW", "severity": "WARNING"}
    assert client.post(f"/api/v1/alert-rules/{contested}", headers=viewer_headers, json=rule).status_code == 403
    created = client.post(f"/api/v1/alert-rules/{contested}", headers=planner_headers, json=rule)
    assert created.status_code == 201, created.text
    fired = client.get(f"/api/v1/alert-rules/{contested}/evaluate", headers=planner_headers).json()["alerts"]
    assert any(a["kind"] == "AIRCRAFT_HOURS" for a in fired)

    bad = client.post(f"/api/v1/alert-rules/{contested}", headers=planner_headers, json={**rule, "kind": "NOPE"})
    assert bad.status_code == 422


def test_branch_compare_and_delete(client, db_session, contested, planner_headers):
    res = client.post(f"/api/v1/branches/{contested}", headers=planner_headers, json={"name": "Try without C-130-Alpha"})
    assert res.status_code == 201, res.text
    branch_id = res.json()["id"]
    assert db_session.query(Scenario).filter_by(id=branch_id).one().parent_scenario_id == contested

    same = client.get(f"/api/v1/branches/compare?a={contested}&b={branch_id}", headers=planner_headers).json()
    assert same["changes"] == []
    assert next(m for m in same["measures"] if m["name"] == "Tasks")["b"] == len(TASKS)

    # Change the branch only, then compare again
    db_session.query(Resource).filter_by(scenario_id=branch_id, name="C-130-Alpha").one().status = "GROUNDED"
    db_session.commit()
    diff = client.get(f"/api/v1/branches/compare?a={contested}&b={branch_id}", headers=planner_headers).json()
    serviceable = next(m for m in diff["measures"] if m["name"] == "Serviceable aircraft")
    assert serviceable["a"] == serviceable["b"] + 1
    # The original is untouched
    assert db_session.query(Resource).filter_by(scenario_id=contested, name="C-130-Alpha").one().status == "AVAILABLE"

    assert client.delete(f"/api/v1/branches/{contested}", headers=planner_headers).status_code == 422  # not a branch
    assert client.delete(f"/api/v1/branches/{branch_id}", headers=planner_headers).status_code == 204
    assert db_session.query(Scenario).filter_by(id=branch_id).count() == 0
