import asyncio
import json
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


def _sse_payloads(chunks: list[str]) -> list[dict]:
    payloads: list[dict] = []
    for chunk in chunks:
        if not chunk.startswith("data: "):
            continue
        payloads.append(json.loads(chunk[6:].strip()))
    return payloads


def test_tool_loop_detection_ignores_changing_workflow_notes() -> None:
    from app.api.routes import chat as chat_route

    history: list[tuple[str, str]] = []
    for index in range(2):
        detected, _ = chat_route._detect_tool_loop(
            history,
            "mcp_local_update_task_workflow",
            json.dumps(
                {
                    "action": "record_progress",
                    "note": f"progress note {index}",
                }
            ),
        )
        assert detected is False

    detected, reason = chat_route._detect_tool_loop(
        history,
        "mcp_local_update_task_workflow",
        json.dumps(
            {
                "action": "record_progress",
                "note": "another differently worded note",
            }
        ),
    )

    assert detected is True
    assert "mcp_local_update_task_workflow" in reason


def test_explicit_web_qq_send_accepts_visible_context_reference() -> None:
    from app.api.routes import chat as chat_route

    assert chat_route._explicit_web_qq_send_requested(
        "跟群里的 baka 说服务器没开",
        {"reply_to": "baka", "text": "服务器没开"},
    )
    assert chat_route._explicit_web_qq_send_requested(
        "帮我转发过去",
        {"reply_to": "baka", "text": "服务器没开"},
    )
    assert chat_route._explicit_web_qq_send_requested(
        "发你好",
        {"reply_to": "baka", "text": "你好"},
    )
    assert not chat_route._explicit_web_qq_send_requested(
        "现在呢",
        {"reply_to": "baka", "text": "误发"},
    )


def test_short_send_follow_up_inherits_recent_qq_tool_context() -> None:
    from app.api.routes import chat as chat_route
    from app.services.agent.tool_selection import select_tools_for_turn

    history = [
        chat_route.ChatMessage(role="user", content="帮我往群里发咕咕嘎嘎"),
        chat_route.ChatMessage(role="assistant", content="你想发什么内容？"),
    ]
    query = chat_route._build_tool_selection_query("发你好", history)
    tools = [
        {
            "type": "function",
            "function": {"name": "mcp_robot_send_message"},
        },
        {
            "type": "function",
            "function": {"name": "mcp_local_execute_command"},
        },
    ]
    selected = select_tools_for_turn(tools, source="web", query=query)

    assert [tool["function"]["name"] for tool in selected] == [
        "mcp_robot_send_message"
    ]
    assert chat_route._build_tool_selection_query("现在呢", history) == "现在呢"


def test_immediate_qq_forward_does_not_need_pending_reply() -> None:
    from app.api.routes import chat as chat_route

    tools = [
        {
            "type": "function",
            "function": {"name": "mcp_robot_send_message"},
        }
    ]
    assert chat_route._is_immediate_web_qq_forward_request(
        "发群里说个你好",
        source_type="web",
        tools=tools,
    )
    assert not chat_route._is_immediate_web_qq_forward_request(
        "Java 安装完成后发群里说装好了",
        source_type="web",
        tools=tools,
    )


def test_web_chat_keeps_visible_qq_targets_without_active_qq_context() -> None:
    from app.plugins.robot.agent.integration import RobotAgentIntegration

    context = SimpleNamespace(
        robot_id="",
        robot_known_targets=[],
        current_user_id="user-1",
        current_user_is_superuser=True,
        item_id="item-1",
        robot_context_token="",
        robot_backend_target_resolution_enabled=True,
    )
    agent = SimpleNamespace(_context=context)
    integration = RobotAgentIntegration()
    integration.extract_context_targets(
        agent,
        [
            {
                "role": "user",
                "content": (
                    "[Robot message; conversation=group:770362397; "
                    "sender=baka (1874419565)]\n服务器开了吗"
                ),
            }
        ],
    )

    assert context.robot_known_targets == [
        {
            "conversation": "group:770362397",
            "target_type": "group",
            "target_id": "770362397",
            "sender": "baka (1874419565)",
        }
    ]
    args: dict = {}
    integration.inject_tool_args(
        agent,
        server_name="robot",
        tool_name="send_message",
        args=args,
    )
    assert args["_robot_known_targets"] == context.robot_known_targets
    assert integration._has_delivery_context(agent, []) is True


def test_generate_stream_allows_short_web_forward_follow_up_to_visible_qq_target(
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route
    from app.services.agent.reply_ticket import reply_ticket_manager

    item, handler = _create_linked_item_and_handler(db)
    tool_name = "mcp_robot_send_message"
    pending_tool_name = "mcp_local_write_pending_reply"
    completion_calls = {"value": 0}
    executed: list[dict] = []
    fake_agent = _make_fake_agent(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": pending_tool_name,
                    "description": "Write a pending reply",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Send QQ message",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        execute_tool_result=lambda _name, args: (
            executed.append(dict(args))
            or {
                "success": True,
                "result": [
                    {
                        "type": "text",
                        "text": "Message sent to QQ group 770362397 from chat context.",
                    }
                ],
            }
        ),
    )

    def fake_completion(**_kwargs):
        completion_calls["value"] += 1
        if completion_calls["value"] == 1:
            return iter(
                [
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(
                                    content="",
                                    tool_calls=[
                                        SimpleNamespace(
                                            index=0,
                                            id="call_pending",
                                            function=SimpleNamespace(
                                                name=pending_tool_name,
                                                arguments=json.dumps(
                                                    {
                                                        "status": "working",
                                                        "request_summary": "发群里说个你好",
                                                        "task_plan": [
                                                            "写入待回复队列",
                                                            "发送消息到QQ群",
                                                            "确认发送成功",
                                                        ],
                                                    },
                                                    ensure_ascii=False,
                                                ),
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
        if completion_calls["value"] == 2:
            return iter(
                [
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(
                                    content="",
                                    tool_calls=[
                                        SimpleNamespace(
                                            index=0,
                                            id="call_forward",
                                            function=SimpleNamespace(
                                                name=tool_name,
                                                arguments=json.dumps(
                                                    {
                                                        "reply_to": "baka",
                                                        "text": "你好",
                                                    },
                                                    ensure_ascii=False,
                                                ),
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
                            delta=SimpleNamespace(
                                content="已经转发。",
                                tool_calls=None,
                            ),
                            finish_reason="stop",
                        )
                    ]
                )
            ]
        )

    monkeypatch.setattr(chat_route, "completion", fake_completion)
    monkeypatch.setattr(
        chat_route,
        "build_chat_turn_messages",
        lambda *args, **kwargs: [
            {
                "role": "user",
                "content": (
                    "[Robot message; conversation=group:770362397; "
                    "sender=baka (1874419565)]\n服务器开了吗"
                ),
            },
            {"role": "user", "content": "发你好"},
        ],
    )
    monkeypatch.setattr(chat_route, "_create_agent_task_plan", lambda *args, **kwargs: None)

    reply_ticket_manager.reset()
    try:
        chunks = list(
            chat_route.generate_stream(
                message="发你好",
                history=[
                    chat_route.ChatMessage(
                        role="user",
                        content="帮我往群里的 baka 发一条消息",
                    ),
                    chat_route.ChatMessage(
                        role="assistant",
                        content="你想发什么内容？",
                    ),
                ],
                handler=handler,
                item_id=str(item.id),
                agent=fake_agent,
                source_type="web",
            )
        )
        payloads = _sse_payloads(chunks)

        assert completion_calls["value"] == 2
        assert len(executed) == 1
        assert executed[0]["reply_to"] == "baka"
        assert executed[0]["text"] == "你好"
        assert reply_ticket_manager.list_pending_replies(str(item.id)) == []
        assert any(event.get("type") == "agent_qq_reply" for event in payloads)
        assert not any(event.get("type") == "agent_warning" for event in payloads)
        assert not any(event.get("type") == "agent_response" for event in payloads)
    finally:
        reply_ticket_manager.reset()


def test_generate_stream_replaces_fabricated_tool_transcript_when_no_tool_ran(
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route

    item, handler = _create_linked_item_and_handler(db)
    fake_agent = _make_fake_agent(tools=[])
    fabricated = (
        "Executing tool: mcp_local_append_pending_reply\n"
        "```json\n{\"group_id\":\"770362397\",\"content\":\"你好\"}\n```\n"
        "Executing tool: mcp_robot_send_group_message\n"
        "已经发送成功。"
    )

    monkeypatch.setattr(
        chat_route,
        "completion",
        lambda **kwargs: iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content=fabricated,
                                tool_calls=None,
                            ),
                            finish_reason="stop",
                        )
                    ]
                )
            ]
        ),
    )
    monkeypatch.setattr(
        chat_route,
        "build_chat_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "发你好"}],
    )
    monkeypatch.setattr(chat_route, "_create_agent_task_plan", lambda *args, **kwargs: None)

    chunks = list(
        chat_route.generate_stream(
            message="发你好",
            history=[],
            handler=handler,
            item_id=str(item.id),
            agent=fake_agent,
            source_type="web",
        )
    )
    payloads = _sse_payloads(chunks)
    responses = [
        event.get("content", "")
        for event in payloads
        if event.get("type") == "agent_response"
    ]

    assert responses == ["我没有实际调用工具，因此这次外部操作没有执行。"]
    assert not any("mcp_local_append_pending_reply" in chunk for chunk in chunks)
    assert not any("mcp_robot_send_group_message" in chunk for chunk in chunks)
    assert not any("发送成功" in chunk for chunk in chunks)


def test_generate_stream_forces_live_terminal_status_tool(
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route
    from app.services.terminal_runtime_state import TerminalRuntimeState

    item, handler = _create_linked_item_and_handler(db)
    completion_calls = {"value": 0}
    tool_calls = []
    tool_name = "mcp_local_get_terminal_status"
    fake_agent = _make_fake_agent(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Read live terminal state",
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
                        "text": "终端未启动或未连接。Backend 与 Daemon 当前没有 Socket 连接。",
                    }
                ],
            }
        ),
    )

    def chunk(*, content="", tool_calls_value=None):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=content,
                        tool_calls=tool_calls_value,
                    ),
                    finish_reason="stop",
                )
            ]
        )

    def fake_completion(**kwargs):
        completion_calls["value"] += 1
        if completion_calls["value"] == 1:
            return iter([chunk(content="终端开着，当前可用。")])
        if completion_calls["value"] == 2:
            assert any(
                "requires authoritative live terminal evidence" in message["content"]
                for message in kwargs["messages"]
                if message.get("role") == "system"
            )
            return iter(
                [
                    chunk(
                        tool_calls_value=[
                            SimpleNamespace(
                                index=0,
                                id="call_terminal_status",
                                function=SimpleNamespace(name=tool_name, arguments="{}"),
                            )
                        ]
                    )
                ]
            )
        return iter([chunk(content="终端没开，Backend 和 Daemon 当前没有连接。")])

    monkeypatch.setattr(chat_route, "completion", fake_completion)
    monkeypatch.setattr(
        chat_route,
        "build_chat_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "终端开了吗"}],
    )
    monkeypatch.setattr(
        chat_route,
        "get_terminal_runtime_state",
        lambda item_id: TerminalRuntimeState(
            item_id=item_id,
            active=False,
            daemon_connected=False,
            reason="daemon_not_connected",
        ),
    )
    monkeypatch.setattr(chat_route, "_create_agent_task_plan", lambda *args, **kwargs: None)

    chunks = list(
        chat_route.generate_stream(
            message="终端开了吗",
            history=[],
            handler=handler,
            item_id=str(item.id),
            agent=fake_agent,
        )
    )

    assert completion_calls["value"] == 3
    assert len(tool_calls) == 1
    assert tool_calls[0][0] == tool_name
    assert tool_calls[0][1]["item_id"] == str(item.id)
    assert any("终端没开" in chunk_text for chunk_text in chunks)
    assert not any("终端开着，当前可用" in chunk_text for chunk_text in chunks)


