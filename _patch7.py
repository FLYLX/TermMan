path = r'E:\dev\TermMan\dev\TermMan\backend\app\services\agent\task_workflow.py'
content = open(path, encoding='utf-8').read()

# Fix insert_recovery_step: INSERT a new step instead of overwriting the next one.
# This preserves subsequent steps (verification, report) that would otherwise be lost.
old = '''                    for idx in range(workflow.current_step_index + 1, len(workflow.steps)):
                        workflow.steps[idx].status = "waiting"
                        workflow.steps[idx].evidence = ""
                        workflow.steps[idx].last_error = ""
                    next_index = workflow.current_step_index + 1
                    if next_index < len(workflow.steps):
                        workflow.steps[next_index].title = recovery_title
                        workflow.steps[next_index].status = "running"
                        workflow.steps[next_index].recovery = True
                        workflow.current_step_index = next_index
                    else:
                        recovery = WorkflowStep(
                            step_id=uuid.uuid4().hex[:12],
                            title=recovery_title,
                            status="running",
                            note=note,
                            recovery=True,
                        )
                        workflow.steps.append(recovery)
                        workflow.current_step_index = len(workflow.steps) - 1'''

new = '''                    for idx in range(workflow.current_step_index + 1, len(workflow.steps)):
                        workflow.steps[idx].status = "waiting"
                        workflow.steps[idx].evidence = ""
                        workflow.steps[idx].last_error = ""
                    next_index = workflow.current_step_index + 1
                    recovery = WorkflowStep(
                        step_id=uuid.uuid4().hex[:12],
                        title=recovery_title,
                        status="running",
                        note=note,
                        recovery=True,
                    )
                    workflow.steps.insert(next_index, recovery)
                    workflow.current_step_index = next_index'''

assert old in content, 'insert_recovery_step fix target not found'
content = content.replace(old, new, 1)

open(path, 'w', encoding='utf-8').write(content)
print('insert_recovery_step fix applied')
