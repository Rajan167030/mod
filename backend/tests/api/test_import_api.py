"""Data import: header aliasing, row validation, preview without side effects, commit, Excel."""
import io

import pytest
from openpyxl import Workbook

from app.db.demo_contested import seed_contested_scenario
from app.models.all_models import AuditEvent, Resource, ResourceAvailability, Task, User


@pytest.fixture
def contested(db_session):
    planner = db_session.query(User).filter_by(email="planner@airops.demo").first()
    sc = seed_contested_scenario(db_session, planner.id)
    db_session.commit()
    return sc.id


def _post(client, headers, scenario_id, kind, step, name, content: bytes):
    return client.post(
        f"/api/v1/imports/{scenario_id}/{kind}/{step}",
        headers=headers,
        files={"file": (name, content, "application/octet-stream")},
    )


TASKS_CSV = "\n".join([
    "Mission,Prio,Duration,Window Opens,Deadline,Requires,Destination,Notes",
    "WL-40 Bridge parts,HIGH,150,2026-10-17T06:00Z,2026-10-17T14:00Z,HEAVY_AIRLIFT,Delta Valley LZ,x",
    "WL-41 Bad row,URGENT,abc,2026-10-17T06:00Z,2026-10-17T05:00Z,HEAVY_AIRLIFT,Nowhere,y",
]).encode()


def test_preview_maps_headers_and_flags_errors_without_writing(client, db_session, contested, planner_headers):
    before = db_session.query(Task).filter_by(scenario_id=contested).count()
    res = _post(client, planner_headers, contested, "tasks", "preview", "tasks.csv", TASKS_CSV)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["columns"]["name"] == "Mission" and body["columns"]["latest_finish"] == "Deadline"
    assert body["unused_columns"] == ["Notes"]
    assert body["summary"] == {"total": 2, "valid": 1, "invalid": 1, "create": 1, "update": 0}
    bad = body["rows"][1]["errors"]
    assert any("priority" in e for e in bad) and any("site" in e for e in bad)
    assert db_session.query(Task).filter_by(scenario_id=contested).count() == before

    # Commit refuses while errors remain
    assert _post(client, planner_headers, contested, "tasks", "commit", "tasks.csv", TASKS_CSV).status_code == 422


def test_commit_creates_and_updates(client, db_session, contested, planner_headers):
    good = "\n".join([
        "name,priority,duration_minutes,earliest_start,latest_finish,qualification,site",
        "WL-40 Bridge parts,HIGH,150,2026-10-17T06:00Z,2026-10-17T14:00Z,HEAVY_AIRLIFT,Delta Valley LZ",
        "WL-01 Medical stores to Alpha FOB,CRITICAL,180,2026-10-16T07:00Z,2026-10-16T13:00Z,HEAVY_AIRLIFT,Alpha FOB",
    ]).encode()
    res = _post(client, planner_headers, contested, "tasks", "commit", "t.csv", good)
    assert res.status_code == 200, res.text
    assert res.json() == {"kind": "tasks", "created": 1, "updated": 1, "rows": 2}
    new = db_session.query(Task).filter_by(scenario_id=contested, name="WL-40 Bridge parts").one()
    assert new.location_id and [r.requirement_value for r in new.requirements] == ["HEAVY_AIRLIFT"]
    updated = db_session.query(Task).filter_by(scenario_id=contested, name="WL-01 Medical stores to Alpha FOB").one()
    assert updated.duration_minutes == 180
    assert db_session.query(AuditEvent).filter_by(action="DATA_IMPORTED").count() == 1


def test_excel_aircraft_and_maintenance(client, db_session, contested, planner_headers):
    wb = Workbook()
    ws = wb.active
    ws.append(["Callsign", "Aircraft Type", "Capabilities", "Payload kg", "Status"])
    ws.append(["C-17-Delta", "HEAVY_AIRCRAFT", "HEAVY_AIRLIFT; NIGHT_OPS", 70000, "AVAILABLE"])
    buf = io.BytesIO()
    wb.save(buf)
    res = _post(client, planner_headers, contested, "aircraft", "commit", "fleet.xlsx", buf.getvalue())
    assert res.status_code == 200, res.text
    c17 = db_session.query(Resource).filter_by(scenario_id=contested, name="C-17-Delta").one()
    assert c17.metadata_json["qualifications"] == ["HEAVY_AIRLIFT", "NIGHT_OPS"]

    mx = "aircraft,start,end\nC-17-Delta,2026-10-17T02:00Z,2026-10-17T06:00Z\n".encode()
    assert _post(client, planner_headers, contested, "maintenance", "commit", "mx.csv", mx).status_code == 200
    assert db_session.query(ResourceAvailability).filter_by(resource_id=c17.id, available=False).count() == 1


def test_viewer_cannot_import_and_template_downloads(client, contested, viewer_headers):
    assert _post(client, viewer_headers, contested, "sites", "preview", "s.csv", b"name\n").status_code == 403
    t = client.get("/api/v1/imports/templates/tasks")
    assert t.status_code == 200 and t.text.startswith("name,priority")
