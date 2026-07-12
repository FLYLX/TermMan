import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.models import ItemChatSession, ItemHandlerItem
from app.services.agent.history.chat import (
    SESSION_SUMMARY_TYPE,
    append_chat_message,
)
from app.services.agent.session import agent_session_manager
from app.services.agent.stream_manager import stream_manager
from tests.utils.item import create_random_item
from tests.utils.item_handler import create_random_item_handler


def _create_linked_item_and_handler(db: Session):
    item = create_random_item(db)
    handler = create_random_item_handler(db)
    db.add(ItemHandlerItem(item_id=item.id, item_handler_id=handler.id))
    db.commit()
    return item, handler


def _make_fake_agent(*, tools=None, execute_tool_result=None):
    class FakeAgent:
        def __init__(self):
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
            return tools or []

        def get_mcp_servers(self):
            return []

        def get_skip_memory_tools(self):
            return []

        async def execute_tool(self, tool_name, tool_args):
            if callable(execute_tool_result):
                return execute_tool_result(tool_name, tool_args)
            if execute_tool_result is not None:
                return execute_tool_result
            return {"success": True, "result": [{"type": "text", "text": "tool ok"}]}

    return FakeAgent()


def _fake_stream_completion(**_kwargs):
    chunks = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="Shared ", tool_calls=None),
                    finish_reason=None,
                )
            ]
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="reply", tool_calls=None),
                    finish_reason="stop",
                )
            ]
        ),
    ]
    return iter(chunks)


def _fake_sync_completion(**_kwargs):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Handled terminal event", tool_calls=None)
            )
        ]
    )


def _non_status_event_types(events: list[dict]) -> list[str]:
    return [event["type"] for event in events if event["type"] != "agent_status"]


