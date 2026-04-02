from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlmodel import Session

from app.models import ItemHandlerItem
from app.services.agent.session import agent_session_manager
from app.services.agent.stream_manager import (
    MAX_TERMINAL_BATCH_WINDOW_SECONDS,
    MIN_TERMINAL_BATCH_WINDOW_SECONDS,
    TERMINAL_BATCH_DEBOUNCE_SECONDS,
    WAITING_TERMINAL_BATCH_DEBOUNCE_SECONDS,
    PendingTerminalBatch,
    stream_manager,
)
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

        async def start_mcp_servers(self):
            return None

        def get_skills(self):
            return []

        def match_skills(self, message):
            return []

        def get_skip_memory_tools(self):
            return []

        def get_tools_for_litellm(self):
            return tools or []

        async def execute_tool(self, tool_name, tool_args):
            if callable(execute_tool_result):
                return execute_tool_result(tool_name, tool_args)
            if execute_tool_result is not None:
                return execute_tool_result
            return {"success": True, "result": [{"type": "text", "text": "tool ok"}]}

    return FakeAgent()


def test_regular_terminal_turn_uses_filtered_output_only(
    db: Session,
    monkeypatch,
) -> None:
    from app.services.agent import session as session_module

    item, handler = _create_linked_item_and_handler(db)
    item_id = str(item.id)
    handler_id = str(handler.id)
    fake_agent = _make_fake_agent()
    completion_inputs: list[str] = []

    def fake_completion(**kwargs):
        completion_inputs.append(kwargs["messages"][-1]["content"])
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Handled filtered terminal event",
                        tool_calls=None,
                    )
                )
            ]
        )

    agent_session_manager.remove_session(item_id)
    monkeypatch.setattr(session_module.AgentSession, "get_agent", lambda self: fake_agent)
    monkeypatch.setattr(session_module, "completion", fake_completion)
    monkeypatch.setattr(
        session_module.AgentSession,
        "_get_relevant_memories",
        lambda self, query, n_results=3: "",
    )

    try:
        stream_manager.process_stream(
            item_id,
            "filtered error: missing file",
            handler_id,
            raw_output="RAW TRACE: /secret/path\nline 2",
        )
        stream_manager.flush_pending_stream(item_id)
    finally:
        stream_manager.clear_pending_stream(item_id)
        agent_session_manager.remove_session(item_id)

    assert len(completion_inputs) == 1
    assert "filtered error: missing file" in completion_inputs[0]
    assert "RAW TRACE" not in completion_inputs[0]


def test_filtered_terminal_status_marks_filtered_output(
    db: Session,
    monkeypatch,
) -> None:
    from app.services.agent import session as session_module

    item, handler = _create_linked_item_and_handler(db)
    item_id = str(item.id)
    handler_id = str(handler.id)
    fake_agent = _make_fake_agent()
    events: list[dict] = []

    def fake_completion(**kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Handled filtered terminal event",
                        tool_calls=None,
                    )
                )
            ]
        )

    agent_session_manager.remove_session(item_id)
    monkeypatch.setattr(session_module.AgentSession, "get_agent", lambda self: fake_agent)
    monkeypatch.setattr(session_module, "completion", fake_completion)
    monkeypatch.setattr(
        session_module.AgentSession,
        "_get_relevant_memories",
        lambda self, query, n_results=3: "",
    )

    try:
        session = agent_session_manager.get_or_create_session(item_id, handler_id)
        session.add_output_callback(events.append)
        stream_manager.process_stream(
            item_id,
            "filtered error: missing file",
            handler_id,
            raw_output="RAW TRACE: /secret/path\nline 2",
        )
        stream_manager.flush_pending_stream(item_id)
    finally:
        stream_manager.clear_pending_stream(item_id)
        agent_session_manager.remove_session(item_id)

    status_events = [event for event in events if event.get("type") == "agent_status"]
    assert any(
        event.get("status") == "collecting"
        and event.get("terminal_source") == "filtered_output"
        for event in status_events
    )
    assert any(
        event.get("status") == "running"
        and event.get("terminal_source") == "filtered_output"
        for event in status_events
    )


