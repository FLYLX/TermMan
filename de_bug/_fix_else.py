# -*- coding: utf-8 -*-
from pathlib import Path
path = Path(r"backend\app\services\agent\mcp\local_server.py")
src = path.read_text(encoding="utf-8")
old = '''        if len(robot_entries) == 1:
            message = server._format_background_job_robot_message(
                first["command"],
                first["result"],
                reply_ticket_id=robot_ticket,
            )
            message = _format_background_job_results_batch(robot_entries)'''
new = '''        if len(robot_entries) == 1:
            message = server._format_background_job_robot_message(
                first["command"],
                first["result"],
                reply_ticket_id=robot_ticket,
            )
        else:
            message = _format_background_job_results_batch(robot_entries)'''
assert src.count(old) == 1
path.write_text(src.replace(old, new), encoding="utf-8")
print("else restored")