def test_generate_stream_forces_terminal_action_tool_before_claiming_execution(
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route
    from app.services.agent.session import COMMAND_DISPATCH_FAILURE_MESSAGE

    item, handler = _create_linked_item_and_handler(db)
    completion_calls = {"value": 0}
    tool_calls = []
    tool_name = "mcp_local_run_job"
    fake_agent = _make_fake_agent(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Run one shell job",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        execute_tool_result=lambda name, args: (
            tool_calls.append((name, dict(args)))
            or {
                "success": True,
                "result": [{"type": "text", "text": COMMAND_DISPATCH_FAILURE_MESSAGE}],
            }
        ),
    )

    def fake_completion(**kwargs):
        completion_calls["value"] += 1
        if completion_calls["value"] == 1:
            return iter(
                [
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(
                                    content="我先执行 ls，等一下给你结果。",
                                    tool_calls=None,
                                ),
                                finish_reason="stop",
                            )
                        ]
                    )
                ]
            )
        assert any(
            "requires authoritative live terminal evidence" in message["content"]
            for message in kwargs["messages"]
            if message.get("role") == "system"
        )
        return iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="",
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        id="call_ls",
                                        function=SimpleNamespace(
                                            name=tool_name,
                                            arguments='{"command":"ls"}',
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
    monkeypatch.setattr(chat_route, "completion", fake_completion)
    monkeypatch.setattr(
        chat_route,
        "build_chat_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "跑一下ls"}],
    )
    monkeypatch.setattr(chat_route, "_create_agent_task_plan", lambda *args, **kwargs: None)

    try:
        chunks = list(
            chat_route.generate_stream(
                message="跑一下ls",
                history=[],
                handler=handler,
                item_id=str(item.id),
                agent=fake_agent,
            )
        )
    finally:
        agent_session_manager.remove_session(str(item.id))

    assert completion_calls["value"] == 2
    assert len(tool_calls) == 1
    assert tool_calls[0][0] == tool_name
    assert tool_calls[0][1]["command"] == "ls"
    assert any(COMMAND_DISPATCH_FAILURE_MESSAGE in chunk_text for chunk_text in chunks)
    assert not any("等一下给你结果" in chunk_text for chunk_text in chunks)


def test_generate_stream_executes_dsml_tool_call_without_exposing_markup(
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route

    item, handler = _create_linked_item_and_handler(db)
    tool_name = "mcp_local_update_task_workflow"
    completion_calls = {"value": 0}
    executed: list[dict] = []
    fake_agent = _make_fake_agent(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Update workflow progress",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        execute_tool_result=lambda _name, args: (
            executed.append(dict(args))
            or {
                "success": True,
                "result": [{"type": "text", "text": "progress recorded"}],
            }
        ),
    )

    def fake_completion(**_kwargs):
        completion_calls["value"] += 1
        content = (
            '<｜｜DSML｜｜tool_calls>\n'
            f'<｜｜DSML｜｜invoke name="{tool_name}">\n'
            '<｜｜DSML｜｜parameter name="action" string="true">'
            'complete_current_step</｜｜DSML｜｜parameter>\n'
            '<｜｜DSML｜｜parameter name="note" string="true">'
            '结果检查完成，无需QQ回复</｜｜DSML｜｜parameter>\n'
            '</｜｜DSML｜｜invoke>\n'
            '</｜｜DSML｜｜tool_calls>'
            if completion_calls["value"] == 1
            else "处理完成"
        )
        return iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content=content, tool_calls=None),
                            finish_reason="stop",
                        )
                    ]
                )
            ]
        )

    monkeypatch.setattr(chat_route, "completion", fake_completion)
    monkeypatch.setattr(
        chat_route,
        "select_tools_for_turn",
        lambda available_tools, **_kwargs: available_tools,
    )
    monkeypatch.setattr(
        chat_route,
        "build_chat_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "更新任务状态"}],
    )
    monkeypatch.setattr(chat_route, "_create_agent_task_plan", lambda *args, **kwargs: None)

    chunks = list(
        chat_route.generate_stream(
            message="更新任务状态",
            history=[],
            handler=handler,
            item_id=str(item.id),
            agent=fake_agent,
        )
    )
    payloads = _sse_payloads(chunks)

    assert completion_calls["value"] == 2
    assert len(executed) == 1
    assert executed[0]["action"] == "complete_current_step"
    assert executed[0]["note"] == "结果检查完成，无需QQ回复"
    assert executed[0]["item_id"] == str(item.id)
    assert any(
        payload.get("type") == "agent_response"
        and payload.get("content") == "处理完成"
        for payload in payloads
    )
    assert not any("DSML" in chunk for chunk in chunks)


