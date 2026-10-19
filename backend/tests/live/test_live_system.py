"""End-to-end checks against the running backend, real weather providers and the real copilot model."""
import pytest

from app.core.config import settings
from app.db.demo_contested import CONTESTED_SCENARIO_NAME

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def winter_lift(http, planner):
    scenarios = http.get("/scenarios", headers=planner).json()
    sc = next(s for s in scenarios if s["name"] == CONTESTED_SCENARIO_NAME)
    versions = http.get(f"/scenarios/{sc['id']}/schedules", headers=planner).json()
    plan = max((v for v in versions if v["status"] == "APPROVED"), key=lambda v: v["version_number"])
    return sc["id"], plan["id"]


def test_server_and_database_are_up(live_server):
    import httpx

    health = httpx.get(f"{live_server}/health").json()
    assert health["status"] == "HEALTHY" and health["database"] == "UP"


def test_login_rejects_a_wrong_password(http):
    res = http.post("/auth/login", json={"email": "planner@airops.demo", "password": "wrong"})
    assert res.status_code == 401


def test_viewer_cannot_run_the_optimiser(http, viewer, winter_lift):
    _, plan_id = winter_lift
    res = http.post(f"/schedules/{plan_id}/optimisation-runs", headers=viewer, json={"schedule_id": plan_id})
    assert res.status_code == 403


def test_live_open_meteo_forecast(http, planner):
    loc = http.get("/locations", headers=planner).json()[0]
    current = http.get("/weather/current", headers=planner, params={"location_id": loc["id"]}).json()
    # FRESH means it was fetched from Open-Meteo just now, not served from a fallback
    assert current["freshness"] == "FRESH", current
    assert current["data"] is not None

    forecast = http.get("/weather/forecast", headers=planner, params={"location_id": loc["id"]}).json()
    assert len(forecast["forecast_points"]) >= 24


def test_live_noaa_metar(http, planner):
    observations = []
    for loc in http.get("/locations", headers=planner).json():
        body = http.get("/weather/metar", headers=planner, params={"location_id": loc["id"]}).json()
        if body["observation"]:
            observations.append(body["observation"])
    assert observations, "no METAR station reported near any location"
    obs = observations[0]
    assert obs["station_id"] in obs["raw_metar"]


def test_optimiser_with_live_weather(http, planner, winter_lift):
    _, plan_id = winter_lift
    res = http.post(
        f"/schedules/{plan_id}/optimisation-runs",
        headers=planner, params={"include_weather": True},
        json={"schedule_id": plan_id, "solver_time_limit_seconds": 15, "include_weather": True},
    )
    assert res.status_code == 200, res.text
    run = res.json()
    assert run["solver_status"] in ("OPTIMAL", "FEASIBLE")

    check = http.post(f"/schedules/{run['new_schedule_version_id']}/validate", headers=planner).json()
    assert check["is_valid"] is True, check["conflicts"]


def test_courses_of_action_with_live_weather(http, planner, winter_lift):
    _, plan_id = winter_lift
    res = http.post(
        f"/schedules/{plan_id}/courses-of-action",
        headers=planner, json={"include_weather": True, "time_limit_seconds": 5},
    )
    assert res.status_code == 200, res.text
    courses = res.json()["courses"]
    assert [c["key"] for c in courses] == ["FASTEST", "STABLE", "SAFEST", "PRIORITY"]


@pytest.mark.skipif(
    settings.COPILOT_PROVIDER == "groq" and not settings.GROQ_API_KEY, reason="GROQ_API_KEY not set in backend/.env"
)
def test_copilot_answers_with_the_real_model(http, planner, winter_lift):
    scenario_id, _ = winter_lift
    status = http.get("/copilot/status", headers=planner).json()
    assert status["configured"] is True, status

    res = http.post(
        "/copilot/chat", headers=planner,
        json={"scenario_id": scenario_id, "message": "Which aircraft can fly task WL-07, and why?"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    # The model must have looked the task up rather than guessed
    assert any(s["tool"] == "explain_task" for s in body["steps"]), body["steps"]
    assert "C-130-Alpha" in body["reply"]
