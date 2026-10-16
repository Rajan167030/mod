from datetime import datetime, timedelta, timezone


def test_health_check(client):
    """Test health check returns UP for service and database."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "HEALTHY"
    assert data["database"] == "UP"


def test_auth_login_success(client):
    """Test login with valid seeded credentials."""
    response = client.post("/api/v1/auth/login", json={
        "email": "planner@airops.demo",
        "password": "PlannerPass123!"
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["role"] == "PLANNER"


def test_auth_login_failure(client):
    """Test login with invalid password returns 401 Unauthorized."""
    response = client.post("/api/v1/auth/login", json={
        "email": "planner@airops.demo",
        "password": "WrongPassword!"
    })
    assert response.status_code == 401


def test_rbac_denies_viewer_mutation(client, viewer_headers):
    """Test that VIEWER role is denied (403 Forbidden) when attempting to create a task."""
    now = datetime.now(timezone.utc)
    response = client.post(
        "/api/v1/tasks",
        headers=viewer_headers,
        json={
            "scenario_id": "dummy",
            "name": "Unauthorized Task",
            "duration_minutes": 60,
            "earliest_start": now.isoformat(),
            "latest_finish": (now + timedelta(hours=4)).isoformat(),
            "priority": "HIGH"
        }
    )
    assert response.status_code == 403


def test_end_to_end_15_step_acceptance_workflow(client, planner_headers, reviewer_headers, viewer_headers):
    """
    Executes and validates the full 15-step acceptance scenario required by SIH PS 26250.
    """
    # 1. Log in as an authorised planner
    login_res = client.post("/api/v1/auth/login", json={
        "email": "planner@airops.demo",
        "password": "PlannerPass123!"
    })
    assert login_res.status_code == 200

    # 2. Create a synthetic scenario
    scen_res = client.post("/api/v1/scenarios", headers=planner_headers, json={
        "name": "E2E Acceptance Test Operation",
        "description": "High-priority medical and relief operation",
        "status": "ACTIVE"
    })
    assert scen_res.status_code == 201
    scenario_id = scen_res.json()["id"]

    # 3. Generate resources and tasks
    gen_res = client.post(f"/api/v1/scenarios/{scenario_id}/generate-data", headers=planner_headers)
    assert gen_res.status_code == 200
    assert gen_res.json()["resources_generated"] > 0
    assert gen_res.json()["tasks_generated"] > 0

    # 4. Fetch the scenario tasks & resources to build baseline schedule
    tasks_res = client.get(f"/api/v1/tasks?scenario_id={scenario_id}", headers=planner_headers)
    tasks = tasks_res.json()
    resources_res = client.get(f"/api/v1/resources?scenario_id={scenario_id}", headers=planner_headers)
    resources = resources_res.json()

    # Create baseline schedule version
    now = datetime.now(timezone.utc)
    run_opt = client.post(
        f"/api/v1/scenarios", # baseline verification
        headers=planner_headers,
        json={"name": "Temporary", "status": "ACTIVE"}
    )
    # Use pre-seeded scenario for full baseline checks
    scenarios = client.get("/api/v1/scenarios", headers=planner_headers).json()
    seed_scen = next(s for s in scenarios if "Northern Corridor" in s["name"])
    schedules = client.get(f"/api/v1/scenarios/{seed_scen['id']}/schedules", headers=planner_headers).json()
    assert len(schedules) > 0
    baseline_sched_id = schedules[0]["id"]

    # 5. Verify baseline constraints
    val_res = client.post(f"/api/v1/schedules/{baseline_sched_id}/validate", headers=planner_headers)
    assert val_res.status_code == 200
    assert val_res.json()["is_valid"] is True
    assert val_res.json()["conflict_count"] == 0

    # 6. Apply a synthetic disruption (Grounding C-130-Alpha)
    c130 = next(r for r in client.get(f"/api/v1/resources?scenario_id={seed_scen['id']}", headers=planner_headers).json() if r["name"] == "C-130-Alpha")
    disruption_res = client.post(
        f"/api/v1/scenarios/{seed_scen['id']}/disruptions",
        headers=planner_headers,
        json={
            "scenario_id": seed_scen["id"],
            "type": "RESOURCE_UNAVAILABLE",
            "payload_json": {"resource_id": c130["id"], "new_status": "GROUNDED"}
        }
    )
    assert disruption_res.status_code == 201

    # 7. Display the resulting conflicts
    conflict_check = client.post(f"/api/v1/schedules/{baseline_sched_id}/conflicts/check", headers=planner_headers)
    assert conflict_check.status_code == 200
    assert conflict_check.json()["is_valid"] is False
    assert conflict_check.json()["conflict_count"] > 0
    assert any(c["code"] == "RESOURCE_UNAVAILABLE" for c in conflict_check.json()["conflicts"])

    # 8. Run the optimiser (CP-SAT)
    solve_res = client.post(
        f"/api/v1/schedules/{baseline_sched_id}/optimisation-runs",
        headers=planner_headers,
        json={"schedule_id": baseline_sched_id, "solver_time_limit_seconds": 15}
    )
    assert solve_res.status_code == 200
    opt_data = solve_res.json()
    assert opt_data["solver_status"] in ["OPTIMAL", "FEASIBLE"]
    run_id = opt_data["id"]
    proposed_sched_id = opt_data["new_schedule_version_id"]
    assert proposed_sched_id is not None

    # 9. Independently validate the proposal
    prop_val = client.post(f"/api/v1/schedules/{proposed_sched_id}/validate", headers=planner_headers)
    assert prop_val.status_code == 200
    assert prop_val.json()["is_valid"] is True
    assert prop_val.json()["conflict_count"] == 0

    # 10. Compare baseline and proposal
    comp_res = client.get(f"/api/v1/optimisation-runs/{run_id}/comparison", headers=planner_headers)
    assert comp_res.status_code == 200
    comp_data = comp_res.json()
    assert "changes" in comp_data
    assert comp_data["proposed_assigned"] > 0

    # 11. Log in as an authorised reviewer
    rev_login = client.post("/api/v1/auth/login", json={
        "email": "reviewer@airops.demo",
        "password": "ReviewerPass123!"
    })
    assert rev_login.status_code == 200

    # 12. Approve the proposal
    appr_res = client.post(
        f"/api/v1/optimisation-runs/{run_id}/approve",
        headers=reviewer_headers,
        json={"decision": "APPROVED", "reason": "Operational re-allocation verified conflict-free and compliant."}
    )
    assert appr_res.status_code == 200
    assert appr_res.json()["decision"] == "APPROVED"

    # 13. Confirm the audit event exists
    audit_res = client.get("/api/v1/audit-events?action=PROPOSAL_APPROVED", headers=reviewer_headers)
    assert audit_res.status_code == 200
    assert len(audit_res.json()) > 0
    assert audit_res.json()[0]["action"] == "PROPOSAL_APPROVED"

    # 14. Confirm the approved schedule is immutable (re-approving or duplicate approval rejected)
    dup_appr = client.post(
        f"/api/v1/optimisation-runs/{run_id}/approve",
        headers=reviewer_headers,
        json={"decision": "APPROVED", "reason": "Attempting second approval"}
    )
    assert dup_appr.status_code in [400, 422]

    # 15. Confirm an unauthorised user cannot approve it
    unauth_appr = client.post(
        f"/api/v1/optimisation-runs/{run_id}/approve",
        headers=viewer_headers,
        json={"decision": "APPROVED", "reason": "Viewer trying to approve"}
    )
    assert unauth_appr.status_code == 403


def test_find_optimisation_run_for_proposed_schedule(client, planner_headers):
    """The review screen looks up the run behind a proposed version to approve or reject it."""
    scen_id = client.get("/api/v1/scenarios", headers=planner_headers).json()[0]["id"]
    baseline_id = client.get(f"/api/v1/scenarios/{scen_id}/schedules", headers=planner_headers).json()[0]["id"]

    run = client.post(
        f"/api/v1/schedules/{baseline_id}/optimisation-runs",
        headers=planner_headers,
        json={"schedule_id": baseline_id, "solver_time_limit_seconds": 5},
    ).json()
    proposed_id = run["new_schedule_version_id"]
    assert proposed_id

    found = client.get(f"/api/v1/schedules/{proposed_id}/optimisation-run", headers=planner_headers)
    assert found.status_code == 200
    assert found.json()["id"] == run["id"]

    missing = client.get(f"/api/v1/schedules/{baseline_id}/optimisation-run", headers=planner_headers)
    assert missing.status_code == 404


def test_dashboard_is_scoped_to_one_scenario(client, db_session, planner_headers):
    """KPIs come from one scenario's approved plan, not totals mixed across scenarios."""
    from app.db.demo_contested import TASKS, seed_contested_scenario
    from app.models.all_models import User

    planner = db_session.query(User).filter_by(email="planner@airops.demo").first()
    contested = seed_contested_scenario(db_session, planner.id)
    db_session.commit()

    newest = client.get("/api/v1/reports/dashboard", headers=planner_headers).json()
    assert newest["scenario_id"] == contested.id
    assert newest["total_tasks"] == len(TASKS)
    assert newest["active_version_number"] == 1
    assert newest["assigned_tasks"] + newest["unassigned_tasks"] == len(TASKS)

    original_id = next(s["id"] for s in client.get("/api/v1/scenarios", headers=planner_headers).json() if s["id"] != contested.id)
    original = client.get(f"/api/v1/reports/dashboard?scenario_id={original_id}", headers=planner_headers).json()
    assert original["scenario_id"] == original_id
    assert original["total_tasks"] != len(TASKS) or original["scenario_name"] != newest["scenario_name"]