def test_generate_stream_reports_instead_of_exposing_tool_loop_warning(
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route

    item, handler = _create_linked_item_and_handler(db)
    tool_name = "mcp_local_update_task_workflow"
    stream_calls = {"value": 0}
    executed_tools: list[dict] = []

    fake_agent = _make_fake_agent(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Update workflow progress",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        execute_tool_result=lambda _name, args: (
            executed_tools.append(dict(args))
            or {
                "success": True,
                "result": [{"type": "text", "text": "progress recorded"}],
            }
        ),
    )

    def fake_completion(**kwargs):
        if kwargs.get("stream") is False:
            assert "tools" not in kwargs
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="这次操作还没有完成，我已停止重复执行，请稍后重试。",
                            tool_calls=None,
                        )
                    )
                ]
            )

        stream_calls["value"] += 1
        arguments = json.dumps(
            {
                "action": "record_progress",
                "note": f"wording changed on call {stream_calls['value']}",
            }
        )
        return iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="",
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        id=f"call_{stream_calls['value']}",
                                        function=SimpleNamespace(
                                            name=tool_name,
                                            arguments=arguments,
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

    monkeypatch.setattr(chat_route, "completion", fake_completion)
    monkeypatch.setattr(
        chat_route,
        "build_chat_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "test operation"}],
    )
    monkeypatch.setattr(chat_route, "_create_agent_task_plan", lambda *args, **kwargs: None)

    chunks = list(
        chat_route.generate_stream(
            message="测试操作",
            history=[],
            handler=handler,
            item_id=str(item.id),
            agent=fake_agent,
        )
    )
    payloads = _sse_payloads(chunks)

    assert stream_calls["value"] == 3
    assert len(executed_tools) == 2
    assert any(
        event.get("type") == "agent_response"
        and "停止重复执行" in event.get("content", "")
        for event in payloads
    )
    assert not any(event.get("type") == "agent_warning" for event in payloads)
    assert not any("max iteration limit" in chunk for chunk in chunks)
    assert not any("Detected repeated tool loop" in chunk for chunk in chunks)


def test_generate_stream_reports_after_unique_tool_calls_exhaust_budget(
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route

    item, handler = _create_linked_item_and_handler(db)
    tool_name = "mcp_local_list_memories"
    stream_calls = {"value": 0}

    fake_agent = _make_fake_agent(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Inspect memory",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        execute_tool_result={
            "success": True,
            "result": [{"type": "text", "text": "memory page"}],
        },
    )

    def fake_completion(**kwargs):
        if kwargs.get("stream") is False:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="检查没有完成，我已停止继续调用工具。",
                            tool_calls=None,
                        )
                    )
                ]
            )

        stream_calls["value"] += 1
        if "tools" not in kwargs:
            return iter(
                [
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(
                                    content="检查完成，最后一次工具结果已确认。",
                                    tool_calls=None,
                                ),
                                finish_reason="stop",
                            )
                        ]
                    )
                ]
            )
        arguments = json.dumps({"query": f"unique-{stream_calls['value']}"})
        return iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="",
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        id=f"call_{stream_calls['value']}",
                                        function=SimpleNamespace(
                                            name=tool_name,
                                            arguments=arguments,
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

    monkeypatch.setattr(chat_route, "completion", fake_completion)
    monkeypatch.setattr(
        chat_route,
        "build_chat_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "test operation"}],
    )
    monkeypatch.setattr(chat_route, "_create_agent_task_plan", lambda *args, **kwargs: None)

    chunks = list(
        chat_route.generate_stream(
            message="测试操作",
            history=[],
            handler=handler,
            item_id=str(item.id),
            agent=fake_agent,
        )
    )
    payloads = _sse_payloads(chunks)

    assert stream_calls["value"] == chat_route.MAX_ITERATIONS + 1
    assert any(
        event.get("type") == "agent_response"
        and "最后一次工具结果已确认" in event.get("content", "")
        for event in payloads
    )
    assert not any(event.get("type") == "agent_warning" for event in payloads)
    assert not any("max iteration limit" in chunk for chunk in chunks)


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

    assert len(tool_calls) == 1
    called_tool_name, called_tool_args = tool_calls[0]
    assert called_tool_name == tool_name
    assert called_tool_args.pop("_reply_ticket_id")
    assert called_tool_args == {"command": "pwd", "item_id": str(item.id)}
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
    assert len(tool_calls) == 1
    called_tool_name, called_tool_args = tool_calls[0]
    assert called_tool_name == tool_name
    assert called_tool_args.pop("_reply_ticket_id")
    assert called_tool_args == {
        "command": "apt update",
        "item_id": str(item.id),
    }
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
    assert len(tool_calls) == 1
    reply_ticket_id = tool_calls[0][1].pop("_reply_ticket_id")
    assert reply_ticket_id
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


def test_generate_stream_delivers_qq_final_response_via_reply_ticket(
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route
    from app.plugins.robot.bridge_client import robot_bridge_client
    from app.plugins.robot.contracts import RobotReplyTarget
    from app.plugins.robot.conversation_memory import robot_conversation_memory
    from app.plugins.robot.mcp.context import (
        RobotMCPContext,
        register_robot_mcp_context,
        unregister_robot_mcp_context,
    )
    from app.services.agent.reply_ticket import reply_ticket_manager

    item, handler = _create_linked_item_and_handler(db)
    target = RobotReplyTarget(
        target_type="group",
        target_id="770362397",
        metadata={"conversation": {"type": "group", "id": "770362397"}},
    )
    token = register_robot_mcp_context(
        RobotMCPContext(
            robot_id="robot-1",
            sender_key="onebot_v11:group:770362397:2537134688",
            reply_target=target,
            conversation_key="group:770362397",
            conversation_generation=3,
        )
    )
    fake_agent = _make_fake_agent(tools=[])
    fake_agent._context = SimpleNamespace(
        model="fake-model",
        api_key=None,
        api_url=None,
        robot_id="robot-1",
        robot_context_token=token,
        robot_conversation_key="group:770362397",
        agent_profile={},
        enabled_knowledge_files=[],
        skill_revision=0,
        reply_ticket_id="",
    )
    sent: list[tuple[str, RobotReplyTarget, str]] = []
    memory_writes: list[tuple[str, str, str]] = []

    monkeypatch.setattr(chat_route, "completion", _fake_stream_completion)
    monkeypatch.setattr(
        chat_route,
        "build_chat_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "qq message"}],
    )
    monkeypatch.setattr(chat_route, "extract_integration_context_targets", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_route, "record_integration_context_targets", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_route, "get_relevant_memories", lambda *args, **kwargs: "")
    monkeypatch.setattr(chat_route, "extract_important_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_route, "_create_agent_task_plan", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_route, "_append_conversation_memory", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        robot_bridge_client,
        "send_message",
        lambda robot_id, target, text: sent.append((str(robot_id), target, text)),
    )
    monkeypatch.setattr(
        robot_conversation_memory,
        "append_assistant_message",
        lambda robot_id, conversation_key, text: memory_writes.append(
            (str(robot_id), conversation_key, text)
        ),
    )
    reply_ticket_manager.reset()

    try:
        chunks = list(
            chat_route.generate_stream(
                message="[Robot message; conversation=group:770362397]\n说话",
                history=[],
                handler=handler,
                item_id=str(item.id),
                agent=fake_agent,
                include_hidden_tool_results=True,
                latest_only_context=True,
                source_type="qq",
            )
        )
    finally:
        unregister_robot_mcp_context(token)
        reply_ticket_manager.reset()

    payloads = _sse_payloads(chunks)
    assert [(robot_id, target.target_type, target.target_id, text) for robot_id, target, text in sent] == [
        ("robot-1", "group", "770362397", "Shared reply")
    ]
    assert memory_writes == [("robot-1", "group:770362397", "Shared reply")]
    assert any(
        payload.get("type") == "agent_qq_reply" and "Shared reply" in payload.get("content", "")
        for payload in payloads
    )
    assert any(
        payload.get("type") == "agent_tool_result"
        and payload.get("hidden") is True
        and payload.get("content") == "Message sent to current robot conversation."
        for payload in payloads
    )
    assert not any(payload.get("type") == "agent_response" for payload in payloads)


def test_generate_stream_stops_after_successful_qq_send_tool(
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route
    from app.plugins.robot.contracts import RobotReplyTarget
    from app.plugins.robot.mcp.context import (
        RobotMCPContext,
        register_robot_mcp_context,
        unregister_robot_mcp_context,
    )
    from app.services.agent.reply_ticket import reply_ticket_manager

    item, handler = _create_linked_item_and_handler(db)
    tool_name = "mcp_robot_send_message"
    completion_calls = {"value": 0}
    executed: list[dict] = []
    target = RobotReplyTarget(
        target_type="group",
        target_id="770362397",
        metadata={"conversation": {"type": "group", "id": "770362397"}},
    )
    token = register_robot_mcp_context(
        RobotMCPContext(
            robot_id="robot-1",
            sender_key="onebot_v11:group:770362397:2537134688",
            reply_target=target,
            conversation_key="group:770362397",
            conversation_generation=3,
        )
    )
    fake_agent = _make_fake_agent(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Send QQ message",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        execute_tool_result=lambda _name, args: (
            executed.append(dict(args))
            or {
                "success": True,
                "result": [
                    {
                        "type": "text",
                        "text": "Message sent to current robot conversation.",
                    }
                ],
            }
        ),
    )
    fake_agent._context = SimpleNamespace(
        model="fake-model",
        api_key=None,
        api_url=None,
        robot_id="robot-1",
        robot_context_token=token,
        robot_conversation_key="group:770362397",
        agent_profile={},
        enabled_knowledge_files=[],
        skill_revision=0,
        reply_ticket_id="",
    )

    def fake_completion(**_kwargs):
        completion_calls["value"] += 1
        return iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="",
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        id=f"call_send_{completion_calls['value']}",
                                        function=SimpleNamespace(
                                            name=tool_name,
                                            arguments=json.dumps(
                                                {"text": "莫西莫西，我在。"},
                                                ensure_ascii=False,
                                            ),
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

    monkeypatch.setattr(chat_route, "completion", fake_completion)
    monkeypatch.setattr(
        chat_route,
        "build_chat_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "莫西莫西"}],
    )
    monkeypatch.setattr(
        chat_route,
        "extract_integration_context_targets",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        chat_route,
        "record_integration_context_targets",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(chat_route, "get_relevant_memories", lambda *args, **kwargs: "")
    monkeypatch.setattr(chat_route, "extract_important_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_route, "_create_agent_task_plan", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_route, "_append_conversation_memory", lambda *args, **kwargs: None)
    reply_ticket_manager.reset()

    try:
        chunks = list(
            chat_route.generate_stream(
                message="[Robot message; conversation=group:770362397]\n莫西莫西",
                history=[],
                handler=handler,
                item_id=str(item.id),
                agent=fake_agent,
                include_hidden_tool_results=True,
                latest_only_context=True,
                source_type="qq",
            )
        )
    finally:
        unregister_robot_mcp_context(token)
        reply_ticket_manager.reset()

    payloads = _sse_payloads(chunks)
    assert completion_calls["value"] == 1
    assert len(executed) == 1
    assert executed[0]["text"] == "莫西莫西，我在。"
    assert sum(payload.get("type") == "agent_qq_reply" for payload in payloads) == 1
    assert any(payload.get("done") is True for payload in payloads)


def test_generate_stream_suppresses_second_qq_send_while_task_stays_active(
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route
    from app.plugins.robot.contracts import RobotReplyTarget
    from app.plugins.robot.mcp.context import (
        RobotMCPContext,
        register_robot_mcp_context,
        unregister_robot_mcp_context,
    )
    from app.services.agent.reply_ticket import reply_ticket_manager

    item, handler = _create_linked_item_and_handler(db)
    tool_name = "mcp_robot_send_message"
    completion_calls = {"value": 0}
    executed: list[dict] = []
    target = RobotReplyTarget(
        target_type="private",
        target_id="2537134688",
        metadata={"conversation": {"type": "private", "id": "2537134688"}},
    )
    token = register_robot_mcp_context(
        RobotMCPContext(
            robot_id="robot-1",
            sender_key="onebot_v11:private:2537134688",
            reply_target=target,
            conversation_key="private:2537134688",
            conversation_generation=4,
        )
    )
    fake_agent = _make_fake_agent(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Send QQ message",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        execute_tool_result=lambda _name, args: (
            executed.append(dict(args))
            or {
                "success": True,
                "result": [
                    {
                        "type": "text",
                        "text": "Message sent to current robot conversation.",
                    }
                ],
            }
        ),
    )
    fake_agent._context = SimpleNamespace(
        model="fake-model",
        api_key=None,
        api_url=None,
        robot_id="robot-1",
        robot_context_token=token,
        robot_conversation_key="private:2537134688",
        agent_profile={},
        enabled_knowledge_files=[],
        skill_revision=0,
        reply_ticket_id="",
    )

    def fake_completion(**_kwargs):
        completion_calls["value"] += 1
        if completion_calls["value"] <= 2:
            text = (
                "终端没连上，先开起来我再继续装 Java"
                if completion_calls["value"] == 1
                else "终端还没连上，开好以后我接着装 Java"
            )
            delta = SimpleNamespace(
                content="",
                tool_calls=[
                    SimpleNamespace(
                        index=0,
                        id=f"call_send_{completion_calls['value']}",
                        function=SimpleNamespace(
                            name=tool_name,
                            arguments=json.dumps({"text": text}, ensure_ascii=False),
                        ),
                    )
                ],
            )
        else:
            delta = SimpleNamespace(
                content="终端还没连上，开好以后我接着装 Java",
                tool_calls=None,
            )
        return iter(
            [
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=delta, finish_reason=None)]
                )
            ]
        )

    monkeypatch.setattr(chat_route, "completion", fake_completion)
    monkeypatch.setattr(
        chat_route,
        "build_chat_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "帮我装java"}],
    )
    monkeypatch.setattr(chat_route, "get_relevant_memories", lambda *args, **kwargs: "")
    monkeypatch.setattr(chat_route, "extract_important_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_route, "_create_agent_task_plan", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_route, "_append_conversation_memory", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        chat_route.task_workflow_manager,
        "can_finalize",
        lambda _ticket_id: (completion_calls["value"] >= 3, "task still active"),
    )
    reply_ticket_manager.reset()

    try:
        chunks = list(
            chat_route.generate_stream(
                message="[Robot message; conversation=private:2537134688]\n帮我装java",
                history=[],
                handler=handler,
                item_id=str(item.id),
                agent=fake_agent,
                include_hidden_tool_results=True,
                latest_only_context=True,
                source_type="qq",
            )
        )
    finally:
        unregister_robot_mcp_context(token)
        reply_ticket_manager.reset()

    payloads = _sse_payloads(chunks)
    assert completion_calls["value"] == 3
    assert len(executed) == 1
    assert executed[0]["text"] == "终端没连上，先开起来我再继续装 Java"
    assert sum(payload.get("type") == "agent_qq_reply" for payload in payloads) == 1
    assert not any(payload.get("type") == "agent_response" for payload in payloads)


def test_generate_stream_hides_internal_qq_background_job_callback(
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route
    from app.plugins.robot.bridge_client import robot_bridge_client
    from app.plugins.robot.contracts import RobotReplyTarget
    from app.plugins.robot.conversation_memory import robot_conversation_memory
    from app.plugins.robot.mcp.context import (
        RobotMCPContext,
        register_robot_mcp_context,
        unregister_robot_mcp_context,
    )
    from app.services.agent.reply_ticket import reply_ticket_manager

    item, handler = _create_linked_item_and_handler(db)
    target = RobotReplyTarget(
        target_type="group",
        target_id="770362397",
        metadata={
            "conversation": {"type": "group", "id": "770362397"},
            "message": {"raw_message": "check apt sources"},
        },
    )
    token = register_robot_mcp_context(
        RobotMCPContext(
            robot_id="robot-1",
            sender_key="onebot_v11:group:770362397:2537134688",
            reply_target=target,
            conversation_key="group:770362397",
            conversation_generation=3,
        )
    )
    fake_agent = _make_fake_agent(tools=[])
    fake_agent._context = SimpleNamespace(
        model="fake-model",
        api_key=None,
        api_url=None,
        robot_id="robot-1",
        robot_context_token=token,
        robot_conversation_key="group:770362397",
        agent_profile={},
        enabled_knowledge_files=[],
        skill_revision=0,
        reply_ticket_id="",
    )
    sent: list[str] = []
    memory_appends: list[tuple[str, str]] = []

    monkeypatch.setattr(chat_route, "completion", _fake_stream_completion)
    monkeypatch.setattr(
        chat_route,
        "build_chat_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "job result"}],
    )
    monkeypatch.setattr(
        chat_route,
        "extract_integration_context_targets",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        chat_route,
        "record_integration_context_targets",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(chat_route, "get_relevant_memories", lambda *args, **kwargs: "")
    monkeypatch.setattr(chat_route, "extract_important_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        chat_route,
        "_create_agent_task_plan",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("internal callback must not create a new user task plan")
        ),
    )
    monkeypatch.setattr(
        chat_route,
        "_append_conversation_memory",
        lambda item_id, **kwargs: memory_appends.append(
            (str(item_id), str(kwargs.get("user_message") or ""))
        ),
    )
    monkeypatch.setattr(
        robot_bridge_client,
        "send_message",
        lambda _robot_id, _target, text: sent.append(text),
    )
    monkeypatch.setattr(
        robot_conversation_memory,
        "append_assistant_message",
        lambda *args, **kwargs: None,
    )
    reply_ticket_manager.reset()

    internal_message = (
        "[Background terminal job result for this QQ conversation]\n"
        "Job succeeded\noutput_tail:\ndebian.sources"
    )
    try:
        chunks = list(
            chat_route.generate_stream(
                message=internal_message,
                history=[],
                handler=handler,
                item_id=str(item.id),
                agent=fake_agent,
                include_hidden_tool_results=True,
                latest_only_context=True,
                source_type="qq",
            )
        )
    finally:
        unregister_robot_mcp_context(token)
        reply_ticket_manager.reset()

    payloads = _sse_payloads(chunks)
    assert sent == ["Shared reply"]
    assert memory_appends == []
    assert not any(payload.get("type") == "chat_user" for payload in payloads)
    assert not any(internal_message in str(payload.get("content") or "") for payload in payloads)


def test_generate_stream_web_source_does_not_reuse_stale_qq_reply_ticket(
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route
    from app.plugins.robot.bridge_client import robot_bridge_client
    from app.plugins.robot.contracts import RobotReplyTarget
    from app.plugins.robot.conversation_memory import robot_conversation_memory
    from app.plugins.robot.mcp.context import (
        RobotMCPContext,
        register_robot_mcp_context,
        unregister_robot_mcp_context,
    )
    from app.services.agent.reply_ticket import reply_ticket_manager

    item, handler = _create_linked_item_and_handler(db)
    target = RobotReplyTarget(
        target_type="group",
        target_id="770362397",
        metadata={"conversation": {"type": "group", "id": "770362397"}},
    )
    token = register_robot_mcp_context(
        RobotMCPContext(
            robot_id="robot-1",
            sender_key="onebot_v11:group:770362397:2537134688",
            reply_target=target,
            conversation_key="group:770362397",
            conversation_generation=3,
        )
    )
    fake_agent = _make_fake_agent(tools=[])
    fake_agent._context = SimpleNamespace(
        model="fake-model",
        api_key=None,
        api_url=None,
        robot_id="robot-1",
        robot_context_token=token,
        robot_conversation_key="group:770362397",
        agent_profile={},
        enabled_knowledge_files=[],
        skill_revision=0,
        reply_ticket_id="",
    )
    sent: list[tuple[str, RobotReplyTarget, str]] = []
    memory_writes: list[tuple[str, str, str]] = []

    monkeypatch.setattr(chat_route, "completion", _fake_stream_completion)
    monkeypatch.setattr(
        chat_route,
        "build_chat_turn_messages",
        lambda *args, **kwargs: [{"role": "user", "content": "web message"}],
    )
    monkeypatch.setattr(chat_route, "extract_integration_context_targets", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_route, "record_integration_context_targets", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_route, "get_relevant_memories", lambda *args, **kwargs: "")
    monkeypatch.setattr(chat_route, "extract_important_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_route, "_create_agent_task_plan", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_route, "_append_conversation_memory", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        robot_bridge_client,
        "send_message",
        lambda robot_id, target, text: sent.append((str(robot_id), target, text)),
    )
    monkeypatch.setattr(
        robot_conversation_memory,
        "append_assistant_message",
        lambda robot_id, conversation_key, text: memory_writes.append(
            (str(robot_id), conversation_key, text)
        ),
    )
    reply_ticket_manager.reset()

    try:
        chunks = list(
            chat_route.generate_stream(
                message="web asks status",
                history=[],
                handler=handler,
                item_id=str(item.id),
                agent=fake_agent,
            )
        )
    finally:
        unregister_robot_mcp_context(token)
        reply_ticket_manager.reset()

    payloads = _sse_payloads(chunks)
    assert sent == []
    assert memory_writes == []
    assert any(
        payload.get("type") == "agent_response" and payload.get("content") == "Shared reply"
        for payload in payloads
    )
    assert not any(payload.get("type") == "agent_qq_reply" for payload in payloads)


def test_generate_stream_blocks_web_chat_from_reusing_qq_send_target(
    db: Session,
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route
    from app.plugins.robot.bridge_client import robot_bridge_client
    from app.services.agent.reply_ticket import reply_ticket_manager

    item, handler = _create_linked_item_and_handler(db)
    tool_name = "mcp_robot_send_message"
    fake_agent = _make_fake_agent(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Send QQ message",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        execute_tool_result=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("web chat must not execute accidental QQ send")
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
                                content="",
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        id="call_1",
                                        function=SimpleNamespace(
                                            name=tool_name,
                                            arguments='{"target_type":"group","target_id":"770362397","text":"误发"}',
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
        lambda *args, **kwargs: [{"role": "user", "content": "现在呢"}],
    )
    monkeypatch.setattr(chat_route, "get_relevant_memories", lambda *args, **kwargs: "")
    monkeypatch.setattr(chat_route, "extract_important_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_route, "_create_agent_task_plan", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        robot_bridge_client,
        "send_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("bridge send should be blocked")
        ),
    )
    reply_ticket_manager.reset()

    try:
        chunks = list(
            chat_route.generate_stream(
                message="现在呢",
                history=[],
                handler=handler,
                item_id=str(item.id),
                agent=fake_agent,
            )
        )
    finally:
        reply_ticket_manager.reset()

    payloads = _sse_payloads(chunks)
    warnings = [
        payload.get("content", "")
        for payload in payloads
        if payload.get("type") == "agent_warning"
    ]
    assert warnings == []
    assert not any("已拦截 QQ 发送" in payload.get("content", "") for payload in payloads)
    assert not any(payload.get("type") == "agent_response" for payload in payloads)


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
        if call_count["value"] == 2:
            assert any(
                "Choose the next action yourself" in str(message.get("content") or "")
                for message in kwargs["messages"]
            )
            return iter(
                [
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(
                                    content="当前终端正在执行 apt update，java -version 没有发送。",
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

    assert call_count["value"] == 2
    assert any('"type": "agent_response"' in chunk for chunk in chunks)
    assert any("apt update" in chunk and "java -version" in chunk for chunk in chunks)
    assert not any('"type": "agent_tool_result"' in chunk for chunk in chunks)
    assert not any("terminal_dependency" in chunk for chunk in chunks)
    assert not any("max iteration limit" in chunk for chunk in chunks)


def test_generate_stream_does_not_block_shell_like_input_when_console_is_active(
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

    assert len(tool_calls) == 1
    reply_ticket_id = tool_calls[0][1].pop("_reply_ticket_id")
    assert reply_ticket_id
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
    assert any('"type": "agent_response"' in chunk for chunk in chunks)
    assert any("终端未连接或未打开" in chunk for chunk in chunks)
    assert not any("暂停" in chunk or "保留当前进度" in chunk for chunk in chunks)
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
    assert captured_memory["ttl_days"] is None
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


def test_stream_chat_does_not_update_removed_task_memory_type(
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

    monkeypatch.setattr(
        chat_route.vector_store,
        "update_memory",
        fake_update_memory,
    )
    monkeypatch.setattr(
        chat_route.vector_store,
        "add_memory",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("task state must not write long-term memory")
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

    assert captured_update == {}

def test_agent_task_plan_records_reply_origin(monkeypatch) -> None:
    from app.api.routes import chat as chat_route
    from app.services.agent.task_workflow import task_workflow_manager

    handler = SimpleNamespace(id="handler-1")
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="robot-1",
            robot_conversation_key="group:770362397",
            reply_ticket_id="",
        )
    )

    task_workflow_manager.reset()
    monkeypatch.setattr(
        chat_route,
        "_plan_agent_task_titles",
        lambda handler, message, history: ["install Java", "report result"],
    )

    monkeypatch.setattr(
        chat_route.vector_store,
        "add_memory",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("task plans must not be stored as long-term memory")
        ),
    )

    plan = chat_route._create_agent_task_plan(
        "item-1",
        handler=handler,
        agent=agent,
        message="install Java",
        history=[],
        tools=[{"type": "function", "function": {"name": "mcp_local_run_job"}}],
    )

    assert plan is not None
    workflow = task_workflow_manager.get(plan.workflow_id)
    assert workflow is not None
    assert workflow.objective == "install Java"
    assert workflow.source_label == "QQ group:770362397"
    task_workflow_manager.reset()


def test_vague_start_messages_and_status_questions_do_not_create_tasks(
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route
    from app.services.agent.reply_ticket import reply_ticket_manager
    from app.services.agent.task_workflow import task_workflow_manager

    handler = SimpleNamespace(id="handler-1")
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="",
            robot_conversation_key="",
            reply_ticket_id="",
        )
    )
    tools = [{"type": "function", "function": {"name": "mcp_local_run_job"}}]
    monkeypatch.setattr(
        chat_route,
        "build_status_update_memory_candidate",
        lambda *args, **kwargs: None,
    )

    reply_ticket_manager.reset()
    task_workflow_manager.reset()
    try:
        for message in ("启动", "启动了", "你在启动什么"):
            ticket = reply_ticket_manager.create_for_agent(
                agent,
                item_id="item-1",
                handler_id="handler-1",
                message=message,
                source_type="web",
            )
            plan = chat_route._create_agent_task_plan(
                "item-1",
                handler=handler,
                agent=agent,
                message=message,
                history=[],
                tools=tools,
                reply_ticket_id=ticket.ticket_id,
            )
            assert plan is None

        assert task_workflow_manager.snapshot("item-1") == []
        assert reply_ticket_manager.list_pending_replies("item-1") == []
    finally:
        reply_ticket_manager.reset()
        task_workflow_manager.reset()


def test_final_pending_qq_report_is_delivered_and_removed_by_backend(
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route
    from app.services.agent.reply_ticket import SOURCE_QQ

    ticket = SimpleNamespace(
        ticket_id="ticket-java",
        source_type=SOURCE_QQ,
        pending_reply_active=True,
    )
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        chat_route.reply_ticket_manager,
        "get",
        lambda ticket_id: ticket if ticket_id == "ticket-java" else None,
    )
    monkeypatch.setattr(
        chat_route.reply_ticket_manager,
        "send_pending_reply",
        lambda ticket_id, content: (
            sent.append((ticket_id, content)) or True,
            "QQ group:770362397",
        ),
    )
    monkeypatch.setattr(
        chat_route.reply_ticket_manager,
        "deliver",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("pending replies must use send_pending_reply")
        ),
    )
    monkeypatch.setattr(
        chat_route,
        "_persist_and_broadcast_event",
        lambda _item_id, **event: event,
    )

    events = chat_route._deliver_reply_ticket_final_response(
        agent=SimpleNamespace(),
        item_id="item-1",
        content="Java 17 已安装完成。",
        include_hidden_tool_results=False,
        reply_ticket_id="ticket-java",
    )

    assert sent == [("ticket-java", "Java 17 已安装完成。")]
    assert events[0]["content"] == "已回复 QQ：Java 17 已安装完成。"


def test_agent_task_plan_creates_task_queue_entry(monkeypatch) -> None:
    from app.api.routes import chat as chat_route
    from app.services.agent.reply_ticket import reply_ticket_manager
    from app.services.agent.task_workflow import task_workflow_manager

    handler = SimpleNamespace(id="handler-1")
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="",
            robot_conversation_key="",
            reply_ticket_id="",
        )
    )

    reply_ticket_manager.reset()
    task_workflow_manager.reset()
    ticket = reply_ticket_manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="install Java",
        source_type="web",
    )
    monkeypatch.setattr(
        chat_route,
        "_plan_agent_task_titles",
        lambda handler, message, history: ["install Java", "verify Java"],
    )
    monkeypatch.setattr(
        chat_route,
        "build_status_update_memory_candidate",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        chat_route.vector_store,
        "add_memory",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("task plans must not be stored as long-term memory")
        ),
    )

    try:
        plan = chat_route._create_agent_task_plan(
            "item-1",
            handler=handler,
            agent=agent,
            message="install Java",
            history=[],
            tools=[{"type": "function", "function": {"name": "mcp_local_run_job"}}],
        )

        assert plan is not None
        assert ticket.pending_reply_active is True
        entries = reply_ticket_manager.list_pending_replies("item-1")
        assert len(entries) == 1
        assert entries[0]["id"] == ticket.ticket_id
        assert entries[0]["request_summary"] == "install Java"
        assert entries[0]["task_plan"] == ["install Java", "verify Java"]
    finally:
        reply_ticket_manager.reset()
        task_workflow_manager.reset()


def test_agent_task_plan_inserts_source_change_into_running_workflow(
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route
    from app.services.agent.reply_ticket import reply_ticket_manager
    from app.services.agent.task_workflow import task_workflow_manager

    handler = SimpleNamespace(id="handler-1")
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="",
            robot_conversation_key="",
            reply_ticket_id="",
        )
    )
    tools = [{"type": "function", "function": {"name": "mcp_local_run_job"}}]

    reply_ticket_manager.reset()
    task_workflow_manager.reset()
    monkeypatch.setattr(
        chat_route,
        "_plan_agent_task_titles",
        lambda handler, message, history: ["download Java", "install Java"],
    )
    monkeypatch.setattr(
        chat_route,
        "build_status_update_memory_candidate",
        lambda *args, **kwargs: None,
    )
    try:
        first_ticket = reply_ticket_manager.create_for_agent(
            agent,
            item_id="item-1",
            handler_id="handler-1",
            message="安装 Temurin Java 17",
            source_type="web",
        )
        first_plan = chat_route._create_agent_task_plan(
            "item-1",
            handler=handler,
            agent=agent,
            message="安装 Temurin Java 17",
            history=[],
            tools=tools,
            reply_ticket_id=first_ticket.ticket_id,
        )
        assert first_plan is not None

        second_ticket = reply_ticket_manager.create_for_agent(
            agent,
            item_id="item-1",
            handler_id="handler-1",
            message="先别下，换个国内镜像",
            source_type="web",
        )
        resumed_plan = chat_route._create_agent_task_plan(
            "item-1",
            handler=handler,
            agent=agent,
            message="先别下，换个国内镜像",
            history=[],
            tools=tools,
            reply_ticket_id=second_ticket.ticket_id,
        )

        assert resumed_plan is not None
        assert resumed_plan.workflow_id == first_plan.workflow_id
        workflow = task_workflow_manager.get(resumed_plan.workflow_id)
        assert workflow is not None
        assert workflow.objective == "安装 Temurin Java 17"
        assert workflow.reply_ticket_id == second_ticket.ticket_id
        assert workflow.steps[0].recovery is True
        assert "source/mirror change" in workflow.steps[0].title
        assert "先别下，换个国内镜像" in workflow.steps[0].title
        assert (
            reply_ticket_manager.resolve_ticket_id(first_ticket.ticket_id)
            == second_ticket.ticket_id
        )
        assert reply_ticket_manager.get(first_ticket.ticket_id) is second_ticket
        entries = reply_ticket_manager.list_pending_replies("item-1")
        assert [entry["id"] for entry in entries] == [second_ticket.ticket_id]
    finally:
        reply_ticket_manager.reset()
        task_workflow_manager.reset()


def test_repeated_install_request_reuses_same_active_workflow(monkeypatch) -> None:
    from app.api.routes import chat as chat_route
    from app.services.agent.reply_ticket import reply_ticket_manager
    from app.services.agent.task_workflow import task_workflow_manager

    handler = SimpleNamespace(id="handler-1")
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="",
            robot_conversation_key="",
            reply_ticket_id="",
        )
    )
    tools = [{"type": "function", "function": {"name": "mcp_local_run_job"}}]

    reply_ticket_manager.reset()
    task_workflow_manager.reset()
    monkeypatch.setattr(
        chat_route,
        "_plan_agent_task_titles",
        lambda handler, message, history: ["安装 Java", "验证 java -version"],
    )
    monkeypatch.setattr(
        chat_route,
        "build_status_update_memory_candidate",
        lambda *args, **kwargs: None,
    )
    try:
        first_ticket = reply_ticket_manager.create_for_agent(
            agent,
            item_id="item-1",
            handler_id="handler-1",
            message="安装java",
            source_type="web",
        )
        first_plan = chat_route._create_agent_task_plan(
            "item-1",
            handler=handler,
            agent=agent,
            message="安装java",
            history=[],
            tools=tools,
            reply_ticket_id=first_ticket.ticket_id,
        )
        assert first_plan is not None

        repeated_ticket = reply_ticket_manager.create_for_agent(
            agent,
            item_id="item-1",
            handler_id="handler-1",
            message="你想办法给我装完java就行了",
            source_type="web",
        )
        repeated_plan = chat_route._create_agent_task_plan(
            "item-1",
            handler=handler,
            agent=agent,
            message="你想办法给我装完java就行了",
            history=[],
            tools=tools,
            reply_ticket_id=repeated_ticket.ticket_id,
        )

        assert repeated_plan is not None
        assert repeated_plan.workflow_id == first_plan.workflow_id
        workflow = task_workflow_manager.get(repeated_plan.workflow_id)
        assert workflow is not None
        assert workflow.objective == "安装java"
        assert workflow.report_policy == "normal"
        assert len(task_workflow_manager.snapshot("item-1")) == 1
    finally:
        reply_ticket_manager.reset()
        task_workflow_manager.reset()


