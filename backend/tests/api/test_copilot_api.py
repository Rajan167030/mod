"""Planning copilot: read-only tools on real data, the tool loop with a stubbed Claude client, and setup errors."""
from types import SimpleNamespace

import anthropic
import pytest

from app.db.demo_contested import seed_contested_scenario
from app.models.all_models import ResourceAvailability, Scenario, ScheduleVersion, User
from app.services import copilot_service


@pytest.fixture
def contested(db_session):
    planner = db_session.query(User).filter_by(email="planner@airops.demo").first()
    sc = seed_contested_scenario(db_session, planner.id)
    db_session.commit()
    return sc.id


def test_tools_answer_from_scenario_data(db_session, contested):
    situation = copilot_service.tool_get_situation(db_session, contested, {})
    assert situation["active_plan_version"] == 1
    assert {a["name"] for a in situation["aircraft"]} >= {"C-130-Alpha", "IL-76-Heavy"}

    explained = copilot_service.tool_explain_task(db_session, contested, {"task": "WL-07"})
    assert explained["requires"] == ["NIGHT_OPS"]
    # Only C-130-Alpha holds the night qualification
    assert [c["aircraft"] for c in explained["qualified_aircraft"]] == ["C-130-Alpha"]

    tasks = copilot_service.tool_list_tasks(db_session, contested, {"priority": "CRITICAL"})["tasks"]
    assert tasks and all(t["priority"] == "CRITICAL" for t in tasks)


def test_what_if_changes_nothing(db_session, contested):
    blackouts_before = db_session.query(ResourceAvailability).filter_by(available=False).count()
    versions_before = db_session.query(ScheduleVersion).count()

    result = copilot_service.tool_what_if_unavailable(
        db_session, contested, {"aircraft": "c-130-alpha", "hours": 8, "starts_in_hours": None}
    )
    assert "not saved" in result["simulated"]
    assert len(result["plans"]) >= 3
    assert db_session.query(ResourceAvailability).filter_by(available=False).count() == blackouts_before
    assert db_session.query(ScheduleVersion).count() == versions_before


class _FakeMessages:
    """Scripted Claude: first asks for get_situation, then answers using its result."""

    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return SimpleNamespace(
                stop_reason="tool_use", model=kwargs["model"],
                content=[SimpleNamespace(type="tool_use", id="tu_1", name="get_situation", input={})],
            )
        result = kwargs["messages"][-1]["content"][0]
        assert result["type"] == "tool_result" and result["tool_use_id"] == "tu_1" and not result["is_error"]
        return SimpleNamespace(
            stop_reason="end_turn", model=kwargs["model"],
            content=[SimpleNamespace(type="text", text="Plan v1 is in force with no conflicts.")],
        )


def test_chat_runs_the_tool_loop(client, contested, planner_headers, monkeypatch):
    fake = SimpleNamespace(beta=SimpleNamespace(messages=_FakeMessages()))
    monkeypatch.setattr(copilot_service, "_client", fake)

    res = client.post(
        "/api/v1/copilot/chat", headers=planner_headers,
        json={"scenario_id": contested, "message": "What is the situation?"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["reply"] == "Plan v1 is in force with no conflicts."
    assert [s["tool"] for s in body["steps"]] == ["get_situation"]

    first = fake.beta.messages.calls[0]
    assert first["model"] == "claude-opus-5-5"
    assert first["thinking"] == {"type": "adaptive"}
    assert first["extra_body"] == {"fallbacks": "default"}
    assert all(t["strict"] for t in first["tools"])

    # The conversation continues server-side, append-only
    conv = copilot_service._conversations[body["conversation_id"]]
    assert [m["role"] for m in conv.messages] == ["user", "assistant", "user", "assistant"]


def test_missing_credentials_returns_clear_503(client, contested, planner_headers, monkeypatch):
    def no_key():
        raise anthropic.AnthropicError("no api key")

    monkeypatch.setattr(copilot_service, "_client", None)
    monkeypatch.setattr(copilot_service.anthropic, "Anthropic", no_key)

    status = client.get("/api/v1/copilot/status", headers=planner_headers).json()
    assert status["configured"] is False
    res = client.post("/api/v1/copilot/chat", headers=planner_headers, json={"scenario_id": contested, "message": "hi"})
    assert res.status_code == 503
    assert "ANTHROPIC_API_KEY" in res.json()["message"]


def test_client_without_credentials_is_not_configured(monkeypatch):
    """The SDK builds a client with no key and only fails on the first request; status must not say ready."""
    monkeypatch.setattr(copilot_service, "_client", None)
    monkeypatch.setattr(copilot_service.anthropic, "Anthropic", lambda: SimpleNamespace(api_key=None, auth_token=None))
    assert copilot_service.is_configured() is False
