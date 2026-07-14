from __future__ import annotations

from app.services.agent.tool_grounding import (
    guard_ungrounded_tool_claim,
    has_ungrounded_tool_claim,
)


def test_detects_completed_tool_claims() -> None:
    assert has_ungrounded_tool_claim("我已经检查了 robot bridge，一切正常。")
    assert has_ungrounded_tool_claim("I checked the server and it is running.")
    assert has_ungrounded_tool_claim(
        "Executing tool: mcp_robot_send_group_message\n{\"message\":\"hello\"}"
    )
    assert not has_ungrounded_tool_claim("建议你检查一下 robot bridge。")


def test_guard_replaces_claim_when_no_tool_was_called() -> None:
    guarded = guard_ungrounded_tool_claim(
        "我已经重启了 robot bridge。",
        tool_called=False,
    )

    assert guarded == "我没有实际调用工具，因此这次外部操作没有执行。"
    assert "我已经重启了 robot bridge。" not in guarded


def test_guard_drops_fabricated_tool_transcript_and_success_claim() -> None:
    guarded = guard_ungrounded_tool_claim(
        """Executing tool: mcp_robot_send_group_message
```json
{"group_id":"770362397","message":"你好"}
```
已经发送成功啦！""",
        tool_called=False,
    )

    assert guarded == "我没有实际调用工具，因此这次外部操作没有执行。"
    assert "mcp_robot_send_group_message" not in guarded
    assert "发送成功" not in guarded


def test_guard_keeps_claim_after_real_tool_call() -> None:
    content = "我已经读取了日志，里面没有错误。"

    assert guard_ungrounded_tool_claim(content, tool_called=True) == content