def test_finish_then_tell_me_keeps_task_active_and_enables_final_only(
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route
    from app.services.agent.reply_ticket import reply_ticket_manager
    from app.services.agent.task_workflow import task_workflow_manager

    handler = SimpleNamespace(id="handler-1")
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="",
            robot_conversation_key="",
            reply_ticket_id="",
        )
    )
    tools = [{"type": "function", "function": {"name": "mcp_local_run_job"}}]

    reply_ticket_manager.reset()
    task_workflow_manager.reset()
    monkeypatch.setattr(
        chat_route,
        "_plan_agent_task_titles",
        lambda handler, message, history: ["安装 Java", "验证 java -version"],
    )
    monkeypatch.setattr(
        chat_route,
        "build_status_update_memory_candidate",
        lambda *args, **kwargs: None,
    )
    try:
        first_ticket = reply_ticket_manager.create_for_agent(
            agent,
            item_id="item-1",
            handler_id="handler-1",
            message="安装java",
            source_type="web",
        )
        first_plan = chat_route._create_agent_task_plan(
            "item-1",
            handler=handler,
            agent=agent,
            message="安装java",
            history=[],
            tools=tools,
            reply_ticket_id=first_ticket.ticket_id,
        )
        assert first_plan is not None

        final_only_ticket = reply_ticket_manager.create_for_agent(
            agent,
            item_id="item-1",
            handler_id="handler-1",
            message="装完跟我说就行了",
            source_type="web",
        )
        resumed_plan = chat_route._create_agent_task_plan(
            "item-1",
            handler=handler,
            agent=agent,
            message="装完跟我说就行了",
            history=[],
            tools=tools,
            reply_ticket_id=final_only_ticket.ticket_id,
        )

        assert resumed_plan is not None
        assert resumed_plan.workflow_id == first_plan.workflow_id
        workflow = task_workflow_manager.get(resumed_plan.workflow_id)
        assert workflow is not None
        assert workflow.objective == "安装java"
        assert workflow.status == "active"
        assert workflow.report_policy == "final_only"
    finally:
        reply_ticket_manager.reset()
        task_workflow_manager.reset()


