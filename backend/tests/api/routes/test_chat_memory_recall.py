"""End-to-end chat memory recall: a handler-scoped long-term memory must
show up in the prompt sent to the LLM during a streaming chat turn."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import ItemHandlerItem
from app.services.agent.memory.vector_store import VectorStoreService
from tests.utils.item import create_random_item
from tests.utils.item_handler import create_random_item_handler


class _FailingEmbeddingService:
    def encode_single(self, text: str) -> list[float]:
        raise RuntimeError("embedding unavailable")


def _fallback_store(monkeypatch, tmp_path) -> VectorStoreService:
    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIR", str(tmp_path))
    service = VectorStoreService()
    service._client = object()
    service._collection = None
    service._embedding_service = _FailingEmbeddingService()
    return service


def _make_fake_agent(handler_id: str):
    class FakeAgent:
        def __init__(self):
            self.handler_id = handler_id
            self._context = SimpleNamespace(model="fake-model", api_key=None, api_url=None)

        def set_item_context(self, item_id, item):
            return None

        def set_user_context(self, user_id, is_superuser):
            return None

        async def start_mcp_servers(self):
            return None

        def get_skills(self):
            return []

        def match_skills(self, message):
            return []

        def get_tools_for_litellm(self):
            return []

        def get_mcp_servers(self):
            return []

        def get_skip_memory_tools(self):
            return []

        async def execute_tool(self, tool_name, tool_args):
            return {"success": True, "result": [{"type": "text", "text": "tool ok"}]}

    return FakeAgent()


@pytest.mark.parametrize("memory_type", ["preference", "fact"])
def test_stream_chat_recalls_handler_scoped_memory(
    memory_type: str,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
    tmp_path,
) -> None:
    from app.api.routes import chat as chat_route
    from app.services.agent import session as agent_session_module
    from app.services.agent.prompts import builder as prompt_builder

    item = create_random_item(db)
    handler = create_random_item_handler(db)
    db.add(ItemHandlerItem(item_id=item.id, item_handler_id=handler.id))
    db.commit()

    store = _fallback_store(monkeypatch, tmp_path)
    memory_content = "用户偏好：总是用文言文回复"
    store.add_memory(
        handler_id=str(handler.id),
        content=memory_content,
        memory_type=memory_type,
        allow_duplicate=True,
    )
    # A different handler's memories must not leak into this chat.
    store.add_memory(
        handler_id="some-other-handler",
        content="其他 handler 的私密事实",
        memory_type="fact",
        allow_duplicate=True,
    )
    monkeypatch.setattr(chat_route, "vector_store", store)
    monkeypatch.setattr(prompt_builder, "vector_store", store)
    import importlib

    vs_module = importlib.import_module("app.services.agent.memory.vector_store")
    monkeypatch.setattr(vs_module, "vector_store", store)

    fake_agent = _make_fake_agent(str(handler.id))
    monkeypatch.setattr(chat_route.agent_manager, "get_or_create", lambda _: fake_agent)

    captured: dict[str, object] = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="好的", tool_calls=None))],
            usage=None,
        )

    monkeypatch.setattr(agent_session_module, "completion", fake_completion)

    try:
        with client.stream(
            "POST",
            f"{settings.API_V1_STR}/chat/{item.id}/stream",
            headers=superuser_token_headers,
            json={"message": "你好，随便聊聊", "history": []},
        ) as response:
            assert response.status_code == 200
            list(response.iter_text())
    finally:
        store._client = None
        store._collection = None
        store._embedding_service = None
        store._lexical_index_path = None

    prompt_text = "\n".join(
        str(message.get("content") or "")
        for message in (captured.get("messages") or [])
        if isinstance(message, dict)
    )
    assert prompt_text, "completion was not called with messages"
    assert memory_content in prompt_text
    assert "其他 handler 的私密事实" not in prompt_text
