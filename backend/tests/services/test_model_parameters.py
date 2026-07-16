from types import SimpleNamespace

import litellm

from app.services.agent.model_parameters import (
    normalize_model_parameters,
    normalize_model_parameters_for_model,
)
from app.services.llm_completion import build_litellm_completion_kwargs


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


def test_gpt5_model_parameters_drop_incompatible_sampling_values() -> None:
    assert normalize_model_parameters_for_model(
        "openai/gpt-5.6-luna",
        {
            "temperature": 0.1,
            "top_p": 0.8,
            "reasoning_effort": "high",
        },
    ) == {"reasoning_effort": "high"}


def test_gpt5_model_parameters_keep_supported_default_sampling_values() -> None:
    assert normalize_model_parameters_for_model(
        "gpt-5.2",
        {"temperature": 1, "top_p": 1},
    ) == {"temperature": 1, "top_p": 1}


def test_shared_completion_builder_drops_gpt5_sampling_defaults() -> None:
    kwargs = build_litellm_completion_kwargs(
        model="openai/gpt-5.6-luna",
        messages=[{"role": "user", "content": "你好"}],
        default_parameters={"temperature": 0.1, "top_p": 0.8},
    )

    assert "temperature" not in kwargs
    assert "top_p" not in kwargs


def test_shared_completion_builder_keeps_deepseek_sampling_defaults() -> None:
    kwargs = build_litellm_completion_kwargs(
        model="deepseek/deepseek-chat",
        messages=[{"role": "user", "content": "你好"}],
        default_parameters={"temperature": 0.1},
    )

    assert kwargs["temperature"] == 0.1


def test_shared_completion_builder_keeps_tools_without_explicit_tool_choice() -> None:
    tools = [
        {
            "type": "function",
            "function": {"name": "test_tool", "parameters": {"type": "object"}},
        }
    ]

    kwargs = build_litellm_completion_kwargs(
        model="openai/gpt-5.3-codex-spark",
        messages=[{"role": "user", "content": "你好"}],
        tools=tools,
    )

    assert kwargs["tools"] == tools
    assert "tool_choice" not in kwargs
    assert litellm.drop_params is True
    assert litellm.suppress_debug_info is True


def test_web_chat_completion_builder_drops_gpt5_temperature() -> None:
    from app.api.routes.chat import _build_completion_kwargs

    kwargs = _build_completion_kwargs(
        SimpleNamespace(
            model="openai/gpt-5.6-luna",
            api_key="key",
            api_url="https://example.com/v1",
            model_parameters={"temperature": 0.1},
        ),
        messages=[{"role": "user", "content": "你好"}],
        tools=[],
        stream=True,
    )

    assert "temperature" not in kwargs
    assert kwargs["api_key"] == "key"
    assert kwargs["api_base"] == "https://example.com/v1"


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


def test_call_llm_drops_stale_temperature_for_gpt5_model(monkeypatch) -> None:
    from app.services.agent import session as session_module
    from app.services.agent.session import AgentSession

    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(session_module, "completion", fake_completion)
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            model="openai/gpt-5.6-luna",
            api_key=None,
            api_url=None,
            model_parameters={"temperature": 0.1},
        ),
        get_tools_for_litellm=lambda: [],
    )

    AgentSession("item-gpt5", "handler-gpt5")._call_llm(
        agent,
        [{"role": "user", "content": "hello"}],
    )

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