def test_command_feedback_status_marks_raw_feedback(
    db: Session,
    monkeypatch,
) -> None:
    from app.services.agent import session as session_module

    item, handler = _create_linked_item_and_handler(db)
    item_id = str(item.id)
    handler_id = str(handler.id)
    tool_name = "mcp_local_execute_command"
    events: list[dict] = []
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
            "result": [{"type": "text", "text": "command sent: find cron_job.py"}],
        },
    )

    def fake_completion(**kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="准备发送定位命令",
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

        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="已收到原生日志反馈",
                        tool_calls=None,
                    )
                )
            ]
        )

    agent_session_manager.remove_session(item_id)
    monkeypatch.setattr(session_module.AgentSession, "get_agent", lambda self: fake_agent)
    monkeypatch.setattr(session_module, "completion", fake_completion)
    monkeypatch.setattr(
        session_module.AgentSession,
        "_get_relevant_memories",
        lambda self, query, n_results=3: "",
    )
    monkeypatch.setattr(
        session_module.AgentSession,
        "_consume_pending_log_delta",
        lambda self: "[2026-04-02 05:35:18] /app/src/cron_job.py\n",
    )

    try:
        session = agent_session_manager.get_or_create_session(item_id, handler_id)
        session.add_output_callback(events.append)
        session.process_input(
            session_module.InputMessage(
                input_type=session_module.InputType.TERMINAL,
                content="filtered error: missing file",
            )
        )
        stream_manager.process_stream(
            item_id,
            "",
            handler_id,
            raw_output="[2026-04-02 05:35:18] /app/src/cron_job.py\n",
        )
        stream_manager.flush_pending_stream(item_id)
    finally:
        stream_manager.clear_pending_stream(item_id)
        agent_session_manager.remove_session(item_id)

    status_events = [event for event in events if event.get("type") == "agent_status"]
    assert any(
        event.get("status") == "waiting_terminal"
        and event.get("terminal_source") == "raw_feedback"
        for event in status_events
    )
    assert any(
        event.get("status") == "running"
        and event.get("terminal_source") == "raw_feedback"
        for event in status_events
    )


def test_repeated_echo_feedback_resolves_empty_command_output(
    db: Session,
    monkeypatch,
) -> None:
    from app.services.agent import session as session_module

    item, handler = _create_linked_item_and_handler(db)
    item_id = str(item.id)
    handler_id = str(handler.id)
    tool_name = "mcp_local_execute_command"
    command = "ls"
    call_count = {"value": 0}
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

    def fake_completion(**kwargs):
        call_count["value"] += 1
        completion_inputs.append(kwargs["messages"][-1]["content"])
        if call_count["value"] == 1:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="准备执行 ls",
                            tool_calls=[
                                SimpleNamespace(
                                    id="call_1",
                                    function=SimpleNamespace(
                                        name=tool_name,
                                        arguments='{"command":"ls"}',
                                    ),
                                )
                            ],
                        )
                    )
                ]
            )

        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="已确认命令执行完成，但目录为空。",
                        tool_calls=None,
                    )
                )
            ]
        )

    agent_session_manager.remove_session(item_id)
    monkeypatch.setattr(session_module.AgentSession, "get_agent", lambda self: fake_agent)
    monkeypatch.setattr(session_module, "completion", fake_completion)
    monkeypatch.setattr(
        session_module.AgentSession,
        "_get_relevant_memories",
        lambda self, query, n_results=3: "",
    )

    try:
        session = agent_session_manager.get_or_create_session(item_id, handler_id)
        session.add_output_callback(events.append)
        session.process_input(
            session_module.InputMessage(
                input_type=session_module.InputType.TERMINAL,
                content="need to inspect directory",
            )
        )
        stream_manager.process_stream(
            item_id,
            "",
            handler_id,
            raw_output="[2026-04-02 07:37:25] # # ls\n[2026-04-02 07:37:28] # # ls\n",
        )
        stream_manager.flush_pending_stream(item_id)
    finally:
        stream_manager.clear_pending_stream(item_id)
        agent_session_manager.remove_session(item_id)

    assert call_count["value"] == 1
    assert any(
        event.get("type") == "agent_response" and "终端没有输出内容" in event.get("content", "")
        for event in events
    )


