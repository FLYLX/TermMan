from pathlib import Path
p = Path(r"de_bug\_strip_wf_ls.py")
s = p.read_text(encoding="utf-8")
old_head = """rep('''            else:
                message = _format_background_job_results_batch(robot_entries)
            message += server._plan_reminder(item_id, robot_ticket)"""
new_head = """rep('''        else:
                message = _format_background_job_results_batch(robot_entries)
            message += server._plan_reminder(item_id, robot_ticket)"""
assert s.count(old_head) == 1
s = s.replace(old_head, new_head)
old_tail = """                    )''',
'''            message = _format_background_job_results_batch(robot_entries)"""
new_tail = """                    )''',
'''        message = _format_background_job_results_batch(robot_entries)"""
p.write_text(s, encoding="utf-8")
print("script adjusted")
