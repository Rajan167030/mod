"""Live exercise: clock, scripted events, background replanning and the human decision path."""
from datetime import timedelta

import pytest

from app.db.demo_contested import seed_contested_scenario
from app.models.all_models import Scenario, User
from app.models.replay_models import ReplaySession
from app.services import replay_service


@pytest.fixture
def contested(db_session):
    planner = db_session.query(User).filter_by(email="planner@airops.demo").first()
    seed_contested_scenario(db_session, planner.id)
    db_session.commit()
    replay_service.RUN_REPLAN_INLINE = True
    yield
    replay_service.RUN_REPLAN_INLINE = False


def _advance(db, replay_id, minutes):
    """Move the simulated clock forward without waiting."""
    s = db.query(ReplaySession).filter_by(id=replay_id).one()
    s.sim_anchor = replay_service.sim_now(s) + timedelta(minutes=minutes)
    s.wall_anchor = replay_service._now()
    s.status = "PAUSED"
    db.commit()


def test_exercise_runs_on_a_copy_and_replans(client, db_session, contested, admin_headers):
    scenarios_before = db_session.query(Scenario).count()
    start = client.post("/api/v1/replays", headers=admin_headers, json={"script": "winter_lift", "speed": 60})
    assert start.status_code == 201, start.text
    state = start.json()
    assert state["status"] == "RUNNING"
    assert db_session.query(Scenario).count() == scenarios_before + 1
    assert all(e["status"] == "PENDING" for e in state["events"])

    # Reach the aircraft failure (T+75)
    _advance(db_session, state["id"], 80)
    state = client.get(f"/api/v1/replays/{state['id']}", headers=admin_headers).json()
    events = {e["kind"]: e for e in state["events"]}
    assert events["NOTE"]["status"] == "NO_ACTION"
    failure = events["AIRCRAFT_UNSERVICEABLE"]
    assert failure["status"] == "READY", failure
    assert failure["coa_set_id"] and failure["suggested_key"]
    assert "unavailable" in failure["effect"]

    # Admin adopts the suggestion, then approves it: it becomes the active plan
    idx = failure["idx"]
    adopted = client.post(
        f"/api/v1/replays/{state['id']}/events/{idx}/decision",
        headers=admin_headers,
        json={"action": "adopt", "course": failure["suggested_key"]},
    )
    assert adopted.status_code == 200, adopted.text
    approved = client.post(
        f"/api/v1/replays/{state['id']}/events/{idx}/decision",
        headers=admin_headers,
        json={"action": "approve", "reason": "Exercise: reroute heavy lift around C-130-Alpha."},
    ).json()
    assert approved["active_version_number"] == 2
    assert approved["events"][idx]["decision"]["stage"] == "APPROVED"
    assert approved["summary"]["active_conflicts"] == 0
    assert approved["summary"]["decisions"] == 1

    # Simulated weather is labelled as an exercise inject in the alerts
    _advance(db_session, state["id"], 80)
    client.get(f"/api/v1/replays/{state['id']}", headers=admin_headers)
    alerts = client.get(f"/api/v1/weather/alerts?scenario_id={state['scenario_id']}", headers=admin_headers).json()
    injected = [a for a in alerts["alerts"] if a["source"] == "exercise"]
    assert injected and all(a["severity"] == "CRITICAL" for a in injected)

    # Closing removes the copy; the source scenario is untouched
    assert client.delete(f"/api/v1/replays/{state['id']}", headers=admin_headers).status_code == 204
    assert db_session.query(Scenario).count() == scenarios_before


def test_viewer_cannot_start_or_decide(client, contested, viewer_headers, admin_headers):
    assert client.post("/api/v1/replays", headers=viewer_headers, json={}).status_code == 403
    state = client.post("/api/v1/replays", headers=admin_headers, json={}).json()
    res = client.post(
        f"/api/v1/replays/{state['id']}/events/1/decision", headers=viewer_headers, json={"action": "adopt", "course": "FASTEST"}
    )
    assert res.status_code == 403


def test_pause_freezes_the_clock(client, contested, planner_headers):
    state = client.post("/api/v1/replays", headers=planner_headers, json={"speed": 240}).json()
    paused = client.post(f"/api/v1/replays/{state['id']}/control", headers=planner_headers, json={"action": "pause"}).json()
    later = client.get(f"/api/v1/replays/{state['id']}", headers=planner_headers).json()
    assert paused["status"] == "PAUSED"
    assert later["sim_now"] == paused["sim_now"]


def test_expired_options_can_be_solved_again(client, db_session, contested, admin_headers):
    """Options live in server memory; after a restart the event can be re-planned instead of getting stuck."""
    from app.services import coa_service

    state = client.post("/api/v1/replays", headers=admin_headers, json={"script": "winter_lift", "speed": 60}).json()
    _advance(db_session, state["id"], 80)
    state = client.get(f"/api/v1/replays/{state['id']}", headers=admin_headers).json()
    failure = next(e for e in state["events"] if e["kind"] == "AIRCRAFT_UNSERVICEABLE")
    old_set = failure["coa_set_id"]

    coa_service._sets.clear()  # what a backend restart does
    assert client.get(f"/api/v1/courses-of-action/{old_set}", headers=admin_headers).status_code == 404

    res = client.post(f"/api/v1/replays/{state['id']}/events/{failure['idx']}/decision",
                      headers=admin_headers, json={"action": "replan"})
    assert res.status_code == 200, res.text
    redone = res.json()["events"][failure["idx"]]
    assert redone["status"] == "READY" and redone["coa_set_id"] != old_set
    assert client.get(f"/api/v1/courses-of-action/{redone['coa_set_id']}", headers=admin_headers).status_code == 200