def test_log_tail_fallback_resolves_empty_command_output(
    db: Session,
    monkeypatch,
) -> None:
    from app.services.agent import session as session_module

    item, handler = _create_linked_item_and_handler(db)
    item_id = str(item.id)
    handler_id = str(handler.id)
    tool_name = "mcp_local_execute_command"
    call_count = {"value": 0}
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
            "result": [{"type": "text", "text": "command sent: ls"}],
        },
    )

    def fake_completion(**kwargs):
        call_count["value"] += 1
        completion_inputs.append(kwargs["messages"][-1]["content"])
        if call_count["value"] == 1:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="准备执行 ls",
                            tool_calls=[
                                SimpleNamespace(
                                    id="call_1",
                                    function=SimpleNamespace(
                                        name=tool_name,
                                        arguments='{"command":"ls"}',
                                    ),
                                )
                            ],
                        )
                    )
                ]
            )

        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="已确认目录为空。",
                        tool_calls=None,
                    )
                )
            ]
        )

    agent_session_manager.remove_session(item_id)
    monkeypatch.setattr(session_module.AgentSession, "get_agent", lambda self: fake_agent)
    monkeypatch.setattr(session_module, "completion", fake_completion)
    monkeypatch.setattr(
        session_module.AgentSession,
        "_get_relevant_memories",
        lambda self, query, n_results=3: "",
    )
    monkeypatch.setattr(
        session_module.AgentSession,
        "_consume_pending_log_delta",
        lambda self: "[2026-04-02 07:54:28] # # ls\n",
    )
    monkeypatch.setattr(
        session_module.AgentSession,
        "_get_recent_pending_log_tail",
        lambda self, lines=8: "[2026-04-02 07:54:25] # # ls\n[2026-04-02 07:54:28] # # ls\n",
    )

    try:
        session = agent_session_manager.get_or_create_session(item_id, handler_id)
        session.add_output_callback(events.append)
        session.process_input(
            session_module.InputMessage(
                input_type=session_module.InputType.TERMINAL,
                content="need to inspect directory",
            )
        )
        stream_manager.process_stream(
            item_id,
            "",
            handler_id,
            raw_output="[2026-04-02 07:54:28] # # ls\n",
        )
        stream_manager.flush_pending_stream(item_id)
    finally:
        stream_manager.clear_pending_stream(item_id)
        agent_session_manager.remove_session(item_id)

    assert call_count["value"] == 1
    assert any(
        event.get("type") == "agent_response" and "终端没有输出内容" in event.get("content", "")
        for event in events
    )


def test_pending_command_recheck_advances_without_new_stream_event(
    db: Session,
    monkeypatch,
) -> None:
    from app.services.agent import session as session_module

    item, handler = _create_linked_item_and_handler(db)
    item_id = str(item.id)
    handler_id = str(handler.id)
    tool_name = "mcp_local_execute_command"
    command = "ls"
    call_count = {"value": 0}
    completion_inputs: list[str] = []
    log_line_count = {"value": 0}
    raw_echo = "[2026-04-02 08:03:14] # # ls\n"
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

    def fake_completion(**kwargs):
        call_count["value"] += 1
        completion_inputs.append(kwargs["messages"][-1]["content"])
        if call_count["value"] == 1:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="准备执行 ls",
                            tool_calls=[
                                SimpleNamespace(
                                    id="call_1",
                                    function=SimpleNamespace(
                                        name=tool_name,
                                        arguments='{"command":"ls"}',
                                    ),
                                )
                            ],
                        )
                    )
                ]
            )

        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="已确认目录为空。",
                        tool_calls=None,
                    )
                )
            ]
        )

    def fake_consume_pending_log_delta(self):
        pending = self._get_pending_command()
        if not pending:
            return ""
        if pending.log_line_cursor < log_line_count["value"]:
            with self.lock:
                current_pending = self._pending_command
                if current_pending:
                    current_pending.log_line_cursor = log_line_count["value"]
            return raw_echo
        return ""

    agent_session_manager.remove_session(item_id)
    monkeypatch.setattr(session_module.AgentSession, "get_agent", lambda self: fake_agent)
    monkeypatch.setattr(session_module, "completion", fake_completion)
    monkeypatch.setattr(
        session_module.AgentSession,
        "_get_relevant_memories",
        lambda self, query, n_results=3: "",
    )
    monkeypatch.setattr(
        session_module.AgentSession,
        "_schedule_pending_command_recheck",
        lambda self, delay_seconds=session_module.PENDING_COMMAND_RECHECK_SECONDS: None,
    )
    monkeypatch.setattr(
        session_module.AgentSession,
        "_get_log_line_count",
        lambda self: log_line_count["value"],
    )
    monkeypatch.setattr(
        session_module.AgentSession,
        "_consume_pending_log_delta",
        fake_consume_pending_log_delta,
    )
    monkeypatch.setattr(
        session_module.AgentSession,
        "_get_recent_pending_log_tail",
        lambda self, lines=8: raw_echo,
    )

    try:
        session = agent_session_manager.get_or_create_session(item_id, handler_id)
        session.add_output_callback(events.append)
        session.process_input(
            session_module.InputMessage(
                input_type=session_module.InputType.TERMINAL,
                content="need to inspect directory",
            )
        )

        pending = session._get_pending_command()
        assert pending is not None
        assert call_count["value"] == 1

        log_line_count["value"] = 1
        session._run_pending_command_recheck(pending.normalized_command)
        assert call_count["value"] == 1

        pending = session._get_pending_command()
        assert pending is not None
        pending.dispatched_at = datetime.now() - timedelta(
            seconds=session_module.PENDING_COMMAND_STALLED_CONFIRM_SECONDS + 0.1
        )

        session._run_pending_command_recheck(pending.normalized_command)
    finally:
        stream_manager.clear_pending_stream(item_id)
        agent_session_manager.remove_session(item_id)

    assert call_count["value"] == 1
    assert any(
        event.get("type") == "agent_response" and "终端没有输出内容" in event.get("content", "")
        for event in events
    )


