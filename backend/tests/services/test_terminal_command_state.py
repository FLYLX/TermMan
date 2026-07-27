from app.services.terminal_command_state import TerminalCommandStateManager


def test_terminal_command_state_records_latest_command_and_prompt_context() -> None:
    manager = TerminalCommandStateManager()

    state = manager.record(
        "item-1",
        "cd /srv/minecraft && ./run.sh",
        source="agent",
        timeout_seconds=180,
    )

    assert state["command"] == "cd /srv/minecraft && ./run.sh"
    assert state["source"] == "agent"
    assert state["timeout_seconds"] == 180
    context = manager.build_prompt_context("item-1")
    assert "cd /srv/minecraft && ./run.sh" in context
    assert r"Done \(.*\)!" in context
    assert "Do not interrupt" in context


def test_terminal_command_state_ignores_ctrl_c() -> None:
    manager = TerminalCommandStateManager()
    manager.record("item-1", "./run.sh", source="web")
    manager.record("item-1", "\x03", source="web")

    assert manager.snapshot("item-1")["command"] == "./run.sh"