def test_generate_stream_executes_tool_inside_running_event_loop(
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route

    item, handler = _create_linked_item_and_handler(db)
    tool_name = "mcp_local_list_memories"
    call_count = {"value": 0}
    tool_calls: list[tuple[str, dict]] = []

    fake_agent = _make_fake_agent(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Send a command to the terminal",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        execute_tool_result=lambda name, args: (
            tool_calls.append((name, dict(args)))
            or {"success": True, "result": [{"type": "text", "text": "sent"}]}
        ),
    )

    def fake_stream_completion(**kwargs):
        assert kwargs["messages"]
        call_count["value"] += 1
        if call_count["value"] == 1:
            return iter(
                [
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(
                                    content="Running command",
                                    tool_calls=[
                                        SimpleNamespace(
                                            index=0,
                                            id="call_1",
                                            function=SimpleNamespace(
                                                name=tool_name,
                                                arguments='{"command":"pwd"}',
                                            ),
                                        )
                                    ],
                                ),
                                finish_reason=None,
                            )
                        ]
                    )
                ]
            )

        return iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content="Command dispatched", tool_calls=None),
                            finish_reason="stop",
                        )
                    ]
                )
            ]
        )

    monkeypatch.setattr(chat_route, "completion", fake_stream_completion)
    monkeypatch.setattr(chat_route, "get_relevant_memories", lambda *args, **kwargs: "")
    monkeypatch.setattr(chat_route, "extract_important_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_route, "_create_agent_task_plan", lambda *args, **kwargs: None)

    async def consume_inside_running_loop():
        return list(
            chat_route.generate_stream(
                message="run pwd",
                history=[],
                handler=handler,
                item_id=str(item.id),
                agent=fake_agent,
            )
        )

    chunks = asyncio.run(consume_inside_running_loop())

    assert tool_calls == [(tool_name, {"command": "pwd", "item_id": str(item.id)})]
    assert any('"type": "agent_response"' in chunk for chunk in chunks)

def test_generate_stream_stops_after_terminal_command_dispatch(
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route

    item, handler = _create_linked_item_and_handler(db)
    tool_name = "mcp_local_execute_command"
    call_count = {"value": 0}
    tool_calls: list[tuple[str, dict]] = []

    fake_agent = _make_fake_agent(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Send a command to the terminal",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        execute_tool_result=lambda name, args: (
            tool_calls.append((name, dict(args)))
            or {
                "success": True,
                "result": [
                    {
                        "type": "text",
                        "text": "\u547d\u4ee4\u5df2\u53d1\u9001\u5230\u7ec8\u7aef\uff0c\u5c1a\u672a\u786e\u8ba4\u6267\u884c\u7ed3\u679c: apt update",
                    }
                ],
            }
        ),
    )

    def fake_stream_completion(**kwargs):
        assert kwargs["messages"]
        call_count["value"] += 1
        if call_count["value"] > 1:
            raise AssertionError("terminal command dispatch should stop and wait for feedback")

        return iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="Running command",
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        id="call_1",
                                        function=SimpleNamespace(
                                            name=tool_name,
                                            arguments='{"command":"apt update"}',
                                        ),
                                    )
                                ],
                            ),
                            finish_reason=None,
                        )
                    ]
                )
            ]
        )

    agent_session_manager.remove_session(str(item.id))
    monkeypatch.setattr(chat_route, "completion", fake_stream_completion)
    monkeypatch.setattr(
        chat_route,
        "build_chat_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "terminal command"}],
    )
    monkeypatch.setattr(chat_route, "get_relevant_memories", lambda *args, **kwargs: "")
    monkeypatch.setattr(chat_route, "extract_important_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_route, "_create_agent_task_plan", lambda *args, **kwargs: None)

    try:
        chunks = list(
            chat_route.generate_stream(
                message="install packages",
                history=[],
                handler=handler,
                item_id=str(item.id),
                agent=fake_agent,
            )
        )
    finally:
        agent_session_manager.remove_session(str(item.id))

    assert call_count["value"] == 1
    assert tool_calls == [(tool_name, {"command": "apt update", "item_id": str(item.id)})]
    assert any('"status": "waiting_terminal"' in chunk for chunk in chunks)
    assert not any('"type": "agent_tool_result"' in chunk for chunk in chunks)
    assert not any("\u547d\u4ee4\u5df2\u53d1\u9001\u5230\u7ec8\u7aef" in chunk for chunk in chunks)
    assert not any("\u5c1a\u672a\u786e\u8ba4\u6267\u884c\u7ed3\u679c" in chunk for chunk in chunks)
    assert not any('"type": "agent_response"' in chunk for chunk in chunks)
    assert not any("max iteration limit" in chunk for chunk in chunks)


def test_generate_stream_stops_after_background_job_start(
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route

    item, handler = _create_linked_item_and_handler(db)
    tool_name = "mcp_local_run_job"
    call_count = {"value": 0}
    tool_calls: list[tuple[str, dict]] = []

    fake_agent = _make_fake_agent(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Start a background job",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        execute_tool_result=lambda name, args: (
            tool_calls.append((name, dict(args)))
            or {
                "success": True,
                "result": [
                    {
                        "type": "text",
                        "text": "\u540e\u53f0\u4efb\u52a1\u5df2\u542f\u52a8",
                    },
                    {
                        "type": "metadata",
                        "background_job_started": True,
                    },
                ],
            }
        ),
    )

    def fake_stream_completion(**kwargs):
        assert kwargs["messages"]
        call_count["value"] += 1
        if call_count["value"] > 1:
            raise AssertionError("background job start should finish the current turn")

        return iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="Starting background job",
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        id="call_1",
                                        function=SimpleNamespace(
                                            name=tool_name,
                                            arguments='{"command":"apt-get install -y temurin-17-jdk"}',
                                        ),
                                    )
                                ],
                            ),
                            finish_reason=None,
                        )
                    ]
                )
            ]
        )

    agent_session_manager.remove_session(str(item.id))
    monkeypatch.setattr(chat_route, "completion", fake_stream_completion)
    monkeypatch.setattr(
        chat_route,
        "build_chat_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "start background job"}],
    )
    monkeypatch.setattr(chat_route, "get_relevant_memories", lambda *args, **kwargs: "")
    monkeypatch.setattr(chat_route, "extract_important_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_route, "_create_agent_task_plan", lambda *args, **kwargs: None)

    try:
        chunks = list(
            chat_route.generate_stream(
                message="install java",
                history=[],
                handler=handler,
                item_id=str(item.id),
                agent=fake_agent,
            )
        )
    finally:
        agent_session_manager.remove_session(str(item.id))

    assert call_count["value"] == 1
    assert tool_calls == [
        (
            tool_name,
            {
                "command": "apt-get install -y temurin-17-jdk",
                "item_id": str(item.id),
            },
        )
    ]
    assert not any('"type": "agent_tool_result"' in chunk for chunk in chunks)
    assert not any('"type": "agent_response"' in chunk for chunk in chunks)
    assert any('"done": true' in chunk for chunk in chunks)
    assert not any("max iteration limit" in chunk for chunk in chunks)


def test_generate_stream_blocks_shell_command_while_busy_terminal_command_pending(
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route

    item, handler = _create_linked_item_and_handler(db)
    item_id = str(item.id)
    tool_name = "mcp_local_execute_command"
    call_count = {"value": 0}

    fake_agent = _make_fake_agent(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Send a command to the terminal",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        execute_tool_result=lambda _name, _args: (_ for _ in ()).throw(
            AssertionError("blocked command should not execute")
        ),
    )

    def fake_stream_completion(**kwargs):
        assert kwargs["messages"]
        call_count["value"] += 1
        return iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="Checking Java",
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        id="call_1",
                                        function=SimpleNamespace(
                                            name=tool_name,
                                            arguments='{"command":"java -version"}',
                                        ),
                                    )
                                ],
                            ),
                            finish_reason=None,
                        )
                    ]
                )
            ]
        )

    agent_session_manager.remove_session(item_id)
    terminal_session = agent_session_manager.get_or_create_session(item_id, str(handler.id))
    monkeypatch.setattr(terminal_session, "_schedule_pending_command_recheck", lambda *args, **kwargs: None)
    monkeypatch.setattr(terminal_session, "_get_log_line_count", lambda: 0)
    terminal_session.mark_terminal_command_dispatched(
        tool_name,
        {"command": "apt update"},
    )

    monkeypatch.setattr(chat_route, "completion", fake_stream_completion)
    monkeypatch.setattr(
        chat_route,
        "build_chat_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "terminal command"}],
    )
    monkeypatch.setattr(chat_route, "get_relevant_memories", lambda *args, **kwargs: "")
    monkeypatch.setattr(chat_route, "extract_important_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_route, "_create_agent_task_plan", lambda *args, **kwargs: None)

    try:
        chunks = list(
            chat_route.generate_stream(
                message="check java",
                history=[],
                handler=handler,
                item_id=item_id,
                agent=fake_agent,
            )
        )
    finally:
        agent_session_manager.remove_session(item_id)

    assert call_count["value"] == 1
    assert any('"type": "agent_warning"' in chunk for chunk in chunks)
    assert any("apt update" in chunk and "java -version" in chunk for chunk in chunks)
    assert not any('"type": "agent_tool_result"' in chunk for chunk in chunks)
    assert not any("max iteration limit" in chunk for chunk in chunks)


def test_generate_stream_allows_shell_query_to_auto_route_when_console_is_active(
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route

    item, handler = _create_linked_item_and_handler(db)
    item_id = str(item.id)
    tool_name = "mcp_local_execute_command"
    tool_calls: list[tuple[str, dict]] = []

    fake_agent = _make_fake_agent(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Send a command to the terminal",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        execute_tool_result=lambda name, args: (
            tool_calls.append((name, dict(args)))
            or {
                "success": True,
                "result": [
                    {"type": "text", "text": "后台任务已启动"},
                    {
                        "type": "metadata",
                        "auto_routed_execute_command_to_run_job": True,
                        "background_job_started": True,
                    },
                ],
            }
        ),
    )

    def fake_stream_completion(**kwargs):
        assert kwargs["messages"]
        return iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="Checking process",
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        id="call_1",
                                        function=SimpleNamespace(
                                            name=tool_name,
                                            arguments='{"command":"ps aux | grep java | grep -v grep"}',
                                        ),
                                    )
                                ],
                            ),
                            finish_reason=None,
                        )
                    ]
                )
            ]
        )

    agent_session_manager.remove_session(item_id)
    terminal_session = agent_session_manager.get_or_create_session(item_id, str(handler.id))
    monkeypatch.setattr(terminal_session, "_schedule_pending_command_recheck", lambda *args, **kwargs: None)
    monkeypatch.setattr(terminal_session, "_get_log_line_count", lambda: 0)
    terminal_session.mark_terminal_command_dispatched(
        tool_name,
        {"command": "bash run.sh"},
    )

    monkeypatch.setattr(chat_route, "completion", fake_stream_completion)
    monkeypatch.setattr(
        chat_route,
        "build_chat_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "check process"}],
    )
    monkeypatch.setattr(chat_route, "get_relevant_memories", lambda *args, **kwargs: "")
    monkeypatch.setattr(chat_route, "extract_important_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_route, "_create_agent_task_plan", lambda *args, **kwargs: None)

    try:
        chunks = list(
            chat_route.generate_stream(
                message="check process",
                history=[],
                handler=handler,
                item_id=item_id,
                agent=fake_agent,
            )
        )
    finally:
        agent_session_manager.remove_session(item_id)

    assert tool_calls == [
        (
            tool_name,
            {
                "command": "ps aux | grep java | grep -v grep",
                "item_id": item_id,
            },
        )
    ]
    assert not any("交互式控制台" in chunk and "已拦截" in chunk for chunk in chunks)
    assert not any('"type": "agent_response"' in chunk for chunk in chunks)
    assert any('"done": true' in chunk for chunk in chunks)


def test_generate_stream_stops_when_terminal_command_not_delivered(
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route

    item, handler = _create_linked_item_and_handler(db)
    tool_name = "mcp_local_execute_command"
    call_count = {"value": 0}

    fake_agent = _make_fake_agent(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Send a command to the terminal",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        execute_tool_result={
            "success": True,
            "result": [
                {
                    "type": "text",
                    "text": "终端未连接或未打开，命令没有发送。请先启动或连接终端后再试。",
                }
            ],
        },
    )

    def fake_stream_completion(**kwargs):
        assert kwargs["messages"]
        call_count["value"] += 1
        if call_count["value"] > 1:
            raise AssertionError("terminal dispatch failure should stop the current turn")

        return iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="Running command",
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        id="call_1",
                                        function=SimpleNamespace(
                                            name=tool_name,
                                            arguments='{"command":"java -version"}',
                                        ),
                                    )
                                ],
                            ),
                            finish_reason=None,
                        )
                    ]
                )
            ]
        )

    monkeypatch.setattr(chat_route, "completion", fake_stream_completion)
    monkeypatch.setattr(
        chat_route,
        "build_chat_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "安装java"}],
    )
    monkeypatch.setattr(chat_route, "get_relevant_memories", lambda *args, **kwargs: "")
    monkeypatch.setattr(chat_route, "extract_important_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_route, "_create_agent_task_plan", lambda *args, **kwargs: None)

    chunks = list(
        chat_route.generate_stream(
            message="安装java",
            history=[],
            handler=handler,
            item_id=str(item.id),
            agent=fake_agent,
        )
    )

    assert call_count["value"] == 1
    assert any('"type": "agent_warning"' in chunk for chunk in chunks)
    assert any("终端未连接或未打开" in chunk for chunk in chunks)
    assert not any("max iteration limit" in chunk for chunk in chunks)


def test_append_chat_message_preserves_order_and_metadata(db: Session) -> None:
    item, _ = _create_linked_item_and_handler(db)

    append_chat_message(
        str(item.id),
        role="user",
        content="hello",
        message_type="chat_user",
    )
    append_chat_message(
        str(item.id),
        role="assistant",
        content="run tool demo",
        message_type="agent_action",
        extra={"tool_name": "demo"},
    )

    with Session(engine) as session:
        chat_session = session.exec(
            select(ItemChatSession).where(ItemChatSession.item_id == item.id)
        ).first()

    assert chat_session is not None
    assert [message["type"] for message in chat_session.messages] == ["chat_user", "agent_action"]
    assert chat_session.messages[1]["tool_name"] == "demo"
    assert chat_session.messages[0]["role"] == "user"
    assert chat_session.messages[1]["role"] == "assistant"


def test_chat_session_endpoint_paginates_history_from_newest(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    item, _ = _create_linked_item_and_handler(db)
    messages = [
        {
            "role": "user",
            "content": f"message {index}",
            "type": "chat_user",
        }
        for index in range(45)
    ]
    db.add(ItemChatSession(item_id=item.id, messages=messages))
    db.commit()

    latest_response = client.get(
        f"{settings.API_V1_STR}/memory/{item.id}/session?limit=20&offset=0",
        headers=superuser_token_headers,
    )
    assert latest_response.status_code == 200
    latest_page = latest_response.json()
    assert [message["content"] for message in latest_page["messages"]] == [
        f"message {index}" for index in range(25, 45)
    ]
    assert latest_page["total"] == 45
    assert latest_page["offset"] == 0
    assert latest_page["limit"] == 20
    assert latest_page["has_more"] is True

    older_response = client.get(
        f"{settings.API_V1_STR}/memory/{item.id}/session?limit=20&offset=20",
        headers=superuser_token_headers,
    )
    assert older_response.status_code == 200
    older_page = older_response.json()
    assert [message["content"] for message in older_page["messages"]] == [
        f"message {index}" for index in range(5, 25)
    ]
    assert older_page["total"] == 45
    assert older_page["offset"] == 20
    assert older_page["has_more"] is True

    oldest_response = client.get(
        f"{settings.API_V1_STR}/memory/{item.id}/session?limit=20&offset=40",
        headers=superuser_token_headers,
    )
    assert oldest_response.status_code == 200
    oldest_page = oldest_response.json()
    assert [message["content"] for message in oldest_page["messages"]] == [
        f"message {index}" for index in range(5)
    ]
    assert oldest_page["total"] == 45
    assert oldest_page["offset"] == 40
    assert oldest_page["has_more"] is False


def test_append_chat_message_generates_session_summary_after_threshold(
    db: Session,
) -> None:
    item, _ = _create_linked_item_and_handler(db)

    for index in range(5):
        append_chat_message(
            str(item.id),
            role="user",
            content=f"user request {index}",
            message_type="chat_user",
        )
        append_chat_message(
            str(item.id),
            role="assistant",
            content=f"assistant result {index}",
            message_type="agent_response",
        )

    with Session(engine) as session:
        chat_session = session.exec(
            select(ItemChatSession).where(ItemChatSession.item_id == item.id)
        ).first()

    assert chat_session is not None
    assert chat_session.messages[0]["type"] == SESSION_SUMMARY_TYPE
    assert chat_session.messages[0]["content"].startswith("当前共享会话摘要")
    assert chat_session.messages[0]["summary_message_count"] == 10
    assert [message["type"] for message in chat_session.messages[1:]] == [
        "chat_user",
        "agent_response",
        "chat_user",
        "agent_response",
        "chat_user",
        "agent_response",
        "chat_user",
        "agent_response",
        "chat_user",
        "agent_response",
    ]


def test_chat_prompt_uses_session_summary_and_clips_recent_history(
    db: Session,
    monkeypatch,
) -> None:
    from app.services.agent.prompts import builder as prompt_builder

    item, _ = _create_linked_item_and_handler(db)
    fake_agent = SimpleNamespace(
        match_skills=lambda query: [],
        get_skills=lambda: [],
        get_skip_memory_tools=lambda: [],
    )

    for index in range(7):
        append_chat_message(
            str(item.id),
            role="user",
            content=f"older user message {index}",
            message_type="chat_user",
        )
        append_chat_message(
            str(item.id),
            role="assistant",
            content=f"older assistant reply {index}",
            message_type="agent_response",
        )

    monkeypatch.setattr(prompt_builder, "get_system_prompt", lambda agent: "system prompt")

    messages = prompt_builder.build_chat_turn_messages(
        fake_agent,
        item_id=str(item.id),
        message="latest question",
        query="latest question",
    )

    assert any(
        message["role"] == "system" and "共享会话摘要" in message["content"]
        for message in messages
    )
    assert messages[-1] == {"role": "user", "content": "latest question"}
    assert len(messages) <= 13
    assert all("older user message 0" not in message["content"] for message in messages)


def test_robot_chat_prompt_filters_recent_history_to_current_conversation(
    db: Session,
    monkeypatch,
) -> None:
    from app.plugins.robot.contracts import RobotReplyTarget
    from app.services.agent import agent as agent_module
    from app.services.agent.prompts import builder as prompt_builder

    item, _ = _create_linked_item_and_handler(db)
    robot_agent = agent_module.Agent(f"robot-history-{item.id}")
    robot_agent._context = agent_module.AgentContext(handler_id=str(item.id))
    robot_agent.set_robot_context(
        robot_id="robot-1",
        sender_key="onebot_v11:group:g2:u2",
        reply_target=RobotReplyTarget(
            target_type="group",
            target_id="g2",
            metadata={
                "conversation": {"type": "group", "id": "g2"},
                "target": {"id": "g2"},
            },
        ),
    )

    try:
        append_chat_message(
            str(item.id),
            role="user",
            content=(
                "[Robot message; conversation=group:g1; "
                "trigger=mention_bot; sender=Alice]\nfrom group one"
            ),
            message_type="chat_user",
        )
        append_chat_message(
            str(item.id),
            role="assistant",
            content="assistant reply to group one",
            message_type="agent_response",
        )
        append_chat_message(
            str(item.id),
            role="user",
            content=(
                "[Robot message; conversation=group:g2; "
                "trigger=mention_bot; sender=Bob]\nfrom group two"
            ),
            message_type="chat_user",
        )
        append_chat_message(
            str(item.id),
            role="assistant",
            content="assistant reply to group two",
            message_type="agent_response",
        )

        monkeypatch.setattr(prompt_builder, "get_system_prompt", lambda agent: "system prompt")

        messages = prompt_builder.build_chat_turn_messages(
            robot_agent,
            item_id=str(item.id),
            message=(
                "[Robot message; conversation=group:g2; "
                "trigger=mention_bot; sender=Bob]\nlatest"
            ),
        )
    finally:
        robot_agent.clear_robot_context()
        agent_module.Agent._instances.pop(robot_agent.handler_id, None)

    combined = "\n".join(message["content"] for message in messages)
    assert "from group two" in combined
    assert "latest" in combined
    assert "from group one" not in combined
    assert "assistant reply to group one" not in combined
    assert "assistant reply to group two" in combined


def test_chat_prompt_includes_handler_knowledge(
    db: Session,
    monkeypatch,
) -> None:
    from app.services.agent.prompts import builder as prompt_builder

    item, handler = _create_linked_item_and_handler(db)
    fake_agent = SimpleNamespace(
        handler_id=str(handler.id),
        enabled_knowledge_files=["ops.md"],
        match_skills=lambda query: [],
        get_skills=lambda: [],
        get_skip_memory_tools=lambda: [],
    )

    monkeypatch.setattr(prompt_builder, "get_system_prompt", lambda agent: "system prompt")
    monkeypatch.setattr(
        prompt_builder.knowledge_base_service,
        "search",
        lambda query, enabled_files, n_results=4: [
            {
                "content": "Deploy with docker compose up -d",
                "metadata": {"file_name": "ops.md"},
            }
        ],
    )

    messages = prompt_builder.build_chat_turn_messages(
        fake_agent,
        item_id=str(item.id),
        message="How do I start the stack?",
        query="How do I start the stack?",
    )

    assert any(
        message["role"] == "system"
        and "Relevant knowledge files" in message["content"]
        and "ops.md" in message["content"]
        for message in messages
    )


def test_terminal_output_broadcasts_to_all_subscribers_and_persists(
    db: Session,
    monkeypatch,
) -> None:
    from app.services.agent import session as session_module

    item, handler = _create_linked_item_and_handler(db)
    item_id = str(item.id)
    handler_id = str(handler.id)
    fake_agent = _make_fake_agent()
    subscriber_a: list[dict] = []
    subscriber_b: list[dict] = []

    agent_session_manager.remove_session(item_id)
    monkeypatch.setattr(session_module.AgentSession, "get_agent", lambda self: fake_agent)
    monkeypatch.setattr(session_module, "completion", _fake_sync_completion)
    monkeypatch.setattr(
        session_module.AgentSession,
        "_get_relevant_memories",
        lambda self, query, n_results=3: "",
    )
    monkeypatch.setattr(
        session_module,
        "build_terminal_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "terminal command"}],
    )

    stream_manager.register_chat(item_id, subscriber_a.append)
    stream_manager.register_chat(item_id, subscriber_b.append)

    try:
        stream_manager.process_stream(item_id, "error: boom", handler_id)
        assert [event["type"] for event in subscriber_a] == ["agent_status"]
        assert [event["type"] for event in subscriber_b] == ["agent_status"]
        stream_manager.flush_pending_stream(item_id)
    finally:
        stream_manager.unregister_chat(item_id, subscriber_a.append)
        stream_manager.unregister_chat(item_id, subscriber_b.append)
        agent_session_manager.remove_session(item_id)

    assert _non_status_event_types(subscriber_a) == ["terminal_output", "agent_response"]
    assert _non_status_event_types(subscriber_b) == ["terminal_output", "agent_response"]
    assert [event["status"] for event in subscriber_a if event["type"] == "agent_status"] == [
        "collecting",
        "running",
        "idle",
    ]
    assert [event["status"] for event in subscriber_b if event["type"] == "agent_status"] == [
        "collecting",
        "running",
        "idle",
    ]

    with Session(engine) as session:
        chat_session = session.exec(
            select(ItemChatSession).where(ItemChatSession.item_id == item.id)
        ).first()

    assert chat_session is not None
    assert [message["type"] for message in chat_session.messages] == [
        "terminal_output",
        "agent_response",
    ]


def test_manual_chat_and_terminal_output_share_item_session_history(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route
    from app.services.agent import session as session_module

    item, handler = _create_linked_item_and_handler(db)
    item_id = str(item.id)
    handler_id = str(handler.id)
    fake_agent = _make_fake_agent()

    agent_session_manager.remove_session(item_id)
    monkeypatch.setattr(chat_route.agent_manager, "get_or_create", lambda _: fake_agent)
    monkeypatch.setattr(chat_route, "completion", _fake_stream_completion)
    monkeypatch.setattr(chat_route, "get_relevant_memories", lambda *args, **kwargs: "")
    monkeypatch.setattr(chat_route, "extract_important_info", lambda *args, **kwargs: None)

    with client.stream(
        "POST",
        f"{settings.API_V1_STR}/chat/{item.id}/stream",
        headers=superuser_token_headers,
        json={"message": "Please inspect this", "history": []},
    ) as response:
        assert response.status_code == 200
        list(response.iter_text())

    monkeypatch.setattr(session_module.AgentSession, "get_agent", lambda self: fake_agent)
    monkeypatch.setattr(session_module, "completion", _fake_sync_completion)
    monkeypatch.setattr(
        session_module.AgentSession,
        "_get_relevant_memories",
        lambda self, query, n_results=3: "",
    )
    monkeypatch.setattr(
        session_module,
        "build_terminal_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "terminal command"}],
    )

    stream_manager.process_stream(item_id, "error: boom", handler_id)
    stream_manager.flush_pending_stream(item_id)
    agent_session_manager.remove_session(item_id)

    response = client.get(
        f"{settings.API_V1_STR}/memory/{item.id}/session",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200

    messages = response.json()["messages"]
    assert [message["type"] for message in messages] == [
        "chat_user",
        "agent_response",
        "terminal_output",
        "agent_response",
    ]
    assert messages[0]["content"] == "Please inspect this"
    assert messages[1]["content"] == "Shared reply"
    assert messages[2]["content"] == "error: boom"
    assert messages[3]["content"] == "Handled terminal event"


def test_stream_chat_uses_sqlite_shared_short_term_history(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route

    item, _ = _create_linked_item_and_handler(db)
    fake_agent = _make_fake_agent()
    completion_messages: list[list[dict]] = []

    append_chat_message(
        str(item.id),
        role="user",
        content="Earlier question",
        message_type="chat_user",
    )
    append_chat_message(
        str(item.id),
        role="assistant",
        content="Earlier answer",
        message_type="agent_response",
    )
    append_chat_message(
        str(item.id),
        role="terminal",
        content="error: missing file",
        message_type="terminal_output",
    )

    def fake_stream_completion(**kwargs):
        completion_messages.append(kwargs["messages"])
        return _fake_stream_completion(**kwargs)

    monkeypatch.setattr(chat_route.agent_manager, "get_or_create", lambda _: fake_agent)
    monkeypatch.setattr(chat_route, "completion", fake_stream_completion)
    monkeypatch.setattr(chat_route, "extract_important_info", lambda *args, **kwargs: None)

    with client.stream(
        "POST",
        f"{settings.API_V1_STR}/chat/{item.id}/stream",
        headers=superuser_token_headers,
        json={"message": "What should I do next?", "history": []},
    ) as response:
        assert response.status_code == 200
        list(response.iter_text())

    assert completion_messages
    prompt_messages = completion_messages[0]
    assert any(
        message["role"] == "user" and message["content"] == "Earlier question"
        for message in prompt_messages
    )
    assert any(
        message["role"] == "assistant" and message["content"] == "Earlier answer"
        for message in prompt_messages
    )
    assert any(
        message["role"] == "user"
        and message["content"] == "终端过滤输出:\nerror: missing file"
        for message in prompt_messages
    )
    assert prompt_messages[-1] == {"role": "user", "content": "What should I do next?"}


def test_stream_chat_persists_explicit_preference_memory(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route

    item, _ = _create_linked_item_and_handler(db)
    fake_agent = _make_fake_agent()
    captured_memory: dict[str, object] = {}

    monkeypatch.setattr(chat_route.agent_manager, "get_or_create", lambda _: fake_agent)
    monkeypatch.setattr(chat_route, "completion", _fake_stream_completion)
    monkeypatch.setattr(chat_route.vector_store, "get_all_memories", lambda *args, **kwargs: [])

    def fake_add_memory(**kwargs):
        captured_memory.update(kwargs)
        return "memory-1"

    monkeypatch.setattr(chat_route.vector_store, "add_memory", fake_add_memory)

    with client.stream(
        "POST",
        f"{settings.API_V1_STR}/chat/{item.id}/stream",
        headers=superuser_token_headers,
        json={"message": "记住以后都用中文并且回复简洁", "history": []},
    ) as response:
        assert response.status_code == 200
        list(response.iter_text())

    assert captured_memory["item_id"] == str(item.id)
    assert captured_memory["content"] == "用户偏好：以后都用中文并且回复简洁"
    assert captured_memory["memory_type"] == "preference"
    assert captured_memory["ttl_days"] == 180
    assert captured_memory["metadata"]["type"] == "conversation_explicit"
    assert captured_memory["metadata"]["source"] == "chat_user"
    assert captured_memory["metadata"]["verified"] is True


def test_stream_chat_confirmation_persists_previous_assistant_fact(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route

    item, _ = _create_linked_item_and_handler(db)
    fake_agent = _make_fake_agent()
    captured_memory: dict[str, object] = {}

    append_chat_message(
        str(item.id),
        role="assistant",
        content="cron_job.py 位于 /app/src/cron_job.py",
        message_type="agent_response",
    )

    monkeypatch.setattr(chat_route.agent_manager, "get_or_create", lambda _: fake_agent)
    monkeypatch.setattr(chat_route, "completion", _fake_stream_completion)
    monkeypatch.setattr(chat_route.vector_store, "get_all_memories", lambda *args, **kwargs: [])

    def fake_add_memory(**kwargs):
        captured_memory.update(kwargs)
        return "memory-2"

    monkeypatch.setattr(chat_route.vector_store, "add_memory", fake_add_memory)

    with client.stream(
        "POST",
        f"{settings.API_V1_STR}/chat/{item.id}/stream",
        headers=superuser_token_headers,
        json={"message": "对，就是这个路径", "history": []},
    ) as response:
        assert response.status_code == 200
        list(response.iter_text())

    assert captured_memory["item_id"] == str(item.id)
    assert captured_memory["content"] == "cron_job.py 位于 /app/src/cron_job.py"
    assert captured_memory["memory_type"] == "fact"
    assert captured_memory["ttl_days"] == 90
    assert captured_memory["metadata"]["type"] == "conversation_confirmed"
    assert captured_memory["metadata"]["source"] == "assistant_response"
    assert captured_memory["metadata"]["verified"] is True
    assert captured_memory["metadata"]["memory_key"] == "fact.cron_job.py"


def test_stream_chat_task_resolution_updates_existing_memory(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route

    item, _ = _create_linked_item_and_handler(db)
    fake_agent = _make_fake_agent()
    captured_update: dict[str, object] = {}

    monkeypatch.setattr(chat_route.agent_manager, "get_or_create", lambda _: fake_agent)
    monkeypatch.setattr(chat_route, "completion", _fake_stream_completion)

    monkeypatch.setattr(
        chat_route.vector_store,
        "get_all_memories",
        lambda *args, **kwargs: [
            {
                "id": "task-1",
                "content": "当前任务：修复 daemon 状态同步",
                "metadata": {
                    "memory_type": "task",
                    "memory_key": "task.修复_daemon_状态同步",
                    "status": "active",
                    "created_at": "2026-04-02T09:00:00",
                },
            }
        ],
    )

    def fake_update_memory(**kwargs):
        captured_update.update(kwargs)
        return True

    monkeypatch.setattr(chat_route.vector_store, "update_memory", fake_update_memory)
    monkeypatch.setattr(
        chat_route.vector_store,
        "add_memory",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("task resolution should update existing memory instead of add")
        ),
    )

    with client.stream(
        "POST",
        f"{settings.API_V1_STR}/chat/{item.id}/stream",
        headers=superuser_token_headers,
        json={"message": "这个任务已经完成了", "history": []},
    ) as response:
        assert response.status_code == 200
        list(response.iter_text())

    assert captured_update["memory_id"] == "task-1"
    assert captured_update["content"] == "当前任务：修复 daemon 状态同步（已完成）"
    assert captured_update["metadata"]["status"] == "completed"
    assert captured_update["metadata"]["type"] == "conversation_status_update"
    assert captured_update["metadata"]["memory_key"] == "task.修复_daemon_状态同步"


def test_terminal_output_batches_multiple_events_into_one_terminal_record(
    db: Session,
    monkeypatch,
) -> None:
    from app.services.agent import session as session_module

    item, handler = _create_linked_item_and_handler(db)
    item_id = str(item.id)
    handler_id = str(handler.id)
    fake_agent = _make_fake_agent()
    subscriber_events: list[dict] = []

    agent_session_manager.remove_session(item_id)
    monkeypatch.setattr(session_module.AgentSession, "get_agent", lambda self: fake_agent)
    monkeypatch.setattr(session_module, "completion", _fake_sync_completion)
    monkeypatch.setattr(
        session_module.AgentSession,
        "_get_relevant_memories",
        lambda self, query, n_results=3: "",
    )
    monkeypatch.setattr(
        session_module,
        "build_terminal_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "terminal command"}],
    )

    stream_manager.register_chat(item_id, subscriber_events.append)

    try:
        stream_manager.process_stream(item_id, "error: first line", handler_id)
        stream_manager.process_stream(item_id, "stacktrace: second line", handler_id)
        assert [event["type"] for event in subscriber_events] == ["agent_status"]

        stream_manager.flush_pending_stream(item_id)
    finally:
        stream_manager.unregister_chat(item_id, subscriber_events.append)
        agent_session_manager.remove_session(item_id)

    assert _non_status_event_types(subscriber_events) == ["terminal_output", "agent_response"]
    terminal_event = next(
        event for event in subscriber_events if event["type"] == "terminal_output"
    )
    assert terminal_event["content"] == "error: first line\nstacktrace: second line"

    with Session(engine) as session:
        chat_session = session.exec(
            select(ItemChatSession).where(ItemChatSession.item_id == item.id)
        ).first()

    assert chat_session is not None
    assert chat_session.messages[0]["type"] == "terminal_output"
    assert chat_session.messages[0]["content"] == "error: first line\nstacktrace: second line"


def test_stream_chat_hides_read_terminal_log_tool_details(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route

    item, handler = _create_linked_item_and_handler(db)
    tool_name = "mcp_local_read_terminal_log"
    raw_log_text = "RAW LOG LINE 1\nRAW LOG LINE 2"

    fake_agent = _make_fake_agent(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Read terminal log",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        execute_tool_result={
            "success": True,
            "result": [{"type": "text", "text": raw_log_text}],
        },
    )

    def fake_stream_completion(**kwargs):
        has_tool_result = any(message.get("role") == "tool" for message in kwargs["messages"])
        if has_tool_result:
            return iter(
                [
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(
                                    content="Found the root cause in the log and summarized it.",
                                    tool_calls=None,
                                ),
                                finish_reason="stop",
                            )
                        ]
                    )
                ]
            )

        return iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="Inspecting the terminal log",
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        id="call_1",
                                        function=SimpleNamespace(
                                            name=tool_name,
                                            arguments="{}",
                                        ),
                                    )
                                ],
                            ),
                            finish_reason=None,
                        )
                    ]
                )
            ]
        )

    monkeypatch.setattr(chat_route.agent_manager, "get_or_create", lambda _: fake_agent)
    monkeypatch.setattr(chat_route, "completion", fake_stream_completion)
    monkeypatch.setattr(chat_route, "get_relevant_memories", lambda *args, **kwargs: "")
    monkeypatch.setattr(chat_route, "extract_important_info", lambda *args, **kwargs: None)

    with client.stream(
        "POST",
        f"{settings.API_V1_STR}/chat/{item.id}/stream",
        headers=superuser_token_headers,
        json={"message": "Check the log", "history": []},
    ) as response:
        assert response.status_code == 200
        list(response.iter_text())

    with Session(engine) as session:
        chat_session = session.exec(
            select(ItemChatSession).where(ItemChatSession.item_id == item.id)
        ).first()

    assert chat_session is not None
    assert [message["type"] for message in chat_session.messages] == [
        "chat_user",
        "agent_response",
    ]
    assert raw_log_text not in chat_session.messages[1]["content"]
    assert chat_session.messages[1]["content"] == "Found the root cause in the log and summarized it."


