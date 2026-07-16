from __future__ import annotations

from typing import Any

import litellm

from app.services.agent.model_parameters import normalize_model_parameters_for_model

litellm.drop_params = True
litellm.suppress_debug_info = True


def build_litellm_completion_kwargs(
    *,
    model: str | None,
    messages: list[dict[str, Any]],
    api_key: str | None = None,
    api_base: str | None = None,
    timeout: float | int | None = None,
    stream: bool | None = None,
    tools: list[dict[str, Any]] | None = None,
    model_parameters: dict[str, Any] | None = None,
    default_parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parameters = dict(default_parameters or {})
    parameters.update(model_parameters or {})

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    kwargs.update(normalize_model_parameters_for_model(model, parameters))

    if timeout is not None:
        kwargs["timeout"] = timeout
    if stream is not None:
        kwargs["stream"] = stream
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base
    if tools:
        kwargs["tools"] = tools
    return kwargs