def test_terminal_flush_delay_uses_min_window_and_max_window() -> None:
    now = datetime.now()
    batch = PendingTerminalBatch(
        item_id="item-1",
        handler_id="handler-1",
        created_at=now,
        last_update=now,
    )

    initial_delay = stream_manager._get_terminal_flush_delay(
        batch,
        debounce_seconds=TERMINAL_BATCH_DEBOUNCE_SECONDS,
        waiting_for_command_feedback=False,
    )
    assert MIN_TERMINAL_BATCH_WINDOW_SECONDS - 0.05 <= initial_delay <= MIN_TERMINAL_BATCH_WINDOW_SECONDS

    middle_age = MIN_TERMINAL_BATCH_WINDOW_SECONDS + 0.1
    batch.created_at = now - timedelta(seconds=middle_age)
    middle_delay = stream_manager._get_terminal_flush_delay(
        batch,
        debounce_seconds=TERMINAL_BATCH_DEBOUNCE_SECONDS,
        waiting_for_command_feedback=False,
    )
    expected_middle_delay = min(
        TERMINAL_BATCH_DEBOUNCE_SECONDS,
        MAX_TERMINAL_BATCH_WINDOW_SECONDS - middle_age,
    )
    assert expected_middle_delay - 0.05 <= middle_delay <= expected_middle_delay + 0.05

    batch.created_at = now - timedelta(seconds=MAX_TERMINAL_BATCH_WINDOW_SECONDS + 0.5)
    expired_delay = stream_manager._get_terminal_flush_delay(
        batch,
        debounce_seconds=TERMINAL_BATCH_DEBOUNCE_SECONDS,
        waiting_for_command_feedback=False,
    )
    assert expired_delay == 0.0

    fast_feedback_delay = stream_manager._get_terminal_flush_delay(
        batch,
        debounce_seconds=WAITING_TERMINAL_BATCH_DEBOUNCE_SECONDS,
        waiting_for_command_feedback=True,
    )
    assert fast_feedback_delay == WAITING_TERMINAL_BATCH_DEBOUNCE_SECONDS


def test_running_terminal_queue_merges_consecutive_terminal_inputs() -> None:
    from app.services.agent import session as session_module

    session = session_module.AgentSession("item-1", "handler-1")
    session.state = session_module.SessionState.RUNNING

    first = session_module.InputMessage(
        input_type=session_module.InputType.TERMINAL,
        content="111",
        raw_content="raw-111",
        timestamp=datetime.now(),
    )
    second = session_module.InputMessage(
        input_type=session_module.InputType.TERMINAL,
        content="222",
        raw_content="raw-222",
        timestamp=datetime.now() + timedelta(seconds=1),
    )

    assert session.queue_input(first) is True
    assert session.queue_input(second) is True
    assert session.input_queue.qsize() == 1

    queued = session.input_queue.get_nowait()
    assert queued.content == "111\n222"
    assert queued.raw_content == "raw-111\nraw-222"
