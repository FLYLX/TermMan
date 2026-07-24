path = r'E:\dev\TermMan\dev\TermMan\backend\tests\services\test_reply_ticket_lifecycle.py'
content = open(path, encoding='utf-8').read()

# Fix test_intermediate_delivery: add record_tool_call before completing verification step
old = '''    task_workflow_manager.update(
        ticket.ticket_id,
        action="complete_current_step",
        note="Java installed",
    )
    task_workflow_manager.update(
        ticket.ticket_id,
        action="complete_current_step",
        note='openjdk version "17"',
    )

    assert manager.mark_delivered(ticket.ticket_id) is True'''

new = '''    task_workflow_manager.update(
        ticket.ticket_id,
        action="complete_current_step",
        note="Java installed",
    )
    task_workflow_manager.record_tool_call(
        ticket.ticket_id,
        tool_name="mcp_local_run_job",
        command="java -version",
    )
    task_workflow_manager.update(
        ticket.ticket_id,
        action="complete_current_step",
        note='openjdk version "17"',
    )

    assert manager.mark_delivered(ticket.ticket_id) is True'''

assert old in content, 'test_intermediate_delivery fix target not found'
content = content.replace(old, new, 1)

open(path, 'w', encoding='utf-8').write(content)
print('test_reply_ticket_lifecycle.py patched successfully')