def test_cancel_current_execution_does_not_cancel_main_objective(monkeypatch) -> None:
    from app.api.routes import chat as chat_route
    from app.services.agent.reply_ticket import reply_ticket_manager
    from app.services.agent.task_workflow import task_workflow_manager

    handler = SimpleNamespace(id="handler-1")
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="",
            robot_conversation_key="",
            reply_ticket_id="",
        )
    )
    tools = [{"type": "function", "function": {"name": "mcp_local_run_job"}}]

    reply_ticket_manager.reset()
    task_workflow_manager.reset()
    monkeypatch.setattr(
        chat_route,
        "_plan_agent_task_titles",
        lambda handler, message, history: ["安装 Java", "验证 java -version"],
    )
    monkeypatch.setattr(
        chat_route,
        "build_status_update_memory_candidate",
        lambda *args, **kwargs: None,
    )
    try:
        first_ticket = reply_ticket_manager.create_for_agent(
            agent,
            item_id="item-1",
            handler_id="handler-1",
            message="安装java",
            source_type="web",
        )
        first_plan = chat_route._create_agent_task_plan(
            "item-1",
            handler=handler,
            agent=agent,
            message="安装java",
            history=[],
            tools=tools,
            reply_ticket_id=first_ticket.ticket_id,
        )
        assert first_plan is not None

        cancel_ticket = reply_ticket_manager.create_for_agent(
            agent,
            item_id="item-1",
            handler_id="handler-1",
            message="给这个任务取消了",
            source_type="web",
        )
        resumed_plan = chat_route._create_agent_task_plan(
            "item-1",
            handler=handler,
            agent=agent,
            message="给这个任务取消了",
            history=[],
            tools=tools,
            reply_ticket_id=cancel_ticket.ticket_id,
        )

        assert resumed_plan is not None
        assert resumed_plan.workflow_id == first_plan.workflow_id
        workflow = task_workflow_manager.get(resumed_plan.workflow_id)
        assert workflow is not None
        assert workflow.objective == "安装java"
        assert workflow.status == "active"
        assert "current execution" in workflow.latest_progress
    finally:
        reply_ticket_manager.reset()
        task_workflow_manager.reset()


