from __future__ import annotations

from app.services.agent.tool_grounding import (
    append_tool_call_footer,
    guard_fabricated_tool_trace,
    has_fabricated_tool_trace,
)


def test_detects_fabricated_tool_trace() -> None:
    assert has_fabricated_tool_trace(
        "Executing tool: mcp_robot_send_group_message\n{\"message\":\"hello\"}"
    )
    assert has_fabricated_tool_trace("执行工具: mcp_local_run_job")
    assert not has_fabricated_tool_trace("我已经检查了 robot bridge，一切正常。")
    assert not has_fabricated_tool_trace("I checked the server and it is running.")
    assert not has_fabricated_tool_trace("")


def test_guard_replaces_fabricated_trace() -> None:
    guarded = guard_fabricated_tool_trace(
        """Executing tool: mcp_robot_send_group_message
```json
{"group_id":"770362397","message":"你好"}
```
已经发送成功啦！""",
    )

    assert guarded == "我没有实际调用工具，因此这次外部操作没有执行。"
    assert "mcp_robot_send_group_message" not in guarded


def test_guard_replaces_fabricated_trace_english() -> None:
    guarded = guard_fabricated_tool_trace(
        "Executing tool: mcp_local_run_job\nDone!"
    )

    assert guarded == "I did not call a tool, so the external operation was not performed."


def test_guard_keeps_plain_claim_text() -> None:
    # 叙述性声明不再被整段替换——是否真实由执行脚注呈现
    content = "我已经重启了 robot bridge。"

    assert guard_fabricated_tool_trace(content) == content


def test_footer_with_tool_calls_chinese() -> None:
    text = append_tool_call_footer(
        "已经装好了。",
        ["mcp_local_run_job", "mcp_local_run_job", "mcp_local_update_task_workflow"],
    )

    assert text.startswith("已经装好了。")
    assert "本回合实际工具调用:3 次" in text
    assert "mcp_local_run_job ×2" in text
    assert "mcp_local_update_task_workflow" in text


def test_footer_with_tool_calls_english() -> None:
    text = append_tool_call_footer("All done.", ["run_job"])

    assert "Tool calls this turn: 1 [run_job]" in text


def test_footer_with_zero_tool_calls() -> None:
    assert "本回合实际工具调用:0 次" in append_tool_call_footer("你好！", [])
    assert "Tool calls this turn: 0" in append_tool_call_footer("Hello!", [])


def test_footer_preserves_original_content() -> None:
    content = "步骤一完成，步骤二进行中。"

    result = append_tool_call_footer(content, ["run_job"])

    assert content in result
    assert result.index(content) == 0


def test_footer_skips_empty_content() -> None:
    assert append_tool_call_footer("", ["run_job"]) == ""
    assert append_tool_call_footer("   ", []) == ""
