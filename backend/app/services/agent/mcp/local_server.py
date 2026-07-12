import asyncio
import json
import logging
import re
import sys
import threading

logger = logging.getLogger(__name__)


def debug_log(msg: str):
    print(msg, file=sys.stderr, flush=True)


TERMINAL_NOT_CONNECTED_MESSAGE = "终端未连接或未打开，命令没有发送。请先启动或连接终端后再试。"
AUTO_ROUTED_TO_JOB_MARKER = "auto_routed_execute_command_to_run_job"
BACKGROUND_JOB_STARTED_MARKER = "background_job_started"


class LocalMCPServer:
    def __init__(self):
        self._tools: dict[str, dict] = {}
        self._register_builtin_tools()
    
    def _register_builtin_tools(self):
        self.register_tool(
            name="execute_command",
            description="在主终端前台执行一条命令或向当前交互式控制台发送输入。适合 shell 短命令、Minecraft/Forge/Paper/Fabric 服务端启动、run.sh/start.sh、REPL、长期服务，以及 MC 控制台里的 op/say/stop 等后续输入。当前台已经是 Minecraft/Java server/REPL 等交互式控制台时，不要把 ls/pwd/find/cat/java -version 这类 shell 查询发进控制台；这类一次性查询应使用 run_job，系统也会自动改走后台 Job。优先一次只发一条命令，不要默认用 &&、||、;、管道或换行拼接多步操作；多步操作应等待上一条终端反馈后再继续。可设置 expected_output/expected_regex 和 timeout_seconds，超时未匹配时自动 Ctrl+C。",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的一条 shell 命令；默认不要拼接 &&、||、;、管道或换行。"},
                    "expected_output": {"type": "string", "description": "可选。预期在终端输出中出现的文本；设置后若超时未出现，可自动 Ctrl+C。"},
                    "expected_regex": {"type": "string", "description": "可选。预期输出正则；比 expected_output 更灵活。"},
                    "timeout_seconds": {"type": "integer", "description": "可选。等待预期输出的秒数，默认 20，范围 1-600。", "default": 20},
                    "auto_interrupt_on_timeout": {"type": "boolean", "description": "可选。设置预期输出时默认 true；超时未匹配则发送 Ctrl+C。"}
                },
                "required": ["command"]
            },
            handler=self._execute_command,
            skip_memory=True
        )
        self.register_tool(
            name="run_job",
            description="Start a non-interactive one-shot shell job in a daemon background process with stdin closed. Use this for downloads, package installs, builds, tests, archive extraction, and other commands that can finish without later user input; the final result and tail output will be delivered back to the agent after completion. Also use run_job for shell inspection commands such as ls, pwd, find, cat, head, tail, grep, du, df, and java -version while the main terminal is already occupied by an interactive server console. Before using it, decide whether the command needs an interactive foreground console. Do not choose run_job for Minecraft/Forge/Paper/Fabric server startup, run.sh/start.sh server launchers, REPLs, shells, watch/dev servers, or any process that should remain open for later commands such as op/say/stop; choose execute_command in the main terminal for those. Prefer one clear operation per job; avoid very long &&/pipe chains when a later step may need diagnosis.",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Non-interactive shell command to run as a one-shot job."},
                    "timeout_seconds": {"type": "integer", "description": "Maximum seconds before the job is terminated. Default 600, max 3600.", "default": 600},
                    "tail_lines": {"type": "integer", "description": "Number of final output lines returned to the agent. Default 80, max 300.", "default": 80},
                    "wait_for_completion": {"type": "boolean", "description": "Optional. Default false. When false, return immediately and deliver the final result as a later terminal event.", "default": False}
                },
                "required": ["command"]
            },
            handler=self._run_job,
            skip_memory=True
        )
        self.register_tool(
            name="list_jobs",
            description="List currently running daemon background jobs for this terminal item. Use before deciding which job to cancel.",
            input_schema={
                "type": "object",
                "properties": {},
                "required": []
            },
            handler=self._list_jobs,
            skip_memory=True
        )
        self.register_tool(
            name="cancel_job",
            description="Cancel a running daemon background job by job_id after listing jobs.",
            input_schema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job id returned by list_jobs."}
                },
                "required": ["job_id"]
            },
            handler=self._cancel_job,
            skip_memory=True
        )
        
        self.register_tool(
            name="interrupt_command",
            description="发送 Ctrl+C 中断当前终端正在运行的命令",
            input_schema={
                "type": "object",
                "properties": {},
                "required": []
            },
            handler=self._interrupt_command,
            skip_memory=True
        )
        
        self.register_tool(
            name="read_terminal_log",
            description="读取终端日志文件（原始输出），用于查看完整的错误信息或命令执行结果。",
            input_schema={
                "type": "object",
                "properties": {
                    "lines": {"type": "integer", "description": "读取最后 N 行，默认 64", "default": 64}
                },
                "required": []
            },
            handler=self._read_terminal_log,
            skip_memory=True
        )
        self.register_tool(
            name="add_terminal_input_filter_rule",
            description="Add a terminal output -> Agent input filter rule for the current item. Use when repeated terminal output is harmless noise and should stop being sent to the Agent, for example automatic backup status lines, heartbeat lines, repeated progress chatter, or plugin logs that do not need action. Default action_type is block, which drops matching terminal chunks before they reach the Agent.",
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {"type": "string", "description": "Current terminal item id."},
                    "name": {"type": "string", "description": "Short rule name, for example noise_ftb_backups."},
                    "regex_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Case-insensitive regex patterns to match noisy terminal output.",
                    },
                    "action_type": {
                        "type": "string",
                        "enum": ["block", "ignore", "log"],
                        "description": "block drops the whole matching chunk; ignore removes matching text; log marks it as needs-action. Default block.",
                        "default": "block",
                    },
                    "reason": {"type": "string", "description": "Optional human-readable reason for this rule."},
                },
                "required": ["item_id", "name", "regex_patterns"]
            },
            handler=self._add_terminal_input_filter_rule,
            skip_memory=True
        )
        self.register_tool(
            name="list_terminal_input_filter_rules",
            description="List terminal output -> Agent input filter rules for the current item. Use before adding a new noise rule when unsure whether one already exists.",
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {"type": "string", "description": "Current terminal item id."},
                },
                "required": ["item_id"]
            },
            handler=self._list_terminal_input_filter_rules,
            skip_memory=True
        )
        self.register_tool(
            name="delete_terminal_input_filter_rule",
            description="Delete one terminal output -> Agent input filter rule for the current item by rule name.",
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {"type": "string", "description": "Current terminal item id."},
                    "name": {"type": "string", "description": "Rule name returned by list_terminal_input_filter_rules."},
                    "disable_when_empty": {
                        "type": "boolean",
                        "description": "Disable input_filter_enabled when no rules remain. Default true.",
                        "default": True,
                    },
                },
                "required": ["item_id", "name"]
            },
            handler=self._delete_terminal_input_filter_rule,
            skip_memory=True
        )
        self.register_tool(
            name="clear_terminal_input_filter_rules",
            description="Delete all terminal output -> Agent input filter rules for the current item.",
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {"type": "string", "description": "Current terminal item id."},
                    "disable": {
                        "type": "boolean",
                        "description": "Disable input_filter_enabled after clearing. Default true.",
                        "default": True,
                    },
                },
                "required": ["item_id"]
            },
            handler=self._clear_terminal_input_filter_rules,
            skip_memory=True
        )
        
        self.register_tool(
            name="list_installed_software",
            description="List software that has been recorded as installed for the current terminal item.",
            input_schema={
                "type": "object",
                "properties": {},
                "required": []
            },
            handler=self._list_installed_software,
            skip_memory=True
        )

        self.register_tool(
            name="record_installed_software",
            description="Record software as installed after terminal output confirms installation succeeded.",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Software or package name"},
                    "manager": {"type": "string", "description": "Package manager or source, such as apt, pip, npm, bun, manual"},
                    "version": {"type": "string", "description": "Installed version if known"},
                    "command": {"type": "string", "description": "Command that installed it"},
                    "notes": {"type": "string", "description": "Short verification notes"}
                },
                "required": ["name"]
            },
            handler=self._record_installed_software,
            skip_memory=True
        )

        self.register_tool(
            name="remove_installed_software",
            description="Remove software from the recorded installed list after uninstall is confirmed.",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Software or package name"},
                    "manager": {"type": "string", "description": "Package manager or source"},
                    "reason": {"type": "string", "description": "Why it was removed from the list"}
                },
                "required": ["name"]
            },
            handler=self._remove_installed_software,
            skip_memory=True
        )
        self.register_tool(
            name="save_memory",
            description="保存稳定、可复用、已验证的重要信息到长期记忆中。不要保存原生日志、命令回显、等待态消息或敏感信息。",
            input_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "要保存的记忆内容"},
                    "memory_type": {"type": "string", "enum": ["fact", "preference", "task", "error", "context"], "description": "记忆类型: fact(事实), preference(偏好), task(任务), error(错误), context(上下文)"},
                    "ttl_days": {"type": "integer", "description": "过期天数，默认 30 天", "default": 30}
                },
                "required": ["content"]
            },
            handler=self._save_memory
        )
        
        self.register_tool(
            name="recall_memory",
            description="从长期记忆中检索相关信息。使用语义搜索，返回与查询最相关的记忆。",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词或问题"},
                    "n_results": {"type": "integer", "description": "返回结果数量，默认 5", "default": 5},
                    "memory_type": {"type": "string", "enum": ["fact", "preference", "task", "error", "context"], "description": "可选：限定记忆类型"}
                },
                "required": ["query"]
            },
            handler=self._recall_memory
        )
        
        self.register_tool(
            name="list_memories",
            description="列出所有记忆，可按类型过滤。",
            input_schema={
                "type": "object",
                "properties": {
                    "memory_type": {"type": "string", "enum": ["fact", "preference", "task", "error", "context"], "description": "可选：限定记忆类型"}
                },
                "required": []
            },
            handler=self._list_memories
        )
        
        self.register_tool(
            name="delete_memory",
            description="删除指定的记忆。",
            input_schema={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "description": "要删除的记忆 ID"}
                },
                "required": ["memory_id"]
            },
            handler=self._delete_memory
        )
    
    def register_tool(self, name: str, description: str, input_schema: dict, handler: callable, skip_memory: bool = False):
        self._tools[name] = {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
            "handler": handler,
            "skip_memory": skip_memory
        }
    
    def _restore_existing_terminal_input(self, item_id: str) -> bool:
        try:
            import uuid

            from sqlmodel import Session

            from app.core.db import engine
            from app.models import Item
            from app.services import DaemonConfig, connection_manager, socket_pool_facade
            from app.services.terminal_service import TerminalService

            try:
                item_uuid = uuid.UUID(str(item_id))
            except ValueError:
                debug_log(f"[LocalMCPServer] invalid item_id for restore: {item_id}")
                return False

            with Session(engine) as db:
                item = db.get(Item, item_uuid)
                if not item:
                    debug_log(f"[LocalMCPServer] item not found for restore: {item_id}")
                    return False
                if not item.socket_host or not item.socket_port or not item.api_key:
                    debug_log(f"[LocalMCPServer] item missing daemon config for restore: {item_id}")
                    return False

                daemon_config = DaemonConfig(item.socket_host, item.socket_port, item.api_key)
                owner_uuid = str(item.owner_id)

            connection = connection_manager.get_or_create_connection(daemon_config)
            if not connection.is_connected():
                debug_log(f"[LocalMCPServer] daemon not connected for restore: {item_id}")
                return False

            status_result = connection.terminal_status_http(str(item_id))
            if not status_result.get("success"):
                debug_log(
                    f"[LocalMCPServer] terminal status unavailable for restore: {item_id}, "
                    f"error={status_result.get('error')}"
                )
                return False

            status_data = status_result.get("data") or {}
            terminal_status = str(status_data.get("status") or "")
            token = status_data.get("token")
            if terminal_status not in {"running", "waiting_backend"} or not token:
                debug_log(
                    f"[LocalMCPServer] terminal not active for restore: {item_id}, "
                    f"status={terminal_status}, token={bool(token)}"
                )
                return False

            terminal_service = TerminalService(connection_manager, socket_pool_facade)
            restored = terminal_service.restore_terminal_session(
                item_uuid=str(item_id),
                owner_uuid=owner_uuid,
                daemon_config=daemon_config,
                token=str(token),
            )
            debug_log(f"[LocalMCPServer] terminal input restore result: item={item_id}, restored={restored}")
            return bool(restored)
        except Exception as exc:
            debug_log(f"[LocalMCPServer] terminal input restore error for item={item_id}: {exc}")
            return False

    def _ensure_terminal_input_handler(self, item_id: str) -> bool:
        from app.services.socket_pool.input_center import input_center

        if input_center.has_handler(item_id):
            return True
        if self._restore_existing_terminal_input(item_id):
            return input_center.has_handler(item_id)
        return False

    def _get_item_daemon_context(self, item_id: str):
        import uuid

        from sqlmodel import Session

        from app.core.db import engine
        from app.models import Item
        from app.services import DaemonConfig, connection_manager

        try:
            item_uuid = uuid.UUID(str(item_id))
        except ValueError:
            raise ValueError(f"invalid item_id: {item_id}")

        with Session(engine) as db:
            item = db.get(Item, item_uuid)
            if not item:
                raise ValueError(f"item not found: {item_id}")
            if not item.socket_host or not item.socket_port or not item.api_key:
                raise ValueError(f"daemon is not configured for item: {item_id}")
            daemon_config = DaemonConfig(item.socket_host, item.socket_port, item.api_key)
            connection = connection_manager.get_or_create_connection(daemon_config)
            return item, connection

    def _coerce_job_int(self, value, default: int, minimum: int, maximum: int) -> int:
        try:
            coerced = int(float(value)) if value is not None and value != "" else default
        except (TypeError, ValueError):
            coerced = default
        return max(minimum, min(coerced, maximum))

    def _format_job_result(self, result: dict) -> str:
        exit_code = result.get("exit_code")
        timed_out = bool(result.get("timed_out"))
        status = "timed out" if timed_out else ("succeeded" if exit_code == 0 else "failed")
        output_tail = (result.get("output_tail") or "").strip() or "(no output)"
        return (
            f"Job {status}\n"
            f"job_id: {result.get('job_id', '')}\n"
            f"command: {result.get('command', '')}\n"
            f"cwd: {result.get('cwd', '')}\n"
            f"exit_code: {exit_code}\n"
            f"timed_out: {timed_out}\n"
            f"duration_seconds: {result.get('duration_seconds', '')}\n"
            f"output_tail:\n{output_tail}"
        )

    def _format_jobs_result(self, result: dict) -> str:
        jobs = result.get("jobs") or []
        if not jobs:
            return "没有运行中的后台任务。"
        lines = [f"运行中的后台任务：{len(jobs)} 个"]
        for job in jobs:
            command = str(job.get("command") or "")
            if len(command) > 120:
                command = f"{command[:117]}..."
            lines.append(
                " - "
                f"job_id={job.get('job_id', '')} "
                f"elapsed={int(float(job.get('elapsed_seconds') or 0))}s "
                f"cancel_requested={bool(job.get('cancel_requested'))} "
                f"command={command}"
            )
            output_tail = str(job.get("output_tail") or "").strip()
            if output_tail:
                if len(output_tail) > 1200:
                    output_tail = f"{output_tail[-1200:]}"
                lines.append(f"   output_tail:\n{output_tail}")
        return "\n".join(lines)

    def _list_jobs(self, args: dict) -> list:
        item_id = args.get("item_id", "")
        if not item_id:
            return [{"type": "text", "text": "Error: item_id required"}]
        try:
            _item, connection = self._get_item_daemon_context(str(item_id))
            result = connection.list_jobs_http(item_uuid=str(item_id))
            if not result.get("success"):
                return [{"type": "text", "text": f"Error: {result.get('error', 'failed to list jobs')}"}]
            return [{"type": "text", "text": self._format_jobs_result(result)}]
        except Exception as e:
            debug_log(f"[LocalMCPServer] list_jobs error: {e}")
            return [{"type": "text", "text": f"Error: {e}"}]

    def _cancel_job(self, args: dict) -> list:
        item_id = args.get("item_id", "")
        job_id = str(args.get("job_id") or "").strip()
        if not item_id or not job_id:
            return [{"type": "text", "text": "Error: item_id and job_id required"}]
        try:
            _item, connection = self._get_item_daemon_context(str(item_id))
            result = connection.cancel_job_http(item_uuid=str(item_id), job_id=job_id)
            if result.get("success") or result.get("cancelled"):
                from app.services.agent.session import agent_session_manager

                agent_session = agent_session_manager.get_session(str(item_id))
                if agent_session:
                    agent_session.clear_terminal_job()
                return [{"type": "text", "text": f"后台任务已取消：{result.get('job_id', job_id)}"}]
            return [{"type": "text", "text": f"Error: {result.get('error', 'failed to cancel job')}"}]
        except Exception as e:
            debug_log(f"[LocalMCPServer] cancel_job error: {e}")
            return [{"type": "text", "text": f"Error: {e}"}]

    def _run_job(self, args: dict) -> list:
        command = (args.get("command") or "").strip()
        item_id = args.get("item_id", "")
        if not command or not item_id:
            return [{"type": "text", "text": "Error: command and item_id required"}]

        timeout_seconds = self._coerce_job_int(args.get("timeout_seconds"), 600, 1, 3600)
        tail_lines = self._coerce_job_int(args.get("tail_lines"), 80, 1, 300)
        wait_for_completion = bool(args.get("wait_for_completion"))
        robot_job_context = self._robot_job_context_from_args(args)
        reply_ticket_id = str(args.get("_reply_ticket_id") or "").strip()
        if reply_ticket_id:
            try:
                from app.services.agent.reply_ticket import reply_ticket_manager

                reply_ticket_manager.mark_command(reply_ticket_id, command)
            except Exception:
                pass
        debug_log(
            f"[LocalMCPServer] _run_job: item={item_id}, timeout={timeout_seconds}, tail_lines={tail_lines}, wait={wait_for_completion}, command={command}"
        )
        agent_session = None
        try:
            from app.services.agent.session import RUN_JOB_TOOL_NAME, agent_session_manager

            agent_session = agent_session_manager.get_session(str(item_id))
            if agent_session:
                guard_error = agent_session.validate_terminal_tool_input(
                    RUN_JOB_TOOL_NAME,
                    {
                        "item_id": str(item_id),
                        "command": command,
                        "timeout_seconds": timeout_seconds,
                    },
                )
                if guard_error:
                    debug_log(
                        f"[LocalMCPServer] run_job blocked before start: item={item_id}, command={command}"
                    )
                    return [{"type": "text", "text": guard_error}]
                agent_session.mark_terminal_job_started(
                    RUN_JOB_TOOL_NAME,
                    {
                        "item_id": str(item_id),
                        "command": command,
                        "timeout_seconds": timeout_seconds,
                    },
                )
        except Exception as guard_error:
            debug_log(f"[LocalMCPServer] run_job guard error: {guard_error}")
            agent_session = None

        try:
            item, connection = self._get_item_daemon_context(str(item_id))
            request_kwargs = {
                "item_uuid": str(item_id),
                "user_uuid": str(item.owner_id),
                "command": command,
                "working_directory": item.working_directory,
                "timeout_seconds": timeout_seconds,
                "tail_lines": tail_lines,
            }

            if wait_for_completion:
                result = connection.run_job_http(**request_kwargs)
                debug_log(
                    f"[LocalMCPServer] run_job result: item={item_id}, success={result.get('success')}, exit_code={result.get('exit_code')}, timed_out={result.get('timed_out')}"
                )
                if not result.get("success"):
                    return [{"type": "text", "text": f"Error: {result.get('error', 'daemon job failed')}"}]
                return [{"type": "text", "text": self._format_job_result(result)}]

            self._start_background_job_thread(
                item_id=str(item_id),
                command=command,
                connection=connection,
                request_kwargs=request_kwargs,
                agent_session=agent_session,
                robot_job_context=robot_job_context,
                reply_ticket_id=reply_ticket_id,
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
                        "后台任务已启动。下载、安装或构建会在独立任务里执行，"
                        "完成后会把最终结果自动送回 Agent；在完成前不要重复发送新的终端命令。"
                    ),
                },
                {
                    "type": "metadata",
                    BACKGROUND_JOB_STARTED_MARKER: True,
                    "effective_tool_name": "mcp_local_run_job",
                },
            ]
        except Exception as e:
            debug_log(f"[LocalMCPServer] run_job error: {e}")
            if agent_session:
                agent_session.clear_terminal_job(command)
            return [{"type": "text", "text": f"Error: {e}"}]
        finally:
            if wait_for_completion and agent_session:
                agent_session.clear_terminal_job(command)

    def _start_background_job_thread(
        self,
        *,
        item_id: str,
        command: str,
        connection,
        request_kwargs: dict,
        agent_session,
        robot_job_context: dict | None = None,
        reply_ticket_id: str = "",
        pending_robot_reply_id: str | None = None,
    ) -> None:
        def worker() -> None:
            result: dict
            try:
                result = connection.run_job_http(**request_kwargs)
                debug_log(
                    f"[LocalMCPServer] background run_job result: item={item_id}, success={result.get('success')}, exit_code={result.get('exit_code')}, timed_out={result.get('timed_out')}"
                )
            except Exception as exc:
                debug_log(f"[LocalMCPServer] background run_job error: item={item_id}, error={exc}")
                result = {
                    "success": False,
                    "error": str(exc),
                    "command": command,
                    "job_id": "",
                    "exit_code": None,
                    "timed_out": False,
                    "duration_seconds": "",
                    "output_tail": "",
                }

            feedback = self._format_background_job_feedback(result)
            delivered_by_ticket = self._deliver_background_job_to_reply_ticket(
                reply_ticket_id=reply_ticket_id,
                command=command,
                result=result,
            )
            if delivered_by_ticket and pending_robot_reply_id and robot_job_context:
                self._clear_background_job_robot_reply(
                    robot_job_context=robot_job_context,
                    pending_reply_id=pending_robot_reply_id,
                )
            if not delivered_by_ticket:
                self._deliver_background_job_to_robot(
                    item_id=item_id,
                    command=command,
                    result=result,
                    robot_job_context=robot_job_context,
                    pending_reply_id=pending_robot_reply_id or "",
                )
            if robot_job_context or delivered_by_ticket:
                feedback = (
                    f"{feedback}\n"
                    "[Reply ticket notification handled for the source that started this job.]"
                )

            if agent_session:
                agent_session.clear_terminal_job(command)
                try:
                    from app.services.agent.session import InputMessage, InputType

                    agent_session.process_input(
                        InputMessage(
                            input_type=InputType.TERMINAL,
                            content=feedback,
                            raw_content=feedback,
                            query="background job completed",
                        )
                    )
                except Exception as exc:
                    debug_log(
                        f"[LocalMCPServer] failed to deliver background job feedback: item={item_id}, error={exc}"
                    )

        thread = threading.Thread(
            target=worker,
            name=f"termman-job-{item_id[:8]}",
            daemon=True,
        )
        thread.start()

    def _robot_job_context_from_args(self, args: dict) -> dict | None:
        context_token = str(args.get("_robot_context_token") or "").strip()
        if not context_token:
            return None
        try:
            from app.plugins.robot.mcp.context import get_robot_mcp_context

            context = get_robot_mcp_context(context_token)
            if context is None or getattr(context, "reply_target", None) is None:
                return None
            return {
                "robot_id": str(getattr(context, "robot_id", "") or ""),
                "sender_key": str(getattr(context, "sender_key", "") or ""),
                "reply_target": context.reply_target.model_dump(mode="json"),
                "conversation_key": str(getattr(context, "conversation_key", "") or ""),
                "conversation_generation": int(
                    getattr(context, "conversation_generation", 0) or 0
                ),
            }
        except Exception as exc:
            debug_log(f"[LocalMCPServer] failed to capture robot job context: {exc}")
            return None

    def _register_background_job_robot_reply(
        self,
        *,
        item_id: str,
        command: str,
        robot_job_context: dict | None,
    ) -> str | None:
        if not robot_job_context:
            return None
        try:
            from app.plugins.robot.service import robot_service

            return robot_service.register_background_job_reply(
                robot_id=robot_job_context.get("robot_id", ""),
                item_id=item_id,
                sender_key=robot_job_context.get("sender_key", ""),
                reply_target=robot_job_context.get("reply_target") or {},
                conversation_key=robot_job_context.get("conversation_key", ""),
                conversation_generation=int(
                    robot_job_context.get("conversation_generation") or 0
                ),
                command=command,
            )
        except Exception as exc:
            debug_log(
                f"[LocalMCPServer] failed to register robot background job reply: item={item_id}, error={exc}"
            )
            return None

    def _deliver_background_job_to_robot(
        self,
        *,
        item_id: str,
        command: str,
        result: dict,
        robot_job_context: dict | None,
        pending_reply_id: str = "",
    ) -> None:
        if not robot_job_context:
            return
        try:
            from app.plugins.robot.service import robot_service

            message = self._format_background_job_robot_message(command, result)
            queued = robot_service.enqueue_background_job_result(
                robot_id=robot_job_context.get("robot_id", ""),
                item_id=item_id,
                sender_key=robot_job_context.get("sender_key", ""),
                reply_target=robot_job_context.get("reply_target") or {},
                conversation_key=robot_job_context.get("conversation_key", ""),
                conversation_generation=int(
                    robot_job_context.get("conversation_generation") or 0
                ),
                message=message,
                pending_reply_id=pending_reply_id,
            )
            if not queued:
                debug_log(
                    f"[LocalMCPServer] robot background job result not queued: item={item_id}, command={command}"
                )
        except Exception as exc:
            debug_log(
                f"[LocalMCPServer] failed to queue robot background job result: item={item_id}, error={exc}"
            )
            if pending_reply_id:
                self._clear_background_job_robot_reply(
                    robot_job_context=robot_job_context,
                    pending_reply_id=pending_reply_id,
                )

    def _clear_background_job_robot_reply(
        self,
        *,
        robot_job_context: dict | None,
        pending_reply_id: str,
    ) -> None:
        if not robot_job_context or not pending_reply_id:
            return
        try:
            from app.plugins.robot.service import robot_service

            robot_service.clear_background_job_reply(
                robot_id=robot_job_context.get("robot_id", ""),
                conversation_key=robot_job_context.get("conversation_key", ""),
                pending_reply_id=pending_reply_id,
            )
        except Exception:
            pass

    def _deliver_background_job_to_reply_ticket(
        self,
        *,
        reply_ticket_id: str,
        command: str,
        result: dict,
    ) -> bool:
        if not reply_ticket_id:
            return False
        try:
            from app.services.agent.reply_ticket import reply_ticket_manager

            message = self._format_background_job_reply_ticket_message(command, result)
            return reply_ticket_manager.deliver(reply_ticket_id, message)
        except Exception as exc:
            debug_log(
                f"[LocalMCPServer] failed to deliver background job via reply ticket: ticket={reply_ticket_id}, error={exc}"
            )
            return False

    def _format_background_job_reply_ticket_message(self, command: str, result: dict) -> str:
        if result.get("success"):
            duration = result.get("duration_seconds")
            duration_text = f"，耗时 {duration}s" if duration not in (None, "") else ""
            return f"后台任务完成了：{command}。退出码 {result.get('exit_code', 0)}{duration_text}。"
        error = str(result.get("error") or "daemon job failed").strip()
        if len(error) > 160:
            error = f"{error[:157]}..."
        return f"后台任务失败了：{command}。原因：{error}"

    def _format_background_job_robot_message(self, command: str, result: dict) -> str:
        status = "completed" if result.get("success") else "failed"
        return (
            "[Background terminal job result for this QQ conversation]\n"
            "The terminal background job requested from this QQ conversation has "
            f"{status}. Summarize the result briefly in Chinese, mention success "
            "or failure, and do not paste full logs unless the failure reason needs it.\n"
            f"Command: {command}\n"
            f"{self._format_job_result(result)}"
        )

    def _format_background_job_feedback(self, result: dict) -> str:
        if result.get("success"):
            return (
                "[Background terminal job completed]\n"
                "后台任务已完成，请根据最终结果继续处理后续步骤。\n"
                f"{self._format_job_result(result)}"
            )
        return (
            "[Background terminal job failed]\n"
            "后台任务请求失败，请根据错误信息决定是否重试或换方案。\n"
            f"Error: {result.get('error', 'daemon job failed')}\n"
            f"command: {result.get('command', '')}"
        )

    def _execute_command(self, args: dict) -> list:
        command = args.get("command", "")
        item_id = args.get("item_id", "")
        
        debug_log(f"[LocalMCPServer] _execute_command: item={item_id}, command={command}")
        
        if not command or not item_id:
            return [{"type": "text", "text": "Error: command and item_id required"}]
        
        try:
            if self._should_auto_route_execute_command_to_job(str(command), str(item_id)):
                debug_log(
                    f"[LocalMCPServer] auto-routing execute_command to run_job: item={item_id}, command={command}"
                )
                job_args = dict(args)
                job_args["item_id"] = item_id
                job_args["command"] = command
                job_args["timeout_seconds"] = self._coerce_job_int(
                    job_args.get("timeout_seconds"),
                    600,
                    60,
                    3600,
                )
                job_args.setdefault("tail_lines", 80)
                job_args["wait_for_completion"] = False
                result = self._run_job(job_args)
                result_text = "\n".join(
                    item.get("text", "")
                    for item in result
                    if isinstance(item, dict) and item.get("type") == "text"
                ).strip()
                return [
                    {
                        "type": "text",
                        "text": "\u5df2\u81ea\u52a8\u6539\u4e3a\u540e\u53f0 Job \u6267\u884c\uff0c\u7ec8\u7aef\u524d\u53f0\u8f93\u5165\u4e0d\u4f1a\u88ab\u9501\u5b9a\u3002"
                        + (f"\n{result_text}" if result_text else ""),
                    },
                    {
                        "type": "metadata",
                        AUTO_ROUTED_TO_JOB_MARKER: True,
                        BACKGROUND_JOB_STARTED_MARKER: True,
                        "effective_tool_name": "mcp_local_run_job",
                    },
                ]

            try:
                from app.services.agent.session import (
                    EXECUTE_COMMAND_TOOL_NAME,
                    agent_session_manager,
                )

                existing_session = agent_session_manager.get_session(str(item_id))
                if existing_session:
                    terminal_input_error = existing_session.validate_terminal_tool_input(
                        EXECUTE_COMMAND_TOOL_NAME,
                        {"item_id": str(item_id), "command": command},
                    )
                    if terminal_input_error:
                        debug_log(
                            f"[LocalMCPServer] command blocked before send: item={item_id}, command={command}"
                        )
                        return [{"type": "text", "text": terminal_input_error}]
            except Exception as guard_error:
                debug_log(f"[LocalMCPServer] terminal input guard error: {guard_error}")

            from app.services.socket_pool import InputSDK
            has_handler = self._ensure_terminal_input_handler(item_id)
            debug_log(f"[LocalMCPServer] has_handler={has_handler}")
            if not has_handler:
                return [{"type": "text", "text": TERMINAL_NOT_CONNECTED_MESSAGE}]
            
            if not command.endswith("\n"):
                command = command + "\n"
            
            success = InputSDK().send(item_id, command)
            debug_log(f"[LocalMCPServer] send result: success={success}")
            
            return [
                {
                    "type": "text",
                    "text": (
                        f"命令已发送到终端，尚未确认执行结果: {command.strip()}"
                        if success
                        else TERMINAL_NOT_CONNECTED_MESSAGE
                    ),
                }
            ]
        except Exception as e:
            debug_log(f"[LocalMCPServer] execute_command error: {e}")
            return [{"type": "text", "text": f"Error: {e}"}]

    def _should_auto_route_execute_command_to_job(self, command: str, item_id: str = "") -> bool:
        try:
            from app.services.agent.session import (
                TERMINAL_INPUT_MODE_BUSY,
                classify_terminal_input_mode,
                agent_session_manager,
            )

            agent_session = (
                agent_session_manager.get_session(str(item_id)) if item_id else None
            )
            if agent_session and agent_session.should_route_execute_command_to_background_job(
                command
            ):
                return True
            return classify_terminal_input_mode(command) == TERMINAL_INPUT_MODE_BUSY
        except Exception as exc:
            debug_log(f"[LocalMCPServer] auto-route classification error: {exc}")
            return False
    
    def _cancel_running_job_for_item(self, item_id: str) -> dict | None:
        try:
            from app.services.agent.session import agent_session_manager

            agent_session = agent_session_manager.get_session(str(item_id))
            if not agent_session or not agent_session.has_running_terminal_job():
                return None

            _item, connection = self._get_item_daemon_context(str(item_id))
            result = connection.cancel_job_http(item_uuid=str(item_id))
            if result.get("success") or result.get("cancelled"):
                agent_session.clear_terminal_job()
            elif result.get("error") == "No running job for item":
                agent_session.clear_terminal_job()
                result["local_lock_cleared"] = True
            return result
        except Exception as exc:
            debug_log(f"[LocalMCPServer] cancel running job error for item={item_id}: {exc}")
            return {"success": False, "error": str(exc)}

    def _interrupt_command(self, args: dict) -> list:
        item_id = args.get("item_id", "")
        
        debug_log(f"[LocalMCPServer] _interrupt_command: item={item_id}")
        
        if not item_id:
            return [{"type": "text", "text": "Error: item_id required"}]

        cancel_result = self._cancel_running_job_for_item(str(item_id))
        if cancel_result is not None:
            if cancel_result.get("success") or cancel_result.get("cancelled"):
                return [{"type": "text", "text": "\u540e\u53f0\u4efb\u52a1\u5df2\u4e2d\u65ad\uff0c\u7ec8\u7aef\u9501\u5df2\u91ca\u653e\u3002"}]
            if cancel_result.get("local_lock_cleared"):
                return [{"type": "text", "text": "daemon \u91cc\u6ca1\u6709\u627e\u5230\u6b63\u5728\u8fd0\u884c\u7684\u540e\u53f0\u4efb\u52a1\uff0c\u5df2\u6e05\u7406\u672c\u5730\u7ec8\u7aef\u9501\u3002"}]
            return [{"type": "text", "text": f"\u540e\u53f0\u4efb\u52a1\u4e2d\u65ad\u5931\u8d25: {cancel_result.get('error', 'unknown error')}"}]
        
        try:
            from app.services.socket_pool import InputSDK
            has_handler = self._ensure_terminal_input_handler(item_id)
            debug_log(f"[LocalMCPServer] interrupt has_handler={has_handler}")
            if not has_handler:
                return [{"type": "text", "text": TERMINAL_NOT_CONNECTED_MESSAGE}]
            
            success = InputSDK().send(item_id, "\x03")
            debug_log(f"[LocalMCPServer] interrupt result: success={success}")
            
            return [
                {
                    "type": "text",
                    "text": (
                        "Ctrl+C 已发送到终端，是否已中断需等待后续输出确认"
                        if success
                        else "Ctrl+C 发送失败"
                    ),
                }
            ]
        except Exception as e:
            debug_log(f"[LocalMCPServer] interrupt error: {e}")
            return [{"type": "text", "text": f"Error: {e}"}]
    
    def _read_terminal_log(self, args: dict) -> list:
        item_id = args.get("item_id", "")
        lines = args.get("lines", 64)
        
        if not item_id:
            return [{"type": "text", "text": "Error: item_id required"}]
        
        try:
            from app.services.log_manager import LogManager
            content = LogManager().get_last_lines(item_id, lines)
            
            if not content:
                return [{"type": "text", "text": f"No log found for {item_id}"}]
            
            return [{"type": "text", "text": f"=== 终端日志 (最后 {lines} 行) ===\n{content}"}]
        except Exception as e:
            return [{"type": "text", "text": f"Error: {e}"}]

    def _sanitize_filter_rule_name(self, name: str, existing: set[str]) -> str:
        candidate = re.sub(r"[^a-zA-Z0-9_]+", "_", (name or "").strip().lower()).strip("_")
        if not candidate:
            candidate = "agent_noise_filter"
        if candidate not in existing:
            return candidate
        suffix = 2
        while f"{candidate}_{suffix}" in existing:
            suffix += 1
        return f"{candidate}_{suffix}"

    def _coerce_filter_patterns(self, raw_patterns) -> list[str]:
        if not isinstance(raw_patterns, list):
            raise ValueError("regex_patterns must be a non-empty list of strings")
        patterns: list[str] = []
        for raw_pattern in raw_patterns:
            if not isinstance(raw_pattern, str):
                continue
            pattern = raw_pattern.strip()
            if not pattern:
                continue
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"invalid regex pattern {pattern!r}: {exc}") from exc
            if pattern not in patterns:
                patterns.append(pattern)
        if not patterns:
            raise ValueError("regex_patterns must contain at least one valid regex")
        return patterns

    def _add_terminal_input_filter_rule(self, args: dict) -> list:
        item_id = str(args.get("item_id") or "").strip()
        name = str(args.get("name") or "agent_noise_filter").strip()
        action_type = str(args.get("action_type") or "block").strip().lower()
        reason = str(args.get("reason") or "").strip()
        if action_type not in {"block", "ignore", "log"}:
            return [{"type": "text", "text": "Error: action_type must be block, ignore, or log"}]
        try:
            import uuid

            from sqlmodel import Session

            from app.core.db import engine
            from app.models import Item

            try:
                item_uuid = uuid.UUID(item_id)
            except ValueError as exc:
                raise ValueError(f"invalid item_id: {item_id}") from exc

            patterns = self._coerce_filter_patterns(args.get("regex_patterns"))
            with Session(engine) as db:
                item = db.get(Item, item_uuid)
                if not item:
                    raise ValueError(f"item not found: {item_id}")

                rules = dict(item.input_filter_rules or {})
                for rule_name, rule in rules.items():
                    if not isinstance(rule, dict):
                        continue
                    existing_patterns = [
                        p for p in rule.get("regex_patterns", []) if isinstance(p, str)
                    ]
                    if (
                        rule.get("action_type", "ignore") == action_type
                        and all(pattern in existing_patterns for pattern in patterns)
                    ):
                        item.input_filter_enabled = True
                        db.add(item)
                        db.commit()
                        return [
                            {
                                "type": "text",
                                "text": (
                                    "Terminal input filter already contains this rule: "
                                    f"{rule_name}. input_filter_enabled=true"
                                ),
                            }
                        ]

                normalized_name = re.sub(
                    r"[^a-zA-Z0-9_]+",
                    "_",
                    name.lower(),
                ).strip("_")
                if normalized_name in rules and isinstance(rules[normalized_name], dict):
                    rule = dict(rules[normalized_name])
                    existing_patterns = [
                        p for p in rule.get("regex_patterns", []) if isinstance(p, str)
                    ]
                    merged_patterns = existing_patterns + [
                        pattern for pattern in patterns if pattern not in existing_patterns
                    ]
                    rule["regex_patterns"] = merged_patterns
                    rule["action_type"] = action_type
                    if reason:
                        rule["reason"] = reason
                    rules[normalized_name] = rule
                    rule_name = normalized_name
                else:
                    rule_name = self._sanitize_filter_rule_name(name, set(rules))
                    rule_payload = {
                        "regex_patterns": patterns,
                        "action_type": action_type,
                    }
                    if reason:
                        rule_payload["reason"] = reason
                    rules[rule_name] = rule_payload

                item.input_filter_enabled = True
                item.input_filter_rules = rules
                db.add(item)
                db.commit()

            return [
                {
                    "type": "text",
                    "text": (
                        "Added terminal output -> Agent input filter rule "
                        f"`{rule_name}` action={action_type}; patterns={len(patterns)}. "
                        "input_filter_enabled=true"
                    ),
                }
            ]
        except Exception as e:
            debug_log(f"[LocalMCPServer] add terminal input filter rule error: {e}")
            return [{"type": "text", "text": f"Error: {e}"}]

    def _list_terminal_input_filter_rules(self, args: dict) -> list:
        item_id = str(args.get("item_id") or "").strip()
        try:
            import uuid

            from sqlmodel import Session

            from app.core.db import engine
            from app.models import Item

            try:
                item_uuid = uuid.UUID(item_id)
            except ValueError as exc:
                raise ValueError(f"invalid item_id: {item_id}") from exc

            with Session(engine) as db:
                item = db.get(Item, item_uuid)
                if not item:
                    raise ValueError(f"item not found: {item_id}")
                enabled = bool(item.input_filter_enabled)
                rules = item.input_filter_rules or {}

            if not rules:
                return [
                    {
                        "type": "text",
                        "text": f"Terminal input filter enabled={enabled}; no rules.",
                    }
                ]

            lines = [f"Terminal input filter enabled={enabled}; rules={len(rules)}"]
            for rule_name, rule in rules.items():
                if not isinstance(rule, dict):
                    continue
                patterns = rule.get("regex_patterns", [])
                action_type = rule.get("action_type", "ignore")
                lines.append(
                    f"- {rule_name}: action={action_type}, patterns={len(patterns)}"
                )
                for pattern in patterns[:5]:
                    lines.append(f"  - {pattern}")
                if len(patterns) > 5:
                    lines.append(f"  - ... {len(patterns) - 5} more")
            return [{"type": "text", "text": "\n".join(lines)}]
        except Exception as e:
            debug_log(f"[LocalMCPServer] list terminal input filter rules error: {e}")
            return [{"type": "text", "text": f"Error: {e}"}]

    def _delete_terminal_input_filter_rule(self, args: dict) -> list:
        item_id = str(args.get("item_id") or "").strip()
        name = str(args.get("name") or "").strip()
        disable_when_empty = bool(args.get("disable_when_empty", True))
        if not name:
            return [{"type": "text", "text": "Error: name is required"}]
        try:
            import uuid

            from sqlmodel import Session

            from app.core.db import engine
            from app.models import Item

            try:
                item_uuid = uuid.UUID(item_id)
            except ValueError as exc:
                raise ValueError(f"invalid item_id: {item_id}") from exc

            with Session(engine) as db:
                item = db.get(Item, item_uuid)
                if not item:
                    raise ValueError(f"item not found: {item_id}")

                rules = dict(item.input_filter_rules or {})
                if name not in rules:
                    existing = ", ".join(sorted(rules)) or "none"
                    return [
                        {
                            "type": "text",
                            "text": (
                                f"Terminal input filter rule not found: {name}. "
                                f"Existing rules: {existing}"
                            ),
                        }
                    ]

                rules.pop(name, None)
                item.input_filter_rules = rules
                if disable_when_empty and not rules:
                    item.input_filter_enabled = False
                enabled = bool(item.input_filter_enabled)
                db.add(item)
                db.commit()

            return [
                {
                    "type": "text",
                    "text": (
                        f"Deleted terminal output -> Agent input filter rule `{name}`. "
                        f"remaining={len(rules)} input_filter_enabled={enabled}"
                    ),
                }
            ]
        except Exception as e:
            debug_log(f"[LocalMCPServer] delete terminal input filter rule error: {e}")
            return [{"type": "text", "text": f"Error: {e}"}]

    def _clear_terminal_input_filter_rules(self, args: dict) -> list:
        item_id = str(args.get("item_id") or "").strip()
        disable = bool(args.get("disable", True))
        try:
            import uuid

            from sqlmodel import Session

            from app.core.db import engine
            from app.models import Item

            try:
                item_uuid = uuid.UUID(item_id)
            except ValueError as exc:
                raise ValueError(f"invalid item_id: {item_id}") from exc

            with Session(engine) as db:
                item = db.get(Item, item_uuid)
                if not item:
                    raise ValueError(f"item not found: {item_id}")

                removed = len(item.input_filter_rules or {})
                item.input_filter_rules = {}
                if disable:
                    item.input_filter_enabled = False
                db.add(item)
                db.commit()

            return [
                {
                    "type": "text",
                    "text": (
                        "Cleared terminal output -> Agent input filter rules. "
                        f"removed={removed} input_filter_enabled={not disable}"
                    ),
                }
            ]
        except Exception as e:
            debug_log(f"[LocalMCPServer] clear terminal input filter rules error: {e}")
            return [{"type": "text", "text": f"Error: {e}"}]
    
    def _list_installed_software(self, args: dict) -> list:
        item_id = args.get("item_id", "")
        if not item_id:
            return [{"type": "text", "text": "Error: item_id required"}]

        try:
            from app.services.agent.installed_software import (
                format_installed_software,
                list_installed_software,
            )

            items = list_installed_software(item_id)
            return [
                {
                    "type": "text",
                    "text": "Installed software list:\n" + format_installed_software(items),
                }
            ]
        except Exception as e:
            return [{"type": "text", "text": f"Error: {e}"}]

    def _record_installed_software(self, args: dict) -> list:
        item_id = args.get("item_id", "")
        name = args.get("name", "")
        if not item_id or not name:
            return [{"type": "text", "text": "Error: item_id and name required"}]

        try:
            from app.services.agent.installed_software import record_installed_software

            item = record_installed_software(
                item_id,
                name=name,
                manager=args.get("manager", "unknown"),
                version=args.get("version", ""),
                command=args.get("command", ""),
                notes=args.get("notes", ""),
            )
            manager = item.get("manager", "unknown")
            version = item.get("version", "unknown")
            return [
                {
                    "type": "text",
                    "text": f"Recorded installed software: {item['name']} [{manager}], version={version}",
                }
            ]
        except Exception as e:
            return [{"type": "text", "text": f"Error: {e}"}]

    def _remove_installed_software(self, args: dict) -> list:
        item_id = args.get("item_id", "")
        name = args.get("name", "")
        if not item_id or not name:
            return [{"type": "text", "text": "Error: item_id and name required"}]

        try:
            from app.services.agent.installed_software import remove_installed_software

            result = remove_installed_software(
                item_id,
                name=name,
                manager=args.get("manager", ""),
                reason=args.get("reason", ""),
            )
            count = result.get("count", 0)
            return [
                {
                    "type": "text",
                    "text": f"Removed {count} installed software record(s) for: {name}",
                }
            ]
        except Exception as e:
            return [{"type": "text", "text": f"Error: {e}"}]

    def _save_memory(self, args: dict) -> list:
        content = args.get("content", "")
        memory_type = args.get("memory_type", "fact")
        ttl_days = args.get("ttl_days", 30)
        item_id = args.get("item_id", "")
        
        if not content or not item_id:
            return [{"type": "text", "text": "Error: content and item_id required"}]
        
        try:
            from app.services.agent.memory.vector_store import vector_store
            memory_id = vector_store.add_memory(
                item_id=item_id,
                content=content,
                memory_type=memory_type,
                ttl_days=ttl_days,
                allow_duplicate=True,
            )
            return [{"type": "text", "text": f"✓ 记忆已保存 (ID: {memory_id[:8]}..., 类型: {memory_type}, 有效期: {ttl_days}天)"}]
        except Exception as e:
            return [{"type": "text", "text": f"Error: {e}"}]
    
    def _recall_memory(self, args: dict) -> list:
        query = args.get("query", "")
        n_results = args.get("n_results", 5)
        memory_type = args.get("memory_type")
        item_id = args.get("item_id", "")
        
        if not query or not item_id:
            return [{"type": "text", "text": "Error: query and item_id required"}]
        
        try:
            from app.services.agent.memory.vector_store import vector_store
            results = vector_store.search_memories(
                item_id=item_id,
                query=query,
                n_results=n_results,
                memory_type=memory_type
            )
            
            if not results:
                return [{"type": "text", "text": "未找到相关记忆"}]
            
            lines = [f"=== 找到 {len(results)} 条相关记忆 ==="]
            for i, m in enumerate(results, 1):
                m_type = m.get("metadata", {}).get("memory_type", "unknown")
                distance = m.get("distance", 0)
                lines.append(f"\n[{i}] ({m_type}, 相关度: {1-distance:.2%})")
                lines.append(f"    {m['content']}")
            
            return [{"type": "text", "text": "\n".join(lines)}]
        except Exception as e:
            return [{"type": "text", "text": f"Error: {e}"}]
    
    def _list_memories(self, args: dict) -> list:
        memory_type = args.get("memory_type")
        item_id = args.get("item_id", "")
        
        if not item_id:
            return [{"type": "text", "text": "Error: item_id required"}]
        
        try:
            from app.services.agent.memory.vector_store import vector_store
            memories = vector_store.get_all_memories(item_id, memory_type=memory_type)
            
            if not memories:
                return [{"type": "text", "text": "暂无记忆"}]
            
            lines = [f"=== 共 {len(memories)} 条记忆 ==="]
            for m in memories:
                m_type = m.get("metadata", {}).get("memory_type", "unknown")
                m_id = m.get("id", "")[:8]
                lines.append(f"[{m_id}] ({m_type}) {m['content'][:50]}...")
            
            return [{"type": "text", "text": "\n".join(lines)}]
        except Exception as e:
            return [{"type": "text", "text": f"Error: {e}"}]
    
    def _delete_memory(self, args: dict) -> list:
        memory_id = args.get("memory_id", "")
        item_id = args.get("item_id", "")
        
        if not memory_id or not item_id:
            return [{"type": "text", "text": "Error: memory_id and item_id required"}]
        
        try:
            from app.services.agent.memory.vector_store import vector_store
            success = vector_store.delete_memory(memory_id)
            if success:
                return [{"type": "text", "text": f"✓ 记忆已删除 (ID: {memory_id[:8]}...)"}]
            else:
                return [{"type": "text", "text": f"记忆不存在或删除失败"}]
        except Exception as e:
            return [{"type": "text", "text": f"Error: {e}"}]
    
    def list_tools(self) -> list:
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "inputSchema": t["inputSchema"],
                "skip_memory": t.get("skip_memory", False)
            }
            for t in self._tools.values()
        ]
    
    def call_tool(self, name: str, args: dict) -> list:
        debug_log(f"[LocalMCPServer] call_tool: name={name}, args={args}")
        if name not in self._tools:
            debug_log(f"[LocalMCPServer] Tool '{name}' not found, available: {list(self._tools.keys())}")
            return [{"type": "text", "text": f"Tool '{name}' not found"}]
        try:
            result = self._tools[name]["handler"](args)
            debug_log(f"[LocalMCPServer] Tool '{name}' result: {result}")
            return result
        except Exception as e:
            debug_log(f"[LocalMCPServer] Tool '{name}' error: {e}")
            return [{"type": "text", "text": f"Error: {e}"}]
    
    async def run(self):
        logger.info("[LocalMCPServer] Starting stdio server")
        loop = asyncio.get_running_loop()
        while True:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                request = json.loads(line.strip())
                response = await self._handle_request(request)
                print(json.dumps(response), flush=True)
            except json.JSONDecodeError as e:
                print(json.dumps({"error": f"Invalid JSON: {e}"}), flush=True)
            except Exception as e:
                print(json.dumps({"error": str(e)}), flush=True)
    
    async def _handle_request(self, request: dict) -> dict:
        method = request.get("method", "")
        params = request.get("params", {})
        request_id = request.get("id")
        
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": request_id, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "termman-local", "version": "1.0.0"}
            }}
        
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": self.list_tools()}}
        
        if method == "tools/call":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"content": self.call_tool(params.get("name", ""), params.get("arguments", {}))}}
        
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


local_mcp_server = LocalMCPServer()


def main():
    asyncio.run(local_mcp_server.run())


if __name__ == "__main__":
    main()
