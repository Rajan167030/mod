"""Planning copilot: read-only tools on real data, the tool loop for each provider with a stubbed client, and setup errors."""
import json
from types import SimpleNamespace

import anthropic
import pytest

from app.db.demo_contested import seed_contested_scenario
from app.models.all_models import ResourceAvailability, ScheduleVersion, User
from app.services import copilot_service


@pytest.fixture
def contested(db_session):
    planner = db_session.query(User).filter_by(email="planner@airops.demo").first()
    sc = seed_contested_scenario(db_session, planner.id)
    db_session.commit()
    return sc.id


@pytest.fixture
def use_anthropic(monkeypatch):
    monkeypatch.setattr(copilot_service.settings, "COPILOT_PROVIDER", "anthropic")


@pytest.fixture
def use_groq(monkeypatch):
    monkeypatch.setattr(copilot_service.settings, "COPILOT_PROVIDER", "groq")


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


# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------

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


def test_anthropic_chat_runs_the_tool_loop(client, contested, planner_headers, monkeypatch, use_anthropic):
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


def test_anthropic_missing_credentials_returns_clear_503(client, contested, planner_headers, monkeypatch, use_anthropic):
    def no_key():
        raise anthropic.AnthropicError("no api key")

    monkeypatch.setattr(copilot_service, "_client", None)
    monkeypatch.setattr(copilot_service.anthropic, "Anthropic", no_key)

    status = client.get("/api/v1/copilot/status", headers=planner_headers).json()
    assert status["configured"] is False and status["provider"] == "anthropic"
    res = client.post("/api/v1/copilot/chat", headers=planner_headers, json={"scenario_id": contested, "message": "hi"})
    assert res.status_code == 503
    assert "ANTHROPIC_API_KEY" in res.json()["message"]


def test_anthropic_client_without_credentials_is_not_configured(monkeypatch, use_anthropic):
    """The SDK builds a client with no key and only fails on the first request; status must not say ready."""
    monkeypatch.setattr(copilot_service, "_client", None)
    monkeypatch.setattr(copilot_service.anthropic, "Anthropic", lambda: SimpleNamespace(api_key=None, auth_token=None))
    assert copilot_service.is_configured() is False


# ---------------------------------------------------------------------------
# Groq provider
# ---------------------------------------------------------------------------

class _FakeGroqCompletions:
    """Scripted Groq model: calls explain_task, then answers from its result."""

    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            call = SimpleNamespace(id="call_1", function=SimpleNamespace(name="explain_task", arguments=json.dumps({"task": "WL-07"})))
            msg = SimpleNamespace(content=None, tool_calls=[call])
            return SimpleNamespace(model=kwargs["model"], choices=[SimpleNamespace(message=msg, finish_reason="tool_calls")])
        tool_msg = kwargs["messages"][-1]
        assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "call_1"
        assert "NIGHT_OPS" in tool_msg["content"]
        msg = SimpleNamespace(content="Only C-130-Alpha holds the night qualification.", tool_calls=None)
        return SimpleNamespace(model=kwargs["model"], choices=[SimpleNamespace(message=msg, finish_reason="stop")])


def test_groq_chat_runs_the_tool_loop(client, contested, planner_headers, monkeypatch, use_groq):
    fake = SimpleNamespace(chat=SimpleNamespace(completions=_FakeGroqCompletions()))
    monkeypatch.setattr(copilot_service, "_groq_client", fake)

    status = client.get("/api/v1/copilot/status", headers=planner_headers).json()
    assert status == {"configured": True, "provider": "groq", "model": "openai/gpt-oss-120b"}

    res = client.post("/api/v1/copilot/chat", headers=planner_headers, json={"scenario_id": contested, "message": "Why WL-07?"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["reply"].startswith("Only C-130-Alpha")
    assert [s["tool"] for s in body["steps"]] == ["explain_task"]

    first = fake.chat.completions.calls[0]
    assert first["messages"][0]["role"] == "system"
    assert first["tool_choice"] == "auto"
    assert {t["function"]["name"] for t in first["tools"]} == set(copilot_service.HANDLERS)
    conv = copilot_service._conversations[body["conversation_id"]]
    assert [m["role"] for m in conv.messages] == ["system", "user", "assistant", "tool", "assistant"]


def test_groq_without_key_returns_clear_503(client, contested, planner_headers, monkeypatch, use_groq):
    monkeypatch.setattr(copilot_service, "_groq_client", None)
    monkeypatch.setattr(copilot_service.settings, "GROQ_API_KEY", "")
    assert client.get("/api/v1/copilot/status", headers=planner_headers).json()["configured"] is False
    res = client.post("/api/v1/copilot/chat", headers=planner_headers, json={"scenario_id": contested, "message": "hi"})
    assert res.status_code == 503
    assert "GROQ_API_KEY" in res.json()["message"]
