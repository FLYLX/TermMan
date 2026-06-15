from __future__ import annotations

from app.services.agent.tool_grounding import (
    guard_ungrounded_tool_claim,
    has_ungrounded_tool_claim,
)


def test_detects_completed_tool_claims() -> None:
    assert has_ungrounded_tool_claim("我已经检查了 robot bridge，一切正常。")
    assert has_ungrounded_tool_claim("I checked the server and it is running.")
    assert not has_ungrounded_tool_claim("建议你检查一下 robot bridge。")


def test_guard_prefixes_claim_when_no_tool_was_called() -> None:
    guarded = guard_ungrounded_tool_claim(
        "我已经重启了 robot bridge。",
        tool_called=False,
    )

    assert guarded.startswith("我没有实际调用 MCP/工具")
    assert "我已经重启了 robot bridge。" in guarded


def test_guard_keeps_claim_after_real_tool_call() -> None:
    content = "我已经读取了日志，里面没有错误。"

    assert guard_ungrounded_tool_claim(content, tool_called=True) == content
