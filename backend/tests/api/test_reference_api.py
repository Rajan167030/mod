"""Reference data for the theatre map, and the service-ceiling rule fed by the aircraft type specs."""
import httpx
import pytest

from app.db.demo_contested import seed_contested_scenario
from app.models.all_models import Assignment, Resource, ScheduleVersion, Task, User
from app.models.weather_models import Location
from app.services import reference_service
from app.services.conflict_service import check_schedule_conflicts
from tests.conftest import AWC_PATTERN


@pytest.fixture(autouse=True)
def fresh_metar_cache():
    reference_service._metar_cache.clear()
    yield
    reference_service._metar_cache.clear()


def test_airfields_airspace_and_types(client, planner_headers):
    fields = client.get("/api/v1/reference/airfields", headers=planner_headers).json()["airfields"]
    leh = next(a for a in fields if a["icao"] == "VILH")
    assert len(fields) > 600 and leh["elevation_m"] > 3000

    areas = client.get("/api/v1/reference/airspace", headers=planner_headers).json()["areas"]
    assert len(areas) > 100 and any(a["designator"] == "VIP 89" and a["type"] == "Prohibited" for a in areas)
    assert all(a["polygon"] or (a["center"] and a["radius_km"]) for a in areas)

    types = {t["type_name"]: t for t in client.get("/api/v1/reference/aircraft-types", headers=planner_headers).json()["types"]}
    assert types["Mi-17V5"]["service_ceiling_m"] == 6000


def test_metar_live_then_snapshot_fallback(client, planner_headers, mock_weather_providers):
    live = client.get("/api/v1/reference/metar", headers=planner_headers).json()
    assert live["source"] == "live" and any(s["icao"] == "VILH" for s in live["stations"])

    reference_service._metar_cache.clear()
    mock_weather_providers.get(url__regex=AWC_PATTERN).mock(return_value=httpx.Response(503))
    fallback = client.get("/api/v1/reference/metar", headers=planner_headers).json()
    assert fallback["source"] == "snapshot" and len(fallback["stations"]) > 50


def test_site_above_service_ceiling_is_ruled_out(client, db_session, planner_headers):
    planner = db_session.query(User).filter_by(email="planner@airops.demo").first()
    sid = seed_contested_scenario(db_session, planner.id).id
    db_session.commit()
    v = db_session.query(ScheduleVersion).filter_by(scenario_id=sid, status="APPROVED").one()
    a = db_session.query(Assignment).filter_by(schedule_version_id=v.id).first()
    heli = db_session.get(Resource, a.resource_id)
    site = db_session.get(Location, db_session.get(Task, a.task_id).location_id)

    # Give the aircraft a published ceiling below the site
    heli.metadata_json = {**heli.metadata_json, "service_ceiling_m": 2000}
    site.metadata_json = {**(site.metadata_json or {}), "elevation_m": 4500}
    db_session.commit()
    assert "ABOVE_SERVICE_CEILING" in {c.code for c in check_schedule_conflicts(db_session, v.id).conflicts}

    run = client.post(f"/api/v1/schedules/{v.id}/optimisation-runs", headers=planner_headers,
                      json={"schedule_id": v.id, "solver_time_limit_seconds": 6}).json()
    assert run["validation"]["is_valid"] and run["metrics_json"]["operational_layers"]["pairs_above_ceiling"] > 0
    tasks_at_site = {t.id for t in db_session.query(Task).filter_by(location_id=site.id)}
    new = db_session.query(Assignment).filter_by(schedule_version_id=run["new_schedule_version_id"]).all()
    assert not any(x.resource_id == heli.id and x.task_id in tasks_at_site for x in new)
