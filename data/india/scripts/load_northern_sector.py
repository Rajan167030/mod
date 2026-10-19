"""
Create the "Northern Sector (real airfields)" scenario in the AirOps database from the import files,
then produce an approved plan (planner optimises, reviewer approves).

Run from the backend folder:   python ../data/india/scripts/load_northern_sector.py [--replace]
It backs up the database first. If the scenario already exists it does nothing, unless --replace is
given, which deletes that scenario (and only that one) and builds it again from the current files.
"""
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BACKEND = Path.cwd()
PACK = Path(__file__).resolve().parents[1] / "import_northern_sector"
NAME = "Northern Sector (real airfields)"
ORDER = [("1_sites.csv", "sites"), ("2_aircraft.csv", "aircraft"), ("3_maintenance.csv", "maintenance"),
         ("4_crews.csv", "crews"), ("5_stores.csv", "stores"), ("6_tasks.csv", "tasks"),
         ("7_threats_and_airspace.csv", "threats")]

if not (BACKEND / "app" / "main.py").exists():
    sys.exit("Run this from the backend folder.")
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("WEATHER_PREFETCH_ON_STARTUP", "false")

# Back up the SQLite database (consistent copy, WAL included)
db_file = BACKEND / "scheduler.db"
if db_file.exists() and not os.environ.get("DATABASE_URL", "").startswith("postgres"):
    backups = BACKEND / "backups"
    backups.mkdir(exist_ok=True)
    target = backups / f"scheduler-{datetime.now():%Y%m%d-%H%M%S}.db"
    src, dst = sqlite3.connect(db_file), sqlite3.connect(target)
    src.backup(dst)
    dst.close()
    src.close()
    print("Backup:", target)

from fastapi.testclient import TestClient  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.all_models import Scenario, ScheduleVersion  # noqa: E402

with TestClient(app) as c:
    def login(email, password):
        r = c.post("/api/v1/auth/login", json={"email": email, "password": password})
        r.raise_for_status()
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    with SessionLocal() as db:
        existing = db.query(Scenario).filter(Scenario.name == NAME).all()
        if existing and "--replace" not in sys.argv:
            sys.exit(f"'{NAME}' already exists; nothing changed. Use --replace to rebuild it.")
        if existing:
            from app.services.scenario_admin import delete_scenario
            for sc in existing:
                delete_scenario(db, sc.id)
            db.commit()
            print(f"Removed the previous '{NAME}'.")

    planner = login("planner@airops.demo", "PlannerPass123!")
    reviewer = login("reviewer@airops.demo", "ReviewerPass123!")
    sid = c.post("/api/v1/scenarios", headers=planner, json={
        "name": NAME,
        "description": "Real Indian airfields (OurAirports) and airspace (AAI eAIP ENR 5.1) with live weather; "
                       "aircraft state, crews, stores, threats and missions are synthetic. See data/india/README.md.",
    }).json()["id"]

    for fname, kind in ORDER:
        data = (PACK / fname).read_bytes()
        pre = c.post(f"/api/v1/imports/{sid}/{kind}/preview", headers=planner, files={"file": (fname, data, "text/csv")}).json()
        if pre["summary"]["invalid"]:
            sys.exit(f"{fname}: {pre['summary']['invalid']} invalid rows, stopping. First: {[r for r in pre['rows'] if r['errors']][:1]}")
        r = c.post(f"/api/v1/imports/{sid}/{kind}/commit", headers=planner, files={"file": (fname, data, "text/csv")})
        r.raise_for_status()
        print(f"Imported {fname:28} created={r.json()['created']} updated={r.json()['updated']}")

    # Version 1 is the empty starting point; the optimiser proposes version 2 and a reviewer approves it
    with SessionLocal() as db:
        v1 = ScheduleVersion(scenario_id=sid, version_number=1, status="APPROVED")
        db.add(v1)
        db.commit()
        v1_id = v1.id
    run = c.post(f"/api/v1/schedules/{v1_id}/optimisation-runs?include_weather=true", headers=planner,
                 json={"schedule_id": v1_id, "solver_time_limit_seconds": 20, "include_weather": True}).json()
    print(f"Optimiser: {run['solver_status']}, assigned {run['metrics_json']['assigned_tasks']} of {run['metrics_json']['total_tasks']}, "
          f"validator {'pass' if run['validation']['is_valid'] else 'FAIL'}")
    if run["status"] != "COMPLETED" or not run["validation"]["is_valid"]:
        sys.exit("Plan not approved: the optimiser or validator did not pass. The scenario is still there to inspect.")
    r = c.post(f"/api/v1/optimisation-runs/{run['id']}/approve", headers=reviewer,
               json={"decision": "APPROVED", "reason": "Initial plan for the Northern Sector exercise; checked by the validator."})
    r.raise_for_status()
    print(f"Approved plan v2. Scenario '{NAME}' is ready.")
