"""
API Integration tests for /api/v1/locations endpoints.
Tests scenario scoping, CRUD, GeoJSON FeatureCollection format, and RBAC enforcement.
"""


def test_list_locations_requires_auth(client):
    res = client.get("/api/v1/locations")
    assert res.status_code == 401


def test_list_locations_success(client, viewer_headers):
    # Get scenarios first
    scen_res = client.get("/api/v1/scenarios", headers=viewer_headers)
    assert scen_res.status_code == 200
    scenarios = scen_res.json()
    assert len(scenarios) > 0
    scen_id = scenarios[0]["id"]

    res = client.get(f"/api/v1/locations?scenario_id={scen_id}", headers=viewer_headers)
    assert res.status_code == 200
    locations = res.json()
    assert isinstance(locations, list)
    assert len(locations) >= 6  # 6 seeded locations
    loc = locations[0]
    assert "name" in loc
    assert "latitude" in loc
    assert "longitude" in loc
    assert "location_type" in loc


def test_locations_geojson(client, viewer_headers):
    scen_res = client.get("/api/v1/scenarios", headers=viewer_headers)
    scen_id = scen_res.json()[0]["id"]

    res = client.get(f"/api/v1/locations/geojson?scenario_id={scen_id}", headers=viewer_headers)
    assert res.status_code == 200
    geojson = res.json()
    assert geojson["type"] == "FeatureCollection"
    assert "features" in geojson
    assert len(geojson["features"]) >= 6

    feat = geojson["features"][0]
    assert feat["type"] == "Feature"
    assert feat["geometry"]["type"] == "Point"
    assert len(feat["geometry"]["coordinates"]) == 2  # [lon, lat]
    assert "name" in feat["properties"]


def test_create_location_rbac(client, viewer_headers, planner_headers):
    scen_res = client.get("/api/v1/scenarios", headers=viewer_headers)
    scen_id = scen_res.json()[0]["id"]

    new_loc = {
        "scenario_id": scen_id,
        "name": "New Test Staging Point",
        "latitude": 33.45,
        "longitude": 75.12,
        "location_type": "WAYPOINT",
        "metadata_json": {"description": "Synthetic staging waypoint"},
    }

    # Viewer should be denied (403)
    viewer_res = client.post("/api/v1/locations", headers=viewer_headers, json=new_loc)
    assert viewer_res.status_code == 403

    # Planner should succeed (201)
    planner_res = client.post("/api/v1/locations", headers=planner_headers, json=new_loc)
    assert planner_res.status_code == 201
    created = planner_res.json()
    assert created["name"] == "New Test Staging Point"
    assert created["latitude"] == 33.45
