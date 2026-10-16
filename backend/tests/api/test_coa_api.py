"""Courses of Action: alternative plans generated without side effects, one adopted as a proposal."""


def _baseline(client, headers):
    scen_id = client.get("/api/v1/scenarios", headers=headers).json()[0]["id"]
    versions = client.get(f"/api/v1/scenarios/{scen_id}/schedules", headers=headers).json()
    return scen_id, versions[0]["id"]


def test_generate_three_courses_without_writing_versions(client, planner_headers):
    scen_id, baseline_id = _baseline(client, planner_headers)
    before = len(client.get(f"/api/v1/scenarios/{scen_id}/schedules", headers=planner_headers).json())

    res = client.post(
        f"/api/v1/schedules/{baseline_id}/courses-of-action",
        headers=planner_headers,
        json={"include_weather": True, "time_limit_seconds": 3},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert [c["key"] for c in body["courses"]] == ["FASTEST", "STABLE", "SAFEST", "PRIORITY"]
    for c in body["courses"]:
        assert c["solver_status"] in ("OPTIMAL", "FEASIBLE")
        assert c["metrics"]["validator_pass"] is True
        assert len(c["tasks"]) == c["metrics"]["assigned"] + c["metrics"]["unassigned"]
    assert sum(c["recommended"] for c in body["courses"]) == 1
    assert body["recommendation_reason"]

    # Generating plans must not create schedule versions (the validator ran inside a savepoint)
    after = len(client.get(f"/api/v1/scenarios/{scen_id}/schedules", headers=planner_headers).json())
    assert after == before


def test_adopt_creates_reviewable_proposal(client, planner_headers, reviewer_headers):
    _, baseline_id = _baseline(client, planner_headers)
    coa = client.post(
        f"/api/v1/schedules/{baseline_id}/courses-of-action",
        headers=planner_headers,
        json={"include_weather": False, "time_limit_seconds": 3},
    ).json()

    adopted = client.post(f"/api/v1/courses-of-action/{coa['coa_set_id']}/STABLE/adopt", headers=planner_headers)
    assert adopted.status_code == 200, adopted.text
    proposed_id = adopted.json()["proposed_version_id"]

    version = client.get(f"/api/v1/schedules/{proposed_id}", headers=planner_headers).json()
    assert version["status"] == "PROPOSED"

    # The review screen can find the run and a reviewer can approve it
    run = client.get(f"/api/v1/schedules/{proposed_id}/optimisation-run", headers=reviewer_headers).json()
    assert run["id"] == adopted.json()["run_id"]
    approve = client.post(
        f"/api/v1/optimisation-runs/{run['id']}/approve",
        headers=reviewer_headers,
        json={"decision": "APPROVED", "reason": "Least-disruption plan accepted for the night shift."},
    )
    assert approve.status_code == 200, approve.text


def test_viewer_cannot_generate_courses(client, viewer_headers):
    _, baseline_id = _baseline(client, viewer_headers)
    res = client.post(
        f"/api/v1/schedules/{baseline_id}/courses-of-action",
        headers=viewer_headers,
        json={"include_weather": False, "time_limit_seconds": 2},
    )
    assert res.status_code == 403


def test_unknown_set_returns_404(client, planner_headers):
    res = client.post("/api/v1/courses-of-action/does-not-exist/STABLE/adopt", headers=planner_headers)
    assert res.status_code == 404