def test_terminal_session_stops_after_command_dispatch_and_waits_for_feedback(
    db: Session,
    monkeypatch,
) -> None:
    from app.services.agent import session as session_module

    item, handler = _create_linked_item_and_handler(db)
    item_id = str(item.id)
    handler_id = str(handler.id)
    tool_name = "mcp_local_execute_command"
    events: list[dict] = []

    fake_agent = _make_fake_agent(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Send a command to the terminal",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        execute_tool_result={
            "success": True,
            "result": [
                {
                    "type": "text",
                    "text": "命令已发送到终端，尚未确认执行结果: npm run dev",
                }
            ],
        },
    )

    call_count = {"value": 0}

    def fake_command_completion(**_kwargs):
        call_count["value"] += 1
        if call_count["value"] > 1:
            raise AssertionError("command dispatch should stop the current turn")

        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="准备执行修复命令",
                        tool_calls=[
                            SimpleNamespace(
                                id="call_1",
                                function=SimpleNamespace(
                                    name=tool_name,
                                    arguments='{"command":"npm run dev"}',
                                ),
                            )
                        ],
                    )
                )
            ]
        )

    agent_session_manager.remove_session(item_id)
    monkeypatch.setattr(session_module.AgentSession, "get_agent", lambda self: fake_agent)
    monkeypatch.setattr(session_module, "completion", fake_command_completion)
    monkeypatch.setattr(
        session_module.AgentSession,
        "_get_relevant_memories",
        lambda self, query, n_results=3: "",
    )
    monkeypatch.setattr(
        session_module,
        "build_terminal_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "terminal command"}],
    )

    try:
        session = agent_session_manager.get_or_create_session(item_id, handler_id)
        session.add_output_callback(events.append)
        session.process_input(
            session_module.InputMessage(
                input_type=session_module.InputType.TERMINAL,
                content="error: boom",
            )
        )
    finally:
        agent_session_manager.remove_session(item_id)

    assert _non_status_event_types(events) == [
        "terminal_output",
        "agent_action",
    ]
    assert not any(event.get("type") == "agent_tool_result" for event in events)
    assert not any("尚未确认执行结果" in event.get("content", "") for event in events)
    assert [event["status"] for event in events if event["type"] == "agent_status"] == [
        "running",
        "tool",
        "waiting_terminal",
    ]
    return
    non_status_events = [event for event in events if event["type"] != "agent_status"]
    assert non_status_events[-1]["type"] == "agent_response"
    assert events[-2]["content"] == "命令已发送，等待终端反馈"
    assert [event["status"] for event in events if event["type"] == "agent_status"] == [
        "running",
        "tool",
        "waiting_terminal",
    ]


