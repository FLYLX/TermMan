filepath = r"E:\dev\TermPaws\dev\TermPaws\backend\app\services\agent\mcp\local_server.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# Add duplicate check before _start_background_job_thread
old = '''            self._start_background_job_thread(
                item_id=str(item_id),
                command=command,
                connection=connection,
                request_kwargs=request_kwargs,
                agent_session=agent_session,
                robot_job_context=robot_job_context,
                reply_ticket_id=reply_ticket_id,
                workflow_id=job_workflow_id,
                pending_robot_reply_id=self._register_background_job_robot_reply(
                    item_id=str(item_id),
                    command=command,
                    robot_job_context=robot_job_context,
                ),
            )
            return [
                {
                    "type": "text",
                    "text": (
                        "后台任务已启动，会在独立任务里执行，完成后把最终结果自动送回 Agent。"
                        "不同后台任务可以并行启动；不要重复启动完全相同的命令。"
                    ),
                },'''

new = '''            # Check for duplicate running command
            _dup_hint = ""
            try:
                _existing = connection.call("list_jobs", {"item_uuid": str(item_id)})
                for _j in (_existing or {}).get("jobs", []):
                    if str(_j.get("command", "")).strip() == command:
                        _dup_hint = (
                            f" WARNING: identical command already running as "
                            f"job_id={_j.get('job_id','')} "
                            f"elapsed={int(float(_j.get('elapsed_seconds',0)))}s. "
                            f"Consider waiting for it instead of starting a duplicate."
                        )
                        break
            except Exception:
                pass

            self._start_background_job_thread(
                item_id=str(item_id),
                command=command,
                connection=connection,
                request_kwargs=request_kwargs,
                agent_session=agent_session,
                robot_job_context=robot_job_context,
                reply_ticket_id=reply_ticket_id,
                workflow_id=job_workflow_id,
                pending_robot_reply_id=self._register_background_job_robot_reply(
                    item_id=str(item_id),
                    command=command,
                    robot_job_context=robot_job_context,
                ),
            )
            return [
                {
                    "type": "text",
                    "text": (
                        "后台任务已启动，完成后自动送回结果。"
                        + _dup_hint
                    ),
                },'''

if old in content:
    content = content.replace(old, new, 1)
    with open(filepath, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print("PATCHED: duplicate job warning added")
else:
    print("NOT FOUND")