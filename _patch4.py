path = r'E:\dev\TermMan\dev\TermMan\backend\tests\services\test_task_workflow.py'
content = open(path, encoding='utf-8').read()

# Fix test: add record_tool_call before completing verification step
old = '''    manager.update(
        "ticket-java",
        action="complete_current_step",
        note='openjdk version "17.0.12"',
    )
    assert workflow.status == "ready_to_report"'''

new = '''    manager.record_tool_call(
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

assert old in content, 'test fix target not found'
content = content.replace(old, new, 1)

open(path, 'w', encoding='utf-8').write(content)
print('test_task_workflow.py patched successfully')