def test_command_echo_only_terminal_output_does_not_retrigger_command_dispatch(
    db: Session,
    monkeypatch,
) -> None:
    from app.services.agent import session as session_module

    item, handler = _create_linked_item_and_handler(db)
    item_id = str(item.id)
    handler_id = str(handler.id)
    tool_name = "mcp_local_execute_command"
    command = 'find /app -name "cron_job.py" -type f 2>/dev/null'
    events: list[dict] = []

    fake_agent = _make_fake_agent(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Send a command to the terminal",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        execute_tool_result={
            "success": True,
            "result": [{"type": "text", "text": f"command sent: {command}"}],
        },
    )

    call_count = {"value": 0}

    def fake_command_completion(**_kwargs):
        call_count["value"] += 1
        if call_count["value"] > 1:
            raise AssertionError("command echo should not trigger another completion")

        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="准备执行定位命令",
                        tool_calls=[
                            SimpleNamespace(
                                id="call_1",
                                function=SimpleNamespace(
                                    name=tool_name,
                                    arguments='{"command":"find /app -name \\"cron_job.py\\" -type f 2>/dev/null"}',
                                ),
                            )
                        ],
                    )
                )
            ]
        )

    agent_session_manager.remove_session(item_id)
    monkeypatch.setattr(session_module.AgentSession, "get_agent", lambda self: fake_agent)
    monkeypatch.setattr(session_module, "completion", fake_command_completion)
    monkeypatch.setattr(
        session_module.AgentSession,
        "_get_relevant_memories",
        lambda self, query, n_results=3: "",
    )
    monkeypatch.setattr(
        session_module,
        "build_terminal_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "terminal command"}],
    )

    stream_manager.register_chat(item_id, events.append)
    try:
        stream_manager.process_stream(item_id, "error: boom", handler_id)
        stream_manager.flush_pending_stream(item_id)
        stream_manager.process_stream(
            item_id,
            f"[2026-04-02 04:04:29] # # {command}",
            handler_id,
        )
        stream_manager.flush_pending_stream(item_id)
    finally:
        stream_manager.clear_pending_stream(item_id)
        stream_manager.unregister_chat(item_id, events.append)
        agent_session_manager.remove_session(item_id)

    assert call_count["value"] == 1
    assert _non_status_event_types(events) == [
        "terminal_output",
        "agent_action",
        "agent_tool_result",
        "terminal_output",
    ]
    non_status_events = [event for event in events if event["type"] != "agent_status"]
    assert non_status_events[-1]["type"] == "terminal_output"
    assert command in non_status_events[-1]["content"]
    return
    assert events[-1]["type"] == "terminal_output"
    assert command in events[-1]["content"]


