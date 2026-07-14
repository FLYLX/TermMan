import json

from app.core.tool_markup import (
    extract_dsml_tool_calls,
    strip_dsml_tool_markup,
)


DSML_WORKFLOW_CALL = """<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name="mcp_local_update_task_workflow">
<｜｜DSML｜｜parameter name="action" string="true">complete_current_step</｜｜DSML｜｜parameter>
<｜｜DSML｜｜parameter name="note" string="true">结果检查完成，无需QQ回复</｜｜DSML｜｜parameter>
</｜｜DSML｜｜invoke>
</｜｜DSML｜｜tool_calls>"""


def test_extract_dsml_tool_call_from_content() -> None:
    visible, calls = extract_dsml_tool_calls(
        DSML_WORKFLOW_CALL,
        allowed_tool_names={"mcp_local_update_task_workflow"},
    )

    assert visible == ""
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "mcp_local_update_task_workflow"
    assert json.loads(calls[0]["function"]["arguments"]) == {
        "action": "complete_current_step",
        "note": "结果检查完成，无需QQ回复",
    }


def test_dsml_unknown_tool_is_removed_but_not_executed() -> None:
    visible, calls = extract_dsml_tool_calls(
        DSML_WORKFLOW_CALL,
        allowed_tool_names=set(),
    )

    assert visible == ""
    assert calls == []


def test_strip_dsml_keeps_only_visible_text() -> None:
    assert strip_dsml_tool_markup(f"处理完成\n{DSML_WORKFLOW_CALL}\n请稍等") == (
        "处理完成\n\n请稍等"
    )
