"""
API Integration tests for /api/v1/weather endpoints.
Tests /weather/current, /weather/forecast, /weather/alerts, and /weather/refresh.
"""


def test_weather_endpoints_require_auth(client):
    assert client.get("/api/v1/weather/current?location_id=dummy").status_code == 401
    assert client.get("/api/v1/weather/forecast?location_id=dummy").status_code == 401
    assert client.get("/api/v1/weather/alerts?scenario_id=dummy").status_code == 401
    assert client.post("/api/v1/weather/refresh", json={}).status_code == 401


def test_weather_alerts_endpoint(client, viewer_headers):
    scen_res = client.get("/api/v1/scenarios", headers=viewer_headers)
    scen_id = scen_res.json()[0]["id"]

    res = client.get(f"/api/v1/weather/alerts?scenario_id={scen_id}", headers=viewer_headers)
    assert res.status_code == 200
    data = res.json()
    assert "scenario_id" in data
    assert "alerts" in data
    assert "freshness_summary" in data
    assert "thresholds_used" in data


def test_weather_forecast_and_current(client, viewer_headers):
    scen_res = client.get("/api/v1/scenarios", headers=viewer_headers)
    scen_id = scen_res.json()[0]["id"]
    loc_res = client.get(f"/api/v1/locations?scenario_id={scen_id}", headers=viewer_headers)
    location_id = loc_res.json()[0]["id"]

    # Forecast endpoint
    fc_res = client.get(f"/api/v1/weather/forecast?location_id={location_id}", headers=viewer_headers)
    assert fc_res.status_code == 200
    forecast = fc_res.json()
    assert forecast["location_id"] == location_id
    assert "forecast_points" in forecast
    assert len(forecast["forecast_points"]) > 0

    # Current endpoint
    curr_res = client.get(f"/api/v1/weather/current?location_id={location_id}", headers=viewer_headers)
    assert curr_res.status_code == 200
    curr = curr_res.json()
    assert curr["location_id"] == location_id
    assert "data" in curr
    assert "freshness" in curr


def test_weather_refresh_rbac(client, viewer_headers, planner_headers):
    scen_res = client.get("/api/v1/scenarios", headers=viewer_headers)
    scen_id = scen_res.json()[0]["id"]

    # Viewer should be denied (403)
    v_res = client.post(
        "/api/v1/weather/refresh",
        headers=viewer_headers,
        json={"scenario_id": scen_id}
    )
    assert v_res.status_code == 403

    # Planner should be accepted (200)
    p_res = client.post(
        "/api/v1/weather/refresh",
        headers=planner_headers,
        json={"scenario_id": scen_id}
    )
    assert p_res.status_code == 200
    data = p_res.json()
    assert data["success"] is True
    assert "refreshed_locations" in data