def test_command_result_after_echo_resumes_next_terminal_turn(
    db: Session,
    monkeypatch,
) -> None:
    from app.services.agent import session as session_module

    item, handler = _create_linked_item_and_handler(db)
    item_id = str(item.id)
    handler_id = str(handler.id)
    tool_name = "mcp_local_execute_command"
    command = 'find /app -name "cron_job.py" -type f 2>/dev/null'
    completion_inputs: list[str] = []
    events: list[dict] = []

    fake_agent = _make_fake_agent(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Send a command to the terminal",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        execute_tool_result={
            "success": True,
            "result": [{"type": "text", "text": f"command sent: {command}"}],
        },
    )

    call_count = {"value": 0}

    def fake_command_completion(**kwargs):
        call_count["value"] += 1
        completion_inputs.append(kwargs["messages"][-1]["content"])
        if call_count["value"] == 1:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="准备执行定位命令",
                            tool_calls=[
                                SimpleNamespace(
                                    id="call_1",
                                    function=SimpleNamespace(
                                        name=tool_name,
                                        arguments='{"command":"find /app -name \\"cron_job.py\\" -type f 2>/dev/null"}',
                                    ),
                                )
                            ],
                        )
                    )
                ]
            )

        if call_count["value"] == 2:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="已定位到 cron_job.py",
                            tool_calls=None,
                        )
                    )
                ]
            )

        raise AssertionError("unexpected extra completion after real terminal feedback")

    agent_session_manager.remove_session(item_id)
    monkeypatch.setattr(session_module.AgentSession, "get_agent", lambda self: fake_agent)
    monkeypatch.setattr(session_module, "completion", fake_command_completion)
    monkeypatch.setattr(
        session_module.AgentSession,
        "_get_relevant_memories",
        lambda self, query, n_results=3: "",
    )
    monkeypatch.setattr(
        session_module,
        "build_terminal_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "terminal command"}],
    )

    stream_manager.register_chat(item_id, events.append)
    try:
        stream_manager.process_stream(item_id, "error: boom", handler_id)
        stream_manager.flush_pending_stream(item_id)
        stream_manager.process_stream(
            item_id,
            f"[2026-04-02 04:04:29] # # {command}",
            handler_id,
        )
        stream_manager.flush_pending_stream(item_id)
        stream_manager.process_stream(item_id, "/app/jobs/cron_job.py", handler_id)
        stream_manager.flush_pending_stream(item_id)
    finally:
        stream_manager.clear_pending_stream(item_id)
        stream_manager.unregister_chat(item_id, events.append)
        agent_session_manager.remove_session(item_id)

    assert call_count["value"] == 2
    assert len(completion_inputs) == 2
    assert completion_inputs[0].endswith("error: boom")
    assert completion_inputs[1].endswith("/app/jobs/cron_job.py")
    assert _non_status_event_types(events) == [
        "terminal_output",
        "agent_action",
        "agent_tool_result",
        "terminal_output",
        "terminal_output",
        "agent_response",
    ]
    non_status_events = [event for event in events if event["type"] != "agent_status"]
    assert non_status_events[-1]["type"] == "agent_response"
    assert non_status_events[-1]["content"].endswith("cron_job.py")
    return
    assert events[-1]["type"] == "agent_response"
    assert events[-1]["content"] == "已定位到 cron_job.py"