def test_terminal_unavailable_task_reports_failure_and_removes_queue_entry(
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route
    from app.services.agent.reply_ticket import reply_ticket_manager
    from app.services.agent.task_workflow import task_workflow_manager

    handler = SimpleNamespace(id="handler-1")
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="",
            robot_conversation_key="",
            reply_ticket_id="",
        )
    )
    tools = [{"type": "function", "function": {"name": "mcp_local_run_job"}}]

    reply_ticket_manager.reset()
    task_workflow_manager.reset()
    monkeypatch.setattr(
        chat_route,
        "_plan_agent_task_titles",
        lambda handler, message, history: ["安装 Java", "验证 java -version"],
    )
    monkeypatch.setattr(
        chat_route,
        "build_status_update_memory_candidate",
        lambda *args, **kwargs: None,
    )
    try:
        install_ticket = reply_ticket_manager.create_for_agent(
            agent,
            item_id="item-1",
            handler_id="handler-1",
            message="安装java",
            source_type="web",
        )
        install_plan = chat_route._create_agent_task_plan(
            "item-1",
            handler=handler,
            agent=agent,
            message="安装java",
            history=[],
            tools=tools,
            reply_ticket_id=install_ticket.ticket_id,
        )
        assert install_plan is not None

        monkeypatch.setattr(
            chat_route,
            "_generate_stopped_turn_report",
            lambda *_args, **_kwargs: "终端未连接，无法安装 Java，任务已结束。",
        )
        monkeypatch.setattr(
            chat_route,
            "_persist_and_broadcast_event",
            lambda _item_id, **event: event,
        )

        events = chat_route._finalize_stopped_turn(
            agent=agent,
            handler=handler,
            item_id="item-1",
            messages=[],
            planned_task_runtime=chat_route.PlannedTaskRuntime(
                request_id=install_plan.request_id,
                reply_ticket_id=install_ticket.ticket_id,
                workflow_id=install_plan.workflow_id,
            ),
            reason="Terminal unavailable: 终端未连接或未打开",
            prefers_chinese=True,
            include_hidden_tool_results=False,
            reply_ticket_id=install_ticket.ticket_id,
        )

        workflow = task_workflow_manager.get(install_plan.workflow_id)
        assert workflow is not None
        assert events[0]["content"] == "终端未连接，无法安装 Java，任务已结束。"
        assert workflow.status == "failed"
        assert reply_ticket_manager.list_pending_replies("item-1") == []
    finally:
        reply_ticket_manager.reset()
        task_workflow_manager.reset()


