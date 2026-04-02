import asyncio
from pathlib import Path
from uuid import uuid4

from app.services.agent import agent as agent_module
from app.services.agent.agent import AgentContext
from app.services.agent.mcp.types import MCPTool
from app.services.log_manager import LogManager


def test_start_mcp_servers_does_not_duplicate_tools(monkeypatch) -> None:
    handler_id = f"handler-{uuid4()}"
    agent = agent_module.Agent(handler_id)
    agent._context = AgentContext(handler_id=handler_id, enabled_mcp_servers=["local"])
    agent._mcp_servers = ["local"]

    tools = [
        MCPTool(
            name="execute_command",
            description="Execute a command",
            input_schema={"type": "object", "properties": {}},
            server_name="local",
        ),
        MCPTool(
            name="read_terminal_log",
            description="Read terminal log",
            input_schema={"type": "object", "properties": {}},
            server_name="local",
        ),
    ]

    monkeypatch.setattr(agent_module.mcp_server_manager, "is_server_running", lambda name: True)
    monkeypatch.setattr(agent_module.mcp_server_manager, "get_tools_for_server", lambda name: tools)

    try:
        asyncio.run(agent.start_mcp_servers())
        asyncio.run(agent.start_mcp_servers())
    finally:
        agent_module.Agent._instances.pop(handler_id, None)

    tool_names = [tool["function"]["name"] for tool in agent.get_tools_for_litellm()]
    assert tool_names == [
        "mcp_local_execute_command",
        "mcp_local_read_terminal_log",
    ]


def test_log_manager_reads_legacy_log_when_primary_missing(tmp_path) -> None:
    primary_dir = tmp_path / ".runtime" / "item_logs"
    legacy_dir = tmp_path / "backend" / "app" / "services" / "log"
    legacy_dir.mkdir(parents=True, exist_ok=True)

    manager = LogManager(base_dir=str(primary_dir))
    manager._legacy_base_dir = legacy_dir
    item_id = "item-1"

    legacy_path = legacy_dir / f"{item_id}.log"
    legacy_path.write_text("legacy line\n", encoding="utf-8")

    assert Path(manager.base_dir) == primary_dir.resolve()
    assert manager.get_log_content("user-1", item_id) == "legacy line\n"
    assert manager.get_last_lines(item_id, lines=1) == "legacy line\n"
    assert manager.get_line_count(item_id) == 1
    assert manager.get_lines_since(item_id, start_line=0) == "legacy line\n"

    assert manager.write_to_log("user-1", item_id, "primary line\n") is True
    assert manager.get_last_lines(item_id, lines=1) == "primary line\n"