def test_pending_command_uses_raw_log_feedback_when_filtered_output_is_empty(
    db: Session,
    monkeypatch,
) -> None:
    from app.services.agent import session as session_module

    item, handler = _create_linked_item_and_handler(db)
    item_id = str(item.id)
    handler_id = str(handler.id)
    tool_name = "mcp_local_execute_command"
    completion_inputs: list[str] = []
    events: list[dict] = []

    fake_agent = _make_fake_agent(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Send a command to the terminal",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        execute_tool_result={
            "success": True,
            "result": [{"type": "text", "text": "command sent: find cron_job.py"}],
        },
    )

    call_count = {"value": 0}

    def fake_command_completion(**kwargs):
        call_count["value"] += 1
        completion_inputs.append(kwargs["messages"][-1]["content"])
        if call_count["value"] == 1:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="准备执行定位命令",
                            tool_calls=[
                                SimpleNamespace(
                                    id="call_1",
                                    function=SimpleNamespace(
                                        name=tool_name,
                                        arguments='{"command":"find /app -name \\"cron_job.py\\" -type f 2>/dev/null"}',
                                    ),
                                )
                            ],
                        )
                    )
                ]
            )

        if call_count["value"] == 2:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="已从原生日志定位到 /app/src/cron_job.py",
                            tool_calls=None,
                        )
                    )
                ]
            )

        raise AssertionError("unexpected extra completion after raw log feedback")

    agent_session_manager.remove_session(item_id)
    monkeypatch.setattr(session_module.AgentSession, "get_agent", lambda self: fake_agent)
    monkeypatch.setattr(session_module, "completion", fake_command_completion)
    monkeypatch.setattr(
        session_module.AgentSession,
        "_get_relevant_memories",
        lambda self, query, n_results=3: "",
    )
    monkeypatch.setattr(
        session_module,
        "build_terminal_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "terminal command"}],
    )
    monkeypatch.setattr(
        session_module.AgentSession,
        "_consume_pending_log_delta",
        lambda self: "[2026-04-02 05:35:18] /app/src/cron_job.py\n",
    )

    stream_manager.register_chat(item_id, events.append)
    try:
        stream_manager.process_stream(item_id, "error: boom", handler_id)
        stream_manager.flush_pending_stream(item_id)
        stream_manager.process_stream(
            item_id,
            "",
            handler_id,
            raw_output="[2026-04-02 05:35:18] /app/src/cron_job.py\n",
        )
        stream_manager.flush_pending_stream(item_id)
    finally:
        stream_manager.clear_pending_stream(item_id)
        stream_manager.unregister_chat(item_id, events.append)
        agent_session_manager.remove_session(item_id)

    assert call_count["value"] == 2
    assert len(completion_inputs) == 2
    assert "/app/src/cron_job.py" in completion_inputs[1]
    assert _non_status_event_types(events) == [
        "terminal_output",
        "agent_action",
        "agent_tool_result",
        "agent_response",
    ]


