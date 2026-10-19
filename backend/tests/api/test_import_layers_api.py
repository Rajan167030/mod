"""Importing crews, stores and threats, plus store columns on aircraft and tasks."""
import pytest

from app.db.demo_contested import seed_contested_scenario
from app.models.all_models import Resource, Task, User
from app.models.ops_models import Crew, OpsZone, StoreItem
from app.models.weather_models import Location


@pytest.fixture
def contested(db_session):
    planner = db_session.query(User).filter_by(email="planner@airops.demo").first()
    sc = seed_contested_scenario(db_session, planner.id)
    db_session.commit()
    return sc.id


def _post(client, headers, scenario_id, kind, step, text):
    return client.post(f"/api/v1/imports/{scenario_id}/{kind}/{step}", headers=headers,
                       files={"file": (f"{kind}.csv", text.encode(), "text/csv")})


@pytest.mark.parametrize("kind", ["crews", "stores", "threats"])
def test_templates_import_cleanly(client, db_session, contested, planner_headers, kind):
    template = client.get(f"/api/v1/imports/templates/{kind}", headers=planner_headers).text
    preview = _post(client, planner_headers, contested, kind, "preview", template).json()
    assert preview["summary"]["invalid"] == 0, preview["rows"]
    res = _post(client, planner_headers, contested, kind, "commit", template)
    assert res.status_code == 200, res.text
    assert res.json()["created"] + res.json()["updated"] == preview["summary"]["total"]


def test_crews_import_with_loose_headers(client, db_session, contested, planner_headers):
    text = "Crew Name,Current On,Duty Limit,Rest,Status\nSpare heavy crew,HEAVY_AIRCRAFT,420,60,available\nHercules crew 1,HEAVY_AIRCRAFT,300,90,UNFIT\n"
    preview = _post(client, planner_headers, contested, "crews", "preview", text).json()
    assert preview["summary"] == {"total": 2, "valid": 2, "invalid": 0, "create": 1, "update": 1}
    _post(client, planner_headers, contested, "crews", "commit", text)
    db_session.expire_all()
    updated = db_session.query(Crew).filter_by(scenario_id=contested, name="Hercules crew 1").one()
    assert (updated.status, updated.max_duty_minutes, updated.min_rest_minutes) == ("UNFIT", 300, 90)


def test_bad_rows_are_reported_not_saved(client, db_session, contested, planner_headers):
    text = (
        "name,kind,latitude,longitude,radius_km,active_from,active_until,confidence\n"
        "Laser nest,LASER,34,77,10,,,50\n"
        "Backwards,SAM,34,77,10,2026-10-20T12:00Z,2026-10-20T10:00Z,50\n"
        "Too far,SAM,95,77,10,,,50\n"
    )
    preview = _post(client, planner_headers, contested, "threats", "preview", text).json()
    assert preview["summary"]["invalid"] == 3
    assert _post(client, planner_headers, contested, "threats", "commit", text).status_code == 422
    db_session.expire_all()
    assert db_session.query(OpsZone).filter_by(scenario_id=contested).count() == 3


def test_polygon_airspace_imports(client, db_session, contested, planner_headers):
    text = ('name,kind,effect,polygon,source,confidence\n'
            'VIR 999 Test box,RESTRICTED,AVOID,"34.0 77.0; 34.0 77.3; 33.8 77.3; 33.8 77.0",AAI eAIP ENR 5.1,100\n'
            'Bad box,RESTRICTED,BLOCK,"34.0 77.0; 34.1 77.1",NOTAM,100\n')
    preview = _post(client, planner_headers, contested, "threats", "preview", text).json()
    assert [bool(r["errors"]) for r in preview["rows"]] == [False, True]
    good = text.rsplit("\n", 2)[0] + "\n"
    assert _post(client, planner_headers, contested, "threats", "commit", good).status_code == 200
    db_session.expire_all()
    z = db_session.query(OpsZone).filter_by(scenario_id=contested, name="VIR 999 Test box").one()
    assert len(z.polygon_json) == 4 and z.center_lat is None and z.effect == "AVOID"


def test_imported_threat_moves_the_plan(client, db_session, contested, planner_headers):
    foxtrot = db_session.query(Location).filter_by(scenario_id=contested, name="Foxtrot Medevac Point").one()
    text = f"name,kind,effect,latitude,longitude,radius_km,source,confidence\nAAA belt Foxtrot,AAA,BLOCK,{foxtrot.latitude},{foxtrot.longitude},10,IMINT,90\n"
    assert _post(client, planner_headers, contested, "threats", "commit", text).status_code == 200

    from app.models.all_models import ScheduleVersion, Assignment
    v = db_session.query(ScheduleVersion).filter_by(scenario_id=contested, status="APPROVED").one()
    run = client.post(f"/api/v1/schedules/{v.id}/optimisation-runs", headers=planner_headers,
                      json={"schedule_id": v.id, "solver_time_limit_seconds": 6}).json()
    assert run["validation"]["is_valid"]
    tasks = {t.id: t for t in db_session.query(Task).filter_by(scenario_id=contested)}
    new = db_session.query(Assignment).filter_by(schedule_version_id=run["new_schedule_version_id"]).all()
    assert not any(tasks[a.task_id].location_id == foxtrot.id for a in new)


def test_stores_columns_on_aircraft_and_tasks(client, db_session, contested, planner_headers):
    stores = "store_type,name,category,quantity,unit\nSMOKE_POT,Coloured smoke,mission kit,4,each\n"
    assert _post(client, planner_headers, contested, "stores", "commit", stores).status_code == 200
    aircraft = "name,type,qualifications,status,store_types\nALH-Dhruv-02,LIGHT_HELICOPTER,FORWARD_RECON;QUICK_MEDEVAC,AVAILABLE,FLARE_SET;SMOKE_POT\n"
    assert _post(client, planner_headers, contested, "aircraft", "commit", aircraft).status_code == 200
    tasks = ("name,priority,duration_minutes,earliest_start,latest_finish,qualification,site,stores\n"
             "WL-50 Marked drop,HIGH,60,2026-10-20T06:00Z,2026-10-20T12:00Z,FORWARD_RECON,Delta Valley LZ,SMOKE_POT:2\n")
    preview = _post(client, planner_headers, contested, "tasks", "preview", tasks).json()
    assert preview["summary"]["invalid"] == 0 and preview["rows"][0]["values"]["stores"] == ["SMOKE_POT:2"]
    assert _post(client, planner_headers, contested, "tasks", "commit", tasks).status_code == 200

    db_session.expire_all()
    heli = db_session.query(Resource).filter_by(scenario_id=contested, name="ALH-Dhruv-02").one()
    assert "SMOKE_POT" in heli.metadata_json["store_types"]
    task = db_session.query(Task).filter_by(scenario_id=contested, name="WL-50 Marked drop").one()
    assert {(r.requirement_type, r.requirement_value) for r in task.requirements} >= {("STORE", "SMOKE_POT:2")}
    assert db_session.query(StoreItem).filter_by(scenario_id=contested, store_type="SMOKE_POT").one().category == "MISSION_KIT"


def test_unknown_store_warns(client, contested, planner_headers):
    tasks = ("name,priority,duration_minutes,earliest_start,latest_finish,stores\n"
             "WL-51 Odd load,LOW,60,2026-10-20T06:00Z,2026-10-20T12:00Z,MYSTERY_BOX\n")
    preview = _post(client, planner_headers, contested, "tasks", "preview", tasks).json()
    assert any("MYSTERY_BOX" in w for w in preview["warnings"])