def test_qq_task_plan_uses_current_message_instead_of_robot_context_card(
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route
    from app.services.agent.reply_ticket import SOURCE_QQ, reply_ticket_manager
    from app.services.agent.task_workflow import task_workflow_manager

    handler = SimpleNamespace(id="handler-1")
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="robot-1",
            robot_conversation_key="private:2537134688",
            reply_ticket_id="",
        )
    )
    reply_ticket_manager.reset()
    task_workflow_manager.reset()
    monkeypatch.setattr(
        chat_route,
        "_plan_agent_task_titles",
        lambda handler, message, history: ["download Java", "verify Java"],
    )
    monkeypatch.setattr(
        chat_route,
        "build_status_update_memory_candidate",
        lambda *args, **kwargs: None,
    )
    try:
        ticket = reply_ticket_manager.create_for_agent(
            agent,
            item_id="item-1",
            handler_id="handler-1",
            message="decorated message",
            source_type="web",
        )
        ticket.source_type = SOURCE_QQ
        ticket.source_label = "QQ private:2537134688"
        ticket.request_message = "安装 Temurin Java 17"

        plan = chat_route._create_agent_task_plan(
            "item-1",
            handler=handler,
            agent=agent,
            message=(
                "[Robot message; conversation=private:2537134688]\n"
                "[Robot identity; background only] lots of metadata\n"
                "[Current QQ message]\n安装 Temurin Java 17"
            ),
            history=[],
            tools=[{"type": "function", "function": {"name": "mcp_local_run_job"}}],
            reply_ticket_id=ticket.ticket_id,
        )

        assert plan is not None
        workflow = task_workflow_manager.get(plan.workflow_id)
        assert workflow is not None
        assert workflow.objective == "安装 Temurin Java 17"
        assert "Robot identity" not in workflow.objective
    finally:
        reply_ticket_manager.reset()
        task_workflow_manager.reset()


