from types import SimpleNamespace

from app.services.agent.model_parameters import normalize_model_parameters


def test_model_parameters_drop_protected_completion_fields() -> None:
    assert normalize_model_parameters(
        {
            "temperature": 0.1,
            "reasoning_effort": "none",
            "model": "wrong-model",
            "messages": [{"role": "user", "content": "override"}],
            "api_key": "secret",
        }
    ) == {
        "temperature": 0.1,
        "reasoning_effort": "none",
    }


def test_call_llm_does_not_send_temperature_by_default(monkeypatch) -> None:
    from app.services.agent import session as session_module
    from app.services.agent.session import AgentSession

    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(session_module, "completion", fake_completion)
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            model="openai/gpt-5-codex",
            api_key=None,
            api_url=None,
            model_parameters={},
        ),
        get_tools_for_litellm=lambda: [],
    )

    result = AgentSession("item-1", "handler-1")._call_llm(
        agent,
        [{"role": "user", "content": "hello"}],
    )

    assert result == "ok"
    assert captured["model"] == "openai/gpt-5-codex"
    assert "temperature" not in captured


def test_call_llm_uses_handler_model_parameters(monkeypatch) -> None:
    from app.services.agent import session as session_module
    from app.services.agent.session import AgentSession

    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(session_module, "completion", fake_completion)
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            model="deepseek/deepseek-chat",
            api_key="key",
            api_url="https://api.deepseek.com",
            model_parameters={"temperature": 0.1},
        ),
        get_tools_for_litellm=lambda: [],
    )

    AgentSession("item-2", "handler-2")._call_llm(
        agent,
        [{"role": "user", "content": "hello"}],
    )

    assert captured["temperature"] == 0.1
    assert captured["api_key"] == "key"
    assert captured["api_base"] == "https://api.deepseek.com"