def test_publish_stream_writes_log_subscribers_before_agent_handler(monkeypatch) -> None:
    from app.services.socket_pool.subscription_center import subscription_center

    item_id = "item-order-test"
    call_order: list[str] = []

    sub_id = subscription_center.subscribe(
        item_id,
        lambda event: call_order.append("subscriber"),
        subscriber_type="test_order",
    )
    monkeypatch.setattr(
        subscription_center,
        "_trigger_agent_handler",
        lambda item_uuid, data: call_order.append("agent"),
    )

    try:
        subscription_center.publish_stream(item_id, {"stdout": "line 1\n"})
    finally:
        subscription_center.unsubscribe(sub_id)

    assert call_order == ["subscriber", "agent"]


def test_terminal_prompt_matches_relevant_skills_instead_of_loading_all_skills(monkeypatch) -> None:
    from app.services.agent import session as session_module

    relevant_skill = SimpleNamespace(
        category="general",
        action=SimpleNamespace(prompt="relevant skill prompt"),
    )
    unrelated_skill = SimpleNamespace(
        category="general",
        action=SimpleNamespace(prompt="unrelated heavy skill prompt"),
    )

    fake_agent = SimpleNamespace(
        match_skills=lambda query: [relevant_skill]
        if "can't open file" in query
        else [],
        get_skills=lambda: [relevant_skill, unrelated_skill],
        get_skip_memory_tools=lambda: [],
    )

    monkeypatch.setattr(session_module, "get_system_prompt", lambda agent: "system prompt")
    monkeypatch.setattr(
        session_module.AgentSession,
        "_get_relevant_memories",
        lambda self, query, n_results=3: "",
    )
    monkeypatch.setattr(
        session_module,
        "build_terminal_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "terminal command"}],
    )

    session = session_module.AgentSession("item-1", "handler-1")
    messages = session._build_terminal_messages(
        fake_agent,
        session_module.InputMessage(
            input_type=session_module.InputType.TERMINAL,
            content="python: can't open file '/app/items/5/cron_job.py'",
        ),
    )

    assert messages[0]["role"] == "system"
    assert "relevant skill prompt" in messages[0]["content"]
    assert "unrelated heavy skill prompt" not in messages[0]["content"]