def test_stopped_web_task_reports_failure_then_removes_queue_entry(
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route
    from app.services.agent.reply_ticket import reply_ticket_manager
    from app.services.agent.task_workflow import task_workflow_manager

    handler = SimpleNamespace(id="handler-1")
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="",
            robot_conversation_key="",
            reply_ticket_id="",
        )
    )
    reply_ticket_manager.reset()
    task_workflow_manager.reset()
    ticket = reply_ticket_manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="install Java",
        source_type="web",
    )
    workflow = task_workflow_manager.create(
        item_id="item-1",
        handler_id="handler-1",
        reply_ticket_id=ticket.ticket_id,
        objective="install Java",
        source_type="web",
        source_label="TermMan web chat",
        step_titles=["install Java", "report result"],
    )
    reply_ticket_manager.upsert_pending_reply(
        ticket.ticket_id,
        status="working",
    )
    monkeypatch.setattr(
        chat_route,
        "_generate_stopped_turn_report",
        lambda *_args, **_kwargs: "Java 安装失败：软件源不可用。",
    )
    monkeypatch.setattr(
        chat_route,
        "_persist_and_broadcast_event",
        lambda _item_id, **event: event,
    )

    try:
        events = chat_route._finalize_stopped_turn(
            agent=agent,
            handler=handler,
            item_id="item-1",
            messages=[],
            planned_task_runtime=chat_route.PlannedTaskRuntime(
                request_id=workflow.workflow_id,
                reply_ticket_id=ticket.ticket_id,
                workflow_id=workflow.workflow_id,
            ),
            reason="Package source is unavailable",
            prefers_chinese=True,
            include_hidden_tool_results=False,
            reply_ticket_id=ticket.ticket_id,
        )

        assert events[0]["content"] == "Java 安装失败：软件源不可用。"
        assert reply_ticket_manager.list_pending_replies("item-1") == []
        assert workflow.status == "failed"
    finally:
        reply_ticket_manager.reset()
        task_workflow_manager.reset()


def test_model_parameter_failure_uses_specific_fallback_without_retrying_llm(
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route

    def unexpected_completion(**_kwargs):
        raise AssertionError("failure reporting must not call the broken model again")

    monkeypatch.setattr(chat_route, "completion", unexpected_completion)

    report = chat_route._generate_stopped_turn_report(
        SimpleNamespace(),
        [{"role": "user", "content": "你好"}],
        reason=(
            "Agent request failed: litellm.UnsupportedParamsError: "
            "gpt-5 models don't support temperature=0.1"
        ),
        prefers_chinese=True,
    )

    assert report.startswith("模型参数不兼容：litellm.UnsupportedParamsError:")
    assert "temperature=0.1" in report


def test_service_unavailable_failure_uses_channel_fallback() -> None:
    from app.api.routes import chat as chat_route

    report = chat_route._stopped_turn_fallback(
        "Agent request failed: ServiceUnavailableError: No available channel",
        prefers_chinese=True,
    )

    assert "模型通道不可用" in report


def test_non_converged_task_ends_instead_of_pausing() -> None:
    from app.api.routes import chat as chat_route

    report = chat_route._stopped_turn_fallback(
        chat_route.TOOL_BUDGET_STOP_REASON,
        prefers_chinese=True,
    )

    assert "任务已结束" in report
    assert "暂停" not in report
    assert "保留当前进度" not in report


def test_model_error_fallback_redacts_api_credentials() -> None:
    from app.api.routes import chat as chat_route

    report = chat_route._stopped_turn_fallback(
        "Agent request failed: AuthenticationError api_key=sk-secret123456 Bearer token.value",
        prefers_chinese=True,
    )

    assert "sk-secret123456" not in report
    assert "token.value" not in report
    assert "[REDACTED]" in report


def test_agent_task_workflow_does_not_depend_on_vector_memory_write(
    monkeypatch,
) -> None:
    from app.api.routes import chat as chat_route
    from app.services.agent.task_workflow import task_workflow_manager

    handler = SimpleNamespace(id="handler-1")
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="",
            robot_conversation_key="",
            reply_ticket_id="ticket-java",
        )
    )
    task_workflow_manager.reset()
    monkeypatch.setattr(
        chat_route,
        "_plan_agent_task_titles",
        lambda handler, message, history: ["install Java", "verify Java"],
    )
    monkeypatch.setattr(
        chat_route.vector_store,
        "add_memory",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("task plans must not be stored as long-term memory")
        ),
    )

    plan = chat_route._create_agent_task_plan(
        "item-1",
        handler=handler,
        agent=agent,
        message="install Java 17",
        history=[],
        tools=[{"type": "function", "function": {"name": "mcp_local_run_job"}}],
    )

    assert plan is not None
    workflow = task_workflow_manager.get(plan.workflow_id)
    assert workflow is not None
    assert workflow.objective == "install Java 17"
    assert [step.title for step in workflow.steps] == [
        "install Java",
        "verify Java",
    ]
    task_workflow_manager.reset()


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
    from app.services.terminal_command_state import terminal_command_state_manager

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

    terminal_command_state_manager.clear("item-1")
    try:
        session = session_module.AgentSession("item-1", "handler-1")
        messages = session._build_terminal_messages(
            fake_agent,
            session_module.InputMessage(
                input_type=session_module.InputType.TERMINAL,
                content="python: can't open file '/app/items/5/cron_job.py'",
            ),
        )
    finally:
        terminal_command_state_manager.clear("item-1")

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
