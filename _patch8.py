path = r'E:\dev\TermMan\dev\TermMan\backend\tests\services\test_task_workflow.py'
content = open(path, encoding='utf-8').read()

old = '''    assert inserted is True
    assert workflow.objective == "\u5b89\u88c5 Temurin Java 17\uff0c\u4f7f\u7528\u53ef\u7528\u7684\u56fd\u5185\u6e90"
    # Failed step is cancelled, next step is rewritten to the new method
    assert workflow.steps[0].status == "cancelled"
    assert workflow.current_step().recovery is True
    assert workflow.current_step().title == "\u5207\u6362\u5230\u53ef\u7528\u7684\u56fd\u5185\u8f6f\u4ef6\u6e90\u5e76\u66f4\u65b0\u7d22\u5f15"

    manager.update(
        "ticket-java",
        action="complete_current_step",
        note="\u56fd\u5185\u6e90\u5df2\u5199\u5165\uff0capt-get update \u6210\u529f",
    )

    # After completing recovery, workflow is ready to report (no more steps)
    assert workflow.status == "ready_to_report"
    assert workflow.objective == "\u5b89\u88c5 Temurin Java 17\uff0c\u4f7f\u7528\u53ef\u7528\u7684\u56fd\u5185\u6e90"'''

new = '''    assert inserted is True
    assert workflow.objective == "\u5b89\u88c5 Temurin Java 17\uff0c\u4f7f\u7528\u53ef\u7528\u7684\u56fd\u5185\u6e90"
    # Failed step is cancelled, recovery step is INSERTED (not overwriting)
    assert workflow.steps[0].status == "cancelled"
    assert workflow.current_step().recovery is True
    assert workflow.current_step().title == "\u5207\u6362\u5230\u53ef\u7528\u7684\u56fd\u5185\u8f6f\u4ef6\u6e90\u5e76\u66f4\u65b0\u7d22\u5f15"
    # The original verification step is preserved after the recovery step
    assert len(workflow.steps) == 3
    assert workflow.steps[2].title == "\u9a8c\u8bc1 java -version"

    manager.update(
        "ticket-java",
        action="complete_current_step",
        note="\u56fd\u5185\u6e90\u5df2\u5199\u5165\uff0capt-get update \u6210\u529f",
    )

    # After completing recovery, advances to the preserved verification step
    assert workflow.status == "active"
    assert workflow.current_step().title == "\u9a8c\u8bc1 java -version"
    assert workflow.objective == "\u5b89\u88c5 Temurin Java 17\uff0c\u4f7f\u7528\u53ef\u7528\u7684\u56fd\u5185\u6e90"

    # Complete verification to reach ready_to_report
    manager.record_tool_call(
        "ticket-java",
        tool_name="mcp_local_run_job",
        command="java -version",
    )
    manager.update(
        "ticket-java",
        action="complete_current_step",
        note='openjdk version "17.0.12"',
    )
    assert workflow.status == "ready_to_report"'''

assert old in content, 'recovery test fix target not found'
content = content.replace(old, new, 1)

open(path, 'w', encoding='utf-8').write(content)
print('recovery test fix applied')