def test_terminal_prompt_skips_long_term_memories_for_filtered_and_raw_feedback(monkeypatch) -> None:
    from app.services.agent import session as session_module
    from app.services.agent.prompts import builder as prompt_builder

    fake_agent = SimpleNamespace(
        match_skills=lambda query: [],
        get_skills=lambda: [],
        get_skip_memory_tools=lambda: [],
    )

    monkeypatch.setattr(prompt_builder, "get_system_prompt", lambda agent: "system prompt")
    monkeypatch.setattr(
        prompt_builder.vector_store,
        "search_memories",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("terminal prompts should not query long-term memories")
        ),
    )

    session = session_module.AgentSession("item-1", "handler-1")

    filtered_messages = session._build_terminal_messages(
        fake_agent,
        session_module.InputMessage(
            input_type=session_module.InputType.TERMINAL,
            content="error: boom",
        ),
    )
    raw_feedback_messages = session._build_terminal_messages(
        fake_agent,
        session_module.InputMessage(
            input_type=session_module.InputType.TERMINAL,
            content="",
        ),
        "ls",
        terminal_source=session_module.TERMINAL_SOURCE_RAW_FEEDBACK,
    )

    assert filtered_messages[-1] == {"role": "user", "content": "终端过滤输出:\nerror: boom"}
    assert any(
        message["role"] == "system"
        and "不要依赖长期记忆猜测" in message["content"]
        for message in raw_feedback_messages
    )


def test_terminal_session_stops_repeated_identical_log_reads(
    db: Session,
    monkeypatch,
) -> None:
    from app.services.agent import session as session_module

    item, handler = _create_linked_item_and_handler(db)
    item_id = str(item.id)
    handler_id = str(handler.id)
    tool_name = "mcp_local_read_terminal_log"
    events: list[dict] = []

    fake_agent = _make_fake_agent(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Read terminal log",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        execute_tool_result={
            "success": True,
            "result": [{"type": "text", "text": "same log content"}],
        },
    )

    call_count = {"value": 0}

    def fake_log_completion(**_kwargs):
        call_count["value"] += 1
        if call_count["value"] > 3:
            raise AssertionError("loop guard should stop repeated log reads")

        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="检查日志",
                        tool_calls=[
                            SimpleNamespace(
                                id=f"call_{call_count['value']}",
                                function=SimpleNamespace(
                                    name=tool_name,
                                    arguments="{}",
                                ),
                            )
                        ],
                    )
                )
            ]
        )

    agent_session_manager.remove_session(item_id)
    monkeypatch.setattr(session_module.AgentSession, "get_agent", lambda self: fake_agent)
    monkeypatch.setattr(session_module, "completion", fake_log_completion)
    monkeypatch.setattr(
        session_module.AgentSession,
        "_get_relevant_memories",
        lambda self, query, n_results=3: "",
    )
    monkeypatch.setattr(
        session_module,
        "build_terminal_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "terminal command"}],
    )
    monkeypatch.setattr(
        session_module,
        "build_terminal_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "error: boom"}],
    )
    try:
        session = agent_session_manager.get_or_create_session(item_id, handler_id)
        session.add_output_callback(events.append)
        session.process_input(
            session_module.InputMessage(
                input_type=session_module.InputType.TERMINAL,
                content="error: boom",
            )
        )
    finally:
        agent_session_manager.remove_session(item_id)

    assert call_count["value"] == 3
    assert _non_status_event_types(events) == ["terminal_output", "agent_warning"]
    assert events[-2]["type"] == "agent_warning"
    assert "日志没有新内容" in events[-2]["content"]


def test_abort_route_clears_pending_terminal_batch_before_flush(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    item, handler = _create_linked_item_and_handler(db)
    item_id = str(item.id)
    handler_id = str(handler.id)

    agent_session_manager.remove_session(item_id)

    stream_manager.process_stream(item_id, "error: boom", handler_id)

    response = client.post(
        f"{settings.API_V1_STR}/chat/{item.id}/abort",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200

    stream_manager.flush_pending_stream(item_id)

    response = client.get(
        f"{settings.API_V1_STR}/memory/{item.id}/session",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200

    messages = response.json()["messages"]
    assert [message["type"] for message in messages] == ["agent_warning"]
    assert messages[0]["content"] == "本次会话已中断"
