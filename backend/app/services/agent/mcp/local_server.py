import asyncio
import json
import logging
import re
import sys
import threading
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def debug_log(msg: str):
    print(msg, file=sys.stderr, flush=True)


TERMINAL_NOT_CONNECTED_MESSAGE = "终端未连接或未打开，命令没有发送。请先启动或连接终端后再试。"
AUTO_ROUTED_TO_JOB_MARKER = "auto_routed_execute_command_to_run_job"
BACKGROUND_JOB_STARTED_MARKER = "background_job_started"
PENDING_REPLY_SENT_MARKER = "pending_reply_sent"


class LocalMCPServer:
    def __init__(self):
        self._tools: dict[str, dict] = {}
        self._register_builtin_tools()
    
    def _register_builtin_tools(self):
        self.register_tool(
            name="get_terminal_status",
            description=(
                "Read the authoritative live terminal state. The terminal is open only when "
                "the Daemon terminal process is active and Backend is currently joined to the "
                "Item Socket Room as a permanent subscriber. Use this whenever the user asks "
                "whether the terminal is open, connected, online, or usable. Never infer that "
                "state from chat history, logs, Item status, or cached handlers."
            ),
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=self._get_terminal_status,
            skip_memory=True,
        )
        self.register_tool(
            name="execute_command",
            description="在主终端前台执行一条命令或向当前交互式控制台发送输入。适合 shell 短命令、Minecraft/Forge/Paper/Fabric 服务端启动、run.sh/start.sh、REPL、长期服务，以及 MC 控制台里的 op/say/stop 等后续输入。当前台已经是 Minecraft/Java server/REPL 等交互式控制台时，系统不会硬拦截或自动改写 execute_command；所填内容会原样发送，由你根据终端回显判断是否是有效控制台命令。若明确需要在 shell 中执行 ls/pwd/find/cat/java -version 等一次性查询，优先自行选择 run_job。优先一次只发一条命令，不要默认用 &&、||、;、管道或换行拼接多步操作；多步操作应等待上一条终端反馈后再继续。可设置 expected_output/expected_regex 和 timeout_seconds；超时未匹配默认只汇报，不中断进程。",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的一条 shell 命令；默认不要拼接 &&、||、;、管道或换行。"},
                    "expected_output": {"type": "string", "description": "可选。预期在终端输出中出现的文本；超时未出现时默认只汇报并保留进程。"},
                    "expected_regex": {"type": "string", "description": "可选。预期输出正则；比 expected_output 更灵活。"},
                    "timeout_seconds": {"type": "integer", "description": "可选。等待预期输出的秒数，默认 20，范围 1-600。", "default": 20},
                    "auto_interrupt_on_timeout": {"type": "boolean", "description": "可选，默认 false。只有用户明确要求超时停止进程时才设为 true。", "default": False}
                },
                "required": ["command"]
            },
            handler=self._execute_command,
            skip_memory=True
        )
        self.register_tool(
            name="run_job",
            description="Start a non-interactive one-shot shell job in a daemon background process with stdin closed. The main terminal must already be started and connected; run_job is rejected while the main terminal is stopped. Use this for downloads, package installs, builds, tests, archive extraction, and other commands that can finish without later user input; the final result and tail output will be delivered back to the agent after completion. Multiple different background jobs may run at the same time; exact duplicate commands are rejected. For apt/dpkg or other package-manager installs that share global locks, prefer waiting for an existing same-manager install to finish or inspect with list_jobs first. Also use run_job for shell inspection commands such as ls, pwd, local find, cat, head, tail, grep, du, df, and java -version while the main terminal is already occupied by an interactive server console. For file discovery, start from the current working directory with pwd and ls -la, then use find . -maxdepth 2 only if needed; do not scan /, ~, /opt, or /srv unless the user explicitly asks for a wider search. Before using it, decide whether the command needs an interactive foreground console. Do not choose run_job for Minecraft/Forge/Paper/Fabric server startup, run.sh/start.sh server launchers, REPLs, shells, watch/dev servers, or any process that should remain open for later commands such as op/say/stop; choose execute_command in the main terminal for those. Prefer one clear operation per job; avoid very long &&/pipe chains when a later step may need diagnosis.",
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
            name="read_chat_history",
            description=(
                "Read recent TermMan chat/agent/terminal history for the current item. "
                "Use this when the user refers to previous work or context, such as "
                "'刚才', '前面', '之前', '继续', '上一个任务', '你忘了', or asks what was done. "
                "This is short-term evidence, not long-term memory."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {"type": "string", "description": "Current terminal item id."},
                    "limit": {"type": "integer", "description": "Recent messages to return. Default 30, max 100.", "default": 30},
                    "offset": {"type": "integer", "description": "Skip this many newest messages before reading older history. Default 0.", "default": 0},
                    "query": {"type": "string", "description": "Optional case-insensitive substring filter."},
                    "include_summary": {"type": "boolean", "description": "Include the latest session summary when available. Default true.", "default": True},
                },
                "required": ["item_id"],
            },
            handler=self._read_chat_history,
            skip_memory=True,
        )
        self.register_tool(
            name="list_reply_tickets",
            description=(
                "List active recent reply tickets for this item. Use this to check the "
                "authoritative source route for pending/running work so completion is "
                "reported back to the same QQ/server/web source."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {"type": "string", "description": "Current terminal item id."},
                    "limit": {"type": "integer", "description": "Tickets to return. Default 10, max 50.", "default": 10},
                    "include_delivered": {"type": "boolean", "description": "Include already delivered tickets. Default false.", "default": False},
                },
                "required": ["item_id"],
            },
            handler=self._list_reply_tickets,
            skip_memory=True,
        )
        self.register_tool(
            name="read_pending_replies",
            description=(
                "Read the authoritative task queue for the current terminal item. "
                "Each entry contains the requester, task plan, immutable destination, status, "
                "and any external event being awaited."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "Current terminal item id; injected automatically.",
                    }
                },
                "required": [],
            },
            handler=self._read_pending_replies,
            skip_memory=True,
        )
        self.register_tool(
            name="write_pending_reply",
            description=(
                "Create or update the task-queue entry linked to the current message source. "
                "Use this only for delegated, multi-step, asynchronous, background-job, or "
                "wait-for-reply work where the main objective or return destination could be "
                "forgotten between turns. Do not create an entry for ordinary chat or an "
                "immediate one-step reply. The destination is copied from the authoritative "
                "reply ticket and cannot be changed by tool arguments."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "Current terminal item id; injected automatically.",
                    },
                    "entry_id": {
                        "type": "string",
                        "description": "Existing pending reply id; defaults to the current reply ticket.",
                    },
                    "requester": {"type": "string"},
                    "request_summary": {"type": "string"},
                    "task_plan": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ordered task steps or the current plan.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "working", "waiting", "ready", "failed"],
                        "default": "working",
                    },
                    "awaiting_kind": {
                        "type": "string",
                        "description": "Optional awaited event type, such as minecraft_player or background_job.",
                    },
                    "awaiting_key": {
                        "type": "string",
                        "description": "Optional exact awaited target, such as yueyinghanbo or a job id.",
                    },
                },
                "required": [],
            },
            handler=self._write_pending_reply,
            skip_memory=True,
        )
        self.register_tool(
            name="delete_pending_reply",
            description=(
                "Delete one task-queue entry without sending. Use only when the user cancels "
                "the task or the task is confirmed obsolete."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "Current terminal item id; injected automatically.",
                    },
                    "entry_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["entry_id"],
            },
            handler=self._delete_pending_reply,
            skip_memory=True,
        )
        self.register_tool(
            name="send_pending_reply",
            description=(
                "Send the final report through the immutable destination stored in one pending "
                "reply entry. This is the only normal completion path: it sends first and deletes "
                "the queue entry only after confirmed delivery. On delivery failure the entry is "
                "kept with failed status. Do not restate the same report after success."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "Current terminal item id; injected automatically.",
                    },
                    "entry_id": {"type": "string"},
                    "content": {"type": "string", "description": "Concise final report."},
                },
                "required": ["entry_id", "content"],
            },
            handler=self._send_pending_reply,
            skip_memory=True,
        )
        self.register_tool(
            name="get_task_workflow",
            description=(
                "Read the authoritative task workflow linked to the current reply ticket. "
                "Use it whenever a multi-step task has changed method, hit an error, resumed "
                "after a background job, or you need to recover the main objective."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "Current terminal item id.",
                    }
                },
                "required": ["item_id"],
            },
            handler=self._get_task_workflow,
            skip_memory=True,
        )
        self.register_tool(
            name="update_task_workflow",
            description=(
                "Update the authoritative task state after observing real evidence. "
                "The main objective cannot be replaced. Complete the current step only "
                "after evidence, insert a recovery step when changing source/method, and "
                "mark blocked only when user or external input is genuinely required. "
                "Action=cancel cancels the whole objective and is allowed only when the user "
                "explicitly abandons it; use cancel_job to stop an obsolete execution while "
                "keeping the main objective active. Updating workflow state is not execution, "
                "so call the concrete terminal/job tool immediately afterward."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "Current terminal item id.",
                    },
                    "action": {
                        "type": "string",
                        "enum": [
                            "record_progress",
                            "complete_current_step",
                            "set_current_step",
                            "insert_recovery_step",
                            "mark_ready_to_report",
                            "mark_blocked",
                            "resume",
                            "cancel",
                        ],
                    },
                    "note": {
                        "type": "string",
                        "description": "Observed evidence, progress, or blocker reason.",
                    },
                    "step_index": {
                        "type": "integer",
                        "description": "Zero-based step index for set_current_step.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Recovery step title for insert_recovery_step.",
                    },
                },
                "required": ["item_id", "action"],
            },
            handler=self._update_task_workflow,
            skip_memory=True,
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
            name="list_terminal_filter_rules",
            description="List all terminal filter rules for the current item, including terminal output -> Agent input filters and Agent -> terminal command output filters. Use this before adding or changing filters when the user asks what filtering rules exist.",
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {"type": "string", "description": "Current terminal item id."},
                },
                "required": ["item_id"]
            },
            handler=self._list_terminal_filter_rules,
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
            name="list_scheduled_tasks",
            description=(
                "Read all scheduled tasks for the current terminal item, including ids, "
                "instructions, enabled state, next run time, and last result."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "Current terminal item id; injected automatically.",
                    }
                },
                "required": [],
            },
            handler=self._list_scheduled_tasks,
            skip_memory=True,
        )
        self.register_tool(
            name="write_scheduled_task",
            description=(
                "Create or update one scheduled task for the current terminal item. "
                "Pass task_id to update an existing task. Supported schedules are once, "
                "interval, and daily."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "Current terminal item id; injected automatically.",
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Existing task id when updating; omit when creating.",
                    },
                    "name": {"type": "string", "description": "Short task name."},
                    "instruction": {
                        "type": "string",
                        "description": "Instruction sent to the Agent when the task runs.",
                    },
                    "schedule_type": {
                        "type": "string",
                        "enum": ["once", "interval", "daily"],
                    },
                    "run_at": {
                        "type": "string",
                        "description": "ISO datetime for a once task.",
                    },
                    "interval_seconds": {
                        "type": "integer",
                        "description": "Interval in seconds for an interval task; minimum 10.",
                    },
                    "time_of_day": {
                        "type": "string",
                        "description": "Local HH:MM time for a daily task.",
                    },
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone, default Asia/Shanghai.",
                        "default": "Asia/Shanghai",
                    },
                    "enabled": {
                        "type": "boolean",
                        "description": "Whether the task should run.",
                        "default": True,
                    },
                },
                "required": ["name", "instruction", "schedule_type"],
            },
            handler=self._write_scheduled_task,
            skip_memory=True,
        )
        self.register_tool(
            name="delete_scheduled_task",
            description=(
                "Delete one scheduled task by id. During scheduled execution, use this only "
                "after deciding the task is obsolete, invalid, unsafe, or permanently unable "
                "to succeed. Do not delete it for a transient failure."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "Current terminal item id; injected automatically.",
                    },
                    "task_id": {"type": "string", "description": "Scheduled task id."},
                    "reason": {
                        "type": "string",
                        "description": "Why the Agent decided to delete the task.",
                    },
                },
                "required": ["task_id"],
            },
            handler=self._delete_scheduled_task,
            skip_memory=True,
        )
        self.register_tool(
            name="save_memory",
            description="保存稳定、可复用、已验证的重要信息到长期记忆中。执行中的任务状态只放任务队列。不要保存原生日志、命令回显、等待态消息或敏感信息。",
            input_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "要保存的记忆内容"},
                    "memory_type": {"type": "string", "enum": ["fact", "preference", "error", "context"], "description": "记忆类型: fact(事实), preference(偏好), error(错误), context(上下文)"},
                    "ttl_days": {"type": "integer", "description": "事实或上下文的过期天数；偏好和错误永久保存"}
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
                    "memory_type": {"type": "string", "enum": ["fact", "preference", "error", "context"], "description": "可选：限定记忆类型"}
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
                    "memory_type": {"type": "string", "enum": ["fact", "preference", "error", "context"], "description": "可选：限定记忆类型"}
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

    def _get_terminal_status(self, args: dict) -> list:
        item_id = str(args.get("item_id") or "").strip()
        if not item_id:
            return [{"type": "text", "text": "Error: item_id required"}]
        try:
            from app.services.terminal_runtime_state import get_terminal_runtime_state

            state = get_terminal_runtime_state(item_id)
            return [
                {"type": "text", "text": state.user_message()},
                {
                    "type": "metadata",
                    "terminal_active": state.active,
                    "daemon_connected": state.daemon_connected,
                    "process_status": state.process_status,
                    "backend_room_connected": state.backend_room_connected,
                    "permanent_subscriber_count": state.permanent_subscriber_count,
                    "reason": state.reason,
                },
            ]
        except Exception as exc:
            debug_log(f"[LocalMCPServer] get_terminal_status error: {exc}")
            return [{"type": "text", "text": f"Error: {exc}"}]
    
    def _restore_existing_terminal_input(self, item_id: str) -> bool:
        try:
            import uuid

            from sqlmodel import Session

            from app.core.db import engine
            from app.models import Item
            from app.services import (
                DaemonConfig,
                connection_manager,
                socket_pool_facade,
            )
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

            terminal_service = TerminalService(connection_manager, socket_pool_facade)
            restored = terminal_service.restore_running_terminal(
                item_uuid=str(item_id),
                owner_uuid=owner_uuid,
                daemon_config=daemon_config,
            )
            debug_log(f"[LocalMCPServer] terminal input restore result: item={item_id}, restored={restored}")
            return bool(restored)
        except Exception as exc:
            debug_log(f"[LocalMCPServer] terminal input restore error for item={item_id}: {exc}")
            return False

    def _ensure_terminal_input_handler(self, item_id: str) -> bool:
        from app.services.socket_pool.input_center import input_center
        from app.services.terminal_runtime_state import get_terminal_runtime_state

        state = get_terminal_runtime_state(item_id)
        if state.active and input_center.has_handler(item_id):
            return True

        # A live PTY can survive a Backend restart. Rejoin its Item Room before
        # accepting input, then verify the Room state again instead of trusting
        # the newly registered local handler.
        if state.daemon_connected and state.terminal_process_active:
            self._restore_existing_terminal_input(item_id)
            state = get_terminal_runtime_state(item_id)
            if state.active and input_center.has_handler(item_id):
                return True

        # Cached handlers are not connection evidence. Remove them so a later
        # command cannot be reported as sent through a dead socket callback.
        if input_center.has_handler(item_id):
            input_center.unregister_all_by_item(item_id)
        return False

    def _terminal_unavailable_message(self, item_id: str) -> str:
        try:
            from app.services.terminal_runtime_state import get_terminal_runtime_state

            state = get_terminal_runtime_state(item_id)
            if state.active:
                return (
                    "终端已启动并已连接，但 Backend 输入处理器不可用，"
                    "自动恢复失败。命令没有发送。"
                )
            return f"{state.user_message()}命令没有发送。"
        except Exception:
            return TERMINAL_NOT_CONNECTED_MESSAGE

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

    def _clip_history_text(self, value: Any, limit: int = 900) -> str:
        text = str(value or "").replace("\r\n", "\n").strip()
        if len(text) <= limit:
            return text
        head = max(limit // 2 - 20, 120)
        tail = max(limit - head - 40, 120)
        return f"{text[:head].rstrip()}\n...<truncated>...\n{text[-tail:].lstrip()}"

    def _format_chat_history_entry(self, index: int, message: dict[str, Any]) -> str:
        timestamp = str(message.get("timestamp") or "").strip() or "unknown-time"
        message_type = str(message.get("type") or "message").strip()
        role = str(message.get("role") or "").strip()
        detail_parts: list[str] = []
        if role:
            detail_parts.append(f"role={role}")
        for key in ("tool_name", "source_type", "source_label", "status"):
            value = str(message.get(key) or "").strip()
            if value:
                detail_parts.append(f"{key}={self._clip_history_text(value, 120)}")
        details = f" ({', '.join(detail_parts)})" if detail_parts else ""
        content = self._clip_history_text(message.get("content"), 1000) or "(empty)"
        return f"[{index}] {timestamp} {message_type}{details}\n{content}"

    def _read_chat_history(self, args: dict) -> list:
        item_id = str(args.get("item_id") or "").strip()
        if not item_id:
            return [{"type": "text", "text": "Error: item_id required"}]

        limit = self._coerce_job_int(args.get("limit"), 30, 1, 100)
        offset = self._coerce_job_int(args.get("offset"), 0, 0, 10000)
        query = str(args.get("query") or "").strip().lower()
        include_summary = bool(args.get("include_summary", True))

        try:
            from app.services.agent.history.chat import (
                SESSION_SUMMARY_TYPE,
                get_chat_messages,
                get_latest_session_summary,
            )

            messages = get_chat_messages(item_id)
            summary = get_latest_session_summary(item_id) if include_summary else None
            history_messages = [
                message
                for message in messages
                if isinstance(message, dict)
                and message.get("type") != SESSION_SUMMARY_TYPE
            ]
            if query:
                history_messages = [
                    message
                    for message in history_messages
                    if query in str(message.get("content") or "").lower()
                    or query in str(message.get("type") or "").lower()
                    or query in str(message.get("tool_name") or "").lower()
                ]

            total = len(history_messages)
            effective_offset = min(offset, total)
            end = max(total - effective_offset, 0)
            start = max(end - limit, 0)
            page = history_messages[start:end]

            lines = [
                "TermMan item chat history:",
                f"item_id={item_id}",
                f"total_matching_messages={total}",
                f"limit={limit}",
                f"offset={effective_offset}",
                "order=oldest_to_newest",
            ]
            if query:
                lines.append(f"query={query}")
            if summary and summary.get("content"):
                lines.append("")
                lines.append("Latest session summary:")
                lines.append(self._clip_history_text(summary.get("content"), 1200))
            if page:
                lines.append("")
                lines.append("Messages:")
                for display_index, message in enumerate(page, start=start + 1):
                    lines.append(self._format_chat_history_entry(display_index, message))
            else:
                lines.append("")
                lines.append("No matching chat history messages.")
            lines.append("")
            lines.append(
                "Use this as short-term evidence for previous work; do not quote raw history unless the user asks."
            )
            return [{"type": "text", "text": "\n".join(lines)}]
        except Exception as e:
            debug_log(f"[LocalMCPServer] read_chat_history error: {e}")
            return [{"type": "text", "text": f"Error: {e}"}]

    def _get_task_workflow(self, args: dict) -> list:
        item_id = str(args.get("item_id") or "").strip()
        reply_ticket_id = str(args.get("_reply_ticket_id") or "").strip()
        if not item_id:
            return [{"type": "text", "text": "Error: item_id required"}]
        try:
            from app.services.agent.task_workflow import task_workflow_manager

            workflow = task_workflow_manager.snapshot_for_ticket(reply_ticket_id)
            if workflow is None:
                active = [
                    candidate
                    for candidate in task_workflow_manager.snapshot(item_id)
                    if candidate.get("status")
                    not in {"completed", "cancelled"}
                ]
                workflow = active[0] if len(active) == 1 else None
            if workflow is None:
                return [
                    {
                        "type": "text",
                        "text": "No authoritative task workflow is linked to this turn.",
                    }
                ]
            return [
                {
                    "type": "text",
                    "text": task_workflow_manager.build_prompt_context(
                        item_id=item_id,
                        reply_ticket_id=reply_ticket_id,
                    ),
                }
            ]
        except Exception as exc:
            debug_log(f"[LocalMCPServer] get_task_workflow error: {exc}")
            return [{"type": "text", "text": f"Error: {exc}"}]

    def _update_task_workflow(self, args: dict) -> list:
        item_id = str(args.get("item_id") or "").strip()
        reply_ticket_id = str(args.get("_reply_ticket_id") or "").strip()
        if not item_id:
            return [{"type": "text", "text": "Error: item_id required"}]
        if not reply_ticket_id:
            return [
                {
                    "type": "text",
                    "text": "Error: no reply ticket is linked to this task turn",
                }
            ]
        try:
            from app.services.agent.task_workflow import task_workflow_manager

            raw_step_index = args.get("step_index")
            step_index = None
            if raw_step_index is not None:
                step_index = int(raw_step_index)
            success, detail = task_workflow_manager.update(
                reply_ticket_id,
                action=str(args.get("action") or ""),
                note=str(args.get("note") or ""),
                step_index=step_index,
                title=str(args.get("title") or ""),
            )
            if not success:
                return [{"type": "text", "text": f"Error: {detail}"}]
            context = task_workflow_manager.build_prompt_context(
                item_id=item_id,
                reply_ticket_id=reply_ticket_id,
            )
            return [
                {
                    "type": "text",
                    "text": (
                        f"Task workflow updated: {detail}\n{context}\n"
                        "Workflow bookkeeping is not task progress by itself. If a safe "
                        "execution action is available, call that tool now instead of "
                        "describing the next step."
                    ),
                }
            ]
        except Exception as exc:
            debug_log(f"[LocalMCPServer] update_task_workflow error: {exc}")
            return [{"type": "text", "text": f"Error: {exc}"}]

    def _list_reply_tickets(self, args: dict) -> list:
        item_id = str(args.get("item_id") or "").strip()
        if not item_id:
            return [{"type": "text", "text": "Error: item_id required"}]

        limit = self._coerce_job_int(args.get("limit"), 10, 1, 50)
        include_delivered = bool(args.get("include_delivered", False))

        try:
            from app.services.agent.reply_ticket import reply_ticket_manager

            tickets = reply_ticket_manager.snapshot(item_id)
            if not include_delivered:
                tickets = [
                    ticket
                    for ticket in tickets
                    if str(ticket.get("status") or "") != "delivered"
                ]
            tickets = tickets[:limit]
            if not tickets:
                return [
                    {
                        "type": "text",
                        "text": "No active reply tickets for this item.",
                    }
                ]

            lines = [
                "Reply tickets for current item:",
                "Use these routes as authoritative return targets for pending/running work.",
            ]
            for ticket in tickets:
                ticket_id = str(ticket.get("ticket_id") or "")
                command = self._clip_history_text(ticket.get("command"), 180)
                task_request_id = str(ticket.get("task_request_id") or "").strip()
                parts = [
                    f"ticket_id={ticket_id[:12]}",
                    f"source_type={ticket.get('source_type', '')}",
                    f"source_label={ticket.get('source_label', '')}",
                    f"status={ticket.get('status', '')}",
                    f"updated_at={ticket.get('updated_at', '')}",
                ]
                if task_request_id:
                    parts.append(f"task_request_id={task_request_id}")
                lines.append(f"- {'; '.join(parts)}")
                if command:
                    lines.append(f"  command={command}")
                delivery_error = str(ticket.get("delivery_error") or "").strip()
                if delivery_error:
                    lines.append(f"  delivery_error={self._clip_history_text(delivery_error, 300)}")

            return [{"type": "text", "text": "\n".join(lines)}]
        except Exception as e:
            debug_log(f"[LocalMCPServer] list_reply_tickets error: {e}")
            return [{"type": "text", "text": f"Error: {e}"}]

    def _read_pending_replies(self, args: dict) -> list:
        item_id = str(args.get("item_id") or "").strip()
        if not item_id:
            return [{"type": "text", "text": "Error: item_id required"}]
        try:
            from app.services.agent.reply_ticket import reply_ticket_manager

            entries = reply_ticket_manager.list_pending_replies(item_id)
            if not entries:
                return [{"type": "text", "text": "Task queue is empty."}]
            lines = [
                "Authoritative task queue:",
                "Send with mcp_local_send_pending_reply; successful send removes the entry.",
            ]
            for entry in entries:
                lines.append(
                    f"- id={entry['id']}; requester={entry['requester']}; "
                    f"destination={entry['destination_label']}; status={entry['status']}"
                )
                lines.append(f"  request={entry['request_summary']}")
                if entry.get("task_plan"):
                    lines.append("  plan=" + " -> ".join(entry["task_plan"]))
                if entry.get("awaiting_kind") or entry.get("awaiting_key"):
                    lines.append(
                        f"  awaiting={entry.get('awaiting_kind') or 'event'}:"
                        f"{entry.get('awaiting_key') or 'unspecified'}"
                    )
                if entry.get("last_error"):
                    lines.append(f"  last_error={entry['last_error']}")
            return [{"type": "text", "text": "\n".join(lines)}]
        except Exception as exc:
            return [{"type": "text", "text": f"Error: {exc}"}]

    def _write_pending_reply(self, args: dict) -> list:
        item_id = str(args.get("item_id") or "").strip()
        entry_id = str(
            args.get("entry_id") or args.get("_reply_ticket_id") or ""
        ).strip()
        if not item_id or not entry_id:
            return [
                {
                    "type": "text",
                    "text": "Error: current reply ticket or entry_id is required",
                }
            ]
        raw_plan = args.get("task_plan")
        if isinstance(raw_plan, str):
            task_plan = [raw_plan]
        elif isinstance(raw_plan, list):
            task_plan = [str(step) for step in raw_plan]
        else:
            task_plan = None
        try:
            from app.services.agent.reply_ticket import reply_ticket_manager
            from app.services.agent.task_workflow import task_workflow_manager

            ticket = reply_ticket_manager.get(entry_id)
            if not ticket or ticket.item_id != item_id:
                return [{"type": "text", "text": "Error: pending reply source not found"}]
            status = str(args.get("status") or "working")
            entry = reply_ticket_manager.upsert_pending_reply(
                entry_id,
                requester=str(args.get("requester") or ""),
                request_summary=str(args.get("request_summary") or ""),
                task_plan=task_plan,
                status=status,
                awaiting_kind=str(args.get("awaiting_kind") or ""),
                awaiting_key=str(args.get("awaiting_key") or ""),
            )
            if status == "ready":
                task_workflow_manager.update(
                    entry_id,
                    action="mark_ready_to_report",
                    note="Pending reply is ready for final delivery.",
                )
            return [
                {
                    "type": "text",
                    "text": (
                        f"Pending reply saved: id={entry['id']} requester={entry['requester']} "
                        f"destination={entry['destination_label']} status={entry['status']}"
                    ),
                }
            ]
        except Exception as exc:
            return [{"type": "text", "text": f"Error: {exc}"}]

    def _delete_pending_reply(self, args: dict) -> list:
        item_id = str(args.get("item_id") or "").strip()
        entry_id = str(args.get("entry_id") or "").strip()
        if not item_id or not entry_id:
            return [{"type": "text", "text": "Error: item_id and entry_id required"}]
        try:
            from app.services.agent.reply_ticket import reply_ticket_manager

            ticket = reply_ticket_manager.get(entry_id)
            if not ticket or ticket.item_id != item_id:
                return [{"type": "text", "text": "Error: pending reply not found"}]
            deleted = reply_ticket_manager.delete_pending_reply(
                entry_id,
                reason=str(args.get("reason") or "Agent deleted pending reply"),
            )
            if not deleted:
                return [{"type": "text", "text": "Error: pending reply not found"}]
            return [{"type": "text", "text": f"Pending reply deleted: id={entry_id}"}]
        except Exception as exc:
            return [{"type": "text", "text": f"Error: {exc}"}]

    def _send_pending_reply(self, args: dict) -> list:
        item_id = str(args.get("item_id") or "").strip()
        entry_id = str(args.get("entry_id") or "").strip()
        content = str(args.get("content") or "").strip()
        if not item_id or not entry_id or not content:
            return [
                {
                    "type": "text",
                    "text": "Error: item_id, entry_id, and content required",
                }
            ]
        try:
            from app.services.agent.reply_ticket import reply_ticket_manager

            ticket = reply_ticket_manager.get(entry_id)
            if not ticket or ticket.item_id != item_id:
                return [{"type": "text", "text": "Error: pending reply not found"}]
            delivered, detail = reply_ticket_manager.send_pending_reply(
                entry_id,
                content,
            )
            if not delivered:
                return [{"type": "text", "text": f"Error: {detail}"}]
            return [
                {
                    "type": "text",
                    "text": f"Pending reply delivered to {detail} and removed from the queue.",
                },
                {
                    "type": "metadata",
                    PENDING_REPLY_SENT_MARKER: True,
                    "entry_id": entry_id,
                    "destination": detail,
                },
            ]
        except Exception as exc:
            return [{"type": "text", "text": f"Error: {exc}"}]

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

        if not self._ensure_terminal_input_handler(str(item_id)):
            debug_log(
                f"[LocalMCPServer] run_job blocked because main terminal is inactive: "
                f"item={item_id}, command={command}"
            )
            return [{"type": "text", "text": self._terminal_unavailable_message(str(item_id))}]

        timeout_seconds = self._coerce_job_int(args.get("timeout_seconds"), 600, 1, 3600)
        tail_lines = self._coerce_job_int(args.get("tail_lines"), 80, 1, 300)
        wait_for_completion = bool(args.get("wait_for_completion"))
        robot_job_context = self._robot_job_context_from_args(args)
        reply_ticket_id = str(args.get("_reply_ticket_id") or "").strip()
        if reply_ticket_id:
            try:
                from app.services.agent.reply_ticket import reply_ticket_manager

                if reply_ticket_manager.get(reply_ticket_id) is None:
                    return [
                        {
                            "type": "text",
                            "text": (
                                "Task request was superseded by a newer message; "
                                "the background job was not started."
                            ),
                        }
                    ]
                reply_ticket_manager.mark_command(reply_ticket_id, command)
            except Exception:
                pass
        debug_log(
            f"[LocalMCPServer] _run_job: item={item_id}, timeout={timeout_seconds}, tail_lines={tail_lines}, wait={wait_for_completion}, command={command}"
        )
        agent_session = None
        try:
            from app.services.agent.session import (
                RUN_JOB_TOOL_NAME,
                agent_session_manager,
            )

            agent_session = agent_session_manager.get_session(str(item_id))
            if agent_session:
                guard_error = agent_session.validate_terminal_tool_input(
                    RUN_JOB_TOOL_NAME,
                    {
                        "item_id": str(item_id),
                        "command": command,
                        "timeout_seconds": timeout_seconds,
                        "_reply_ticket_id": reply_ticket_id,
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
                        "_reply_ticket_id": reply_ticket_id,
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

            if reply_ticket_id:
                try:
                    from app.services.agent.reply_ticket import reply_ticket_manager

                    reply_ticket_manager.upsert_pending_reply(
                        reply_ticket_id,
                        status="working",
                    )
                except Exception as exc:
                    debug_log(
                        f"[LocalMCPServer] failed to register background job pending reply: "
                        f"ticket={reply_ticket_id}, error={exc}"
                    )

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
                        "后台任务已启动，会在独立任务里执行，完成后把最终结果自动送回 Agent。"
                        "不同后台任务可以并行启动；不要重复启动完全相同的命令。"
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
            if reply_ticket_id:
                try:
                    from app.services.agent.scheduled_tasks import (
                        record_scheduled_ticket_result,
                    )

                    record_scheduled_ticket_result(
                        reply_ticket_id,
                        success=bool(result.get("success")),
                        error="" if result.get("success") else self._format_job_result(result),
                    )
                except Exception as exc:
                    debug_log(
                        f"[LocalMCPServer] failed to update scheduled task result: "
                        f"ticket={reply_ticket_id}, error={exc}"
                    )
            if reply_ticket_id:
                try:
                    from app.services.agent.task_workflow import task_workflow_manager

                    task_workflow_manager.record_job_result(
                        reply_ticket_id,
                        command=command,
                        success=bool(result.get("success")),
                        result_summary=self._format_job_result(result),
                        daemon_job_id=str(result.get("job_id") or ""),
                        exit_code=result.get("exit_code"),
                    )
                except Exception as exc:
                    debug_log(
                        f"[LocalMCPServer] failed to update task workflow from job: ticket={reply_ticket_id}, error={exc}"
                    )
            queued_to_robot = False
            delivered_by_ticket = False
            if robot_job_context:
                queued_to_robot = self._deliver_background_job_to_robot(
                    item_id=item_id,
                    command=command,
                    result=result,
                    robot_job_context=robot_job_context,
                    pending_reply_id=pending_robot_reply_id or "",
                    reply_ticket_id=reply_ticket_id,
                )
            if queued_to_robot:
                feedback = (
                    f"{feedback}\n"
                    "[Reply ticket notification handled for the source that started this job.]"
                )

            if agent_session:
                agent_session.clear_terminal_job(command)
                if queued_to_robot:
                    return
                try:
                    from app.services.agent.session import InputMessage, InputType

                    agent_session.process_input(
                        InputMessage(
                            input_type=InputType.TERMINAL,
                            content=feedback,
                            raw_content=feedback,
                            query="background job completed",
                            reply_ticket_id=reply_ticket_id,
                        )
                    )
                    return
                except Exception as exc:
                    debug_log(
                        f"[LocalMCPServer] failed to deliver background job feedback: item={item_id}, error={exc}"
                    )

            if not queued_to_robot:
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
        reply_ticket_id: str = "",
    ) -> bool:
        if not robot_job_context:
            return False
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
                reply_ticket_id=reply_ticket_id,
            )
            if not queued:
                debug_log(
                    f"[LocalMCPServer] robot background job result not queued: item={item_id}, command={command}"
                )
            return bool(queued)
        except Exception as exc:
            debug_log(
                f"[LocalMCPServer] failed to queue robot background job result: item={item_id}, error={exc}"
            )
            if pending_reply_id:
                self._clear_background_job_robot_reply(
                    robot_job_context=robot_job_context,
                    pending_reply_id=pending_reply_id,
                )
            return False

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
            ticket = reply_ticket_manager.get(reply_ticket_id)
            if ticket and ticket.pending_reply_active:
                delivered, _ = reply_ticket_manager.send_pending_reply(
                    reply_ticket_id,
                    message,
                )
                return delivered
            return reply_ticket_manager.deliver(reply_ticket_id, message)
        except Exception as exc:
            debug_log(
                f"[LocalMCPServer] failed to deliver background job via reply ticket: ticket={reply_ticket_id}, error={exc}"
            )
            return False

    def _format_background_job_reply_ticket_message(self, command: str, result: dict) -> str:
        output_tail = str(result.get("output_tail") or "").strip()
        if len(output_tail) > 1200:
            output_tail = output_tail[-1200:]
        if result.get("success"):
            duration = result.get("duration_seconds")
            duration_text = f"，耗时 {duration}s" if duration not in (None, "") else ""
            message = f"后台任务已完成，退出码 {result.get('exit_code', 0)}{duration_text}。"
            if output_tail:
                return f"{message}\n结果：\n{output_tail}"
            return f"{message}\n没有输出内容。"
        error = str(result.get("error") or "daemon job failed").strip()
        if len(error) > 160:
            error = f"{error[:157]}..."
        message = f"后台任务失败。原因：{error}"
        if output_tail:
            return f"{message}\n输出：\n{output_tail}"
        return message

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
            has_handler = self._ensure_terminal_input_handler(str(item_id))
            debug_log(f"[LocalMCPServer] has_handler={has_handler}")
            if not has_handler:
                return [{"type": "text", "text": self._terminal_unavailable_message(str(item_id))}]

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
                job_started = any(
                    isinstance(item, dict)
                    and bool(item.get(BACKGROUND_JOB_STARTED_MARKER))
                    for item in result
                )
                if not job_started:
                    return result
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
                        else self._terminal_unavailable_message(str(item_id))
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
                agent_session_manager,
                classify_terminal_input_mode,
            )

            agent_session = (
                agent_session_manager.get_session(str(item_id)) if item_id else None
            )
            if agent_session:
                if agent_session.has_interactive_terminal_context():
                    return False
                if agent_session.should_route_execute_command_to_background_job(
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
                return [{"type": "text", "text": self._terminal_unavailable_message(str(item_id))}]
            
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

    def _format_terminal_filter_section(
        self,
        title: str,
        *,
        enabled: bool,
        rules: dict,
    ) -> list[str]:
        if not rules:
            return [f"{title} enabled={enabled}; no rules."]

        lines = [f"{title} enabled={enabled}; rules={len(rules)}"]
        for rule_name, rule in rules.items():
            if not isinstance(rule, dict):
                lines.append(f"- {rule_name}: invalid rule payload")
                continue
            patterns = [
                pattern
                for pattern in rule.get("regex_patterns", [])
                if isinstance(pattern, str)
            ]
            action_type = rule.get("action_type", "ignore")
            reason = str(rule.get("reason") or "").strip()
            action = rule.get("action") if isinstance(rule.get("action"), dict) else {}
            replace_rules = action.get("replace_rules") if isinstance(action, dict) else None
            details = [f"action={action_type}", f"patterns={len(patterns)}"]
            if isinstance(replace_rules, dict):
                details.append(f"replace_rules={len(replace_rules)}")
            if reason:
                details.append(f"reason={reason}")
            lines.append(f"- {rule_name}: {', '.join(details)}")
            for pattern in patterns[:5]:
                lines.append(f"  - {pattern}")
            if len(patterns) > 5:
                lines.append(f"  - ... {len(patterns) - 5} more")
        return lines

    def _list_terminal_filter_rules(self, args: dict) -> list:
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
                input_enabled = bool(item.input_filter_enabled)
                input_rules = dict(item.input_filter_rules or {})
                output_enabled = bool(item.output_filter_enabled)
                output_rules = dict(item.output_filter_rules or {})

            lines = ["Terminal filter rules for current item:"]
            lines.extend(
                self._format_terminal_filter_section(
                    "Input filter (terminal output -> Agent)",
                    enabled=input_enabled,
                    rules=input_rules,
                )
            )
            lines.append("")
            lines.extend(
                self._format_terminal_filter_section(
                    "Output filter (Agent command -> terminal)",
                    enabled=output_enabled,
                    rules=output_rules,
                )
            )
            return [{"type": "text", "text": "\n".join(lines)}]
        except Exception as e:
            debug_log(f"[LocalMCPServer] list terminal filter rules error: {e}")
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

    def _list_scheduled_tasks(self, args: dict) -> list:
        item_id = str(args.get("item_id") or "").strip()
        if not item_id:
            return [{"type": "text", "text": "Error: item_id required"}]
        try:
            from app.services.agent.scheduled_tasks import (
                format_scheduled_tasks,
                list_scheduled_tasks,
            )

            tasks = list_scheduled_tasks(item_id)
            return [
                {
                    "type": "text",
                    "text": "Scheduled tasks:\n" + format_scheduled_tasks(tasks),
                }
            ]
        except Exception as e:
            return [{"type": "text", "text": f"Error: {e}"}]

    def _write_scheduled_task(self, args: dict) -> list:
        item_id = str(args.get("item_id") or "").strip()
        if not item_id:
            return [{"type": "text", "text": "Error: item_id required"}]
        try:
            from app.services.agent.scheduled_tasks import write_scheduled_task

            task = write_scheduled_task(
                item_id,
                task_id=str(args.get("task_id") or ""),
                name=str(args.get("name") or ""),
                instruction=str(args.get("instruction") or ""),
                schedule_type=str(args.get("schedule_type") or ""),
                run_at=str(args.get("run_at") or ""),
                interval_seconds=int(args.get("interval_seconds") or 0),
                time_of_day=str(args.get("time_of_day") or ""),
                timezone_name=str(args.get("timezone") or "Asia/Shanghai"),
                enabled=bool(args.get("enabled", True)),
            )
            return [
                {
                    "type": "text",
                    "text": (
                        f"Scheduled task saved: id={task['id']} name={task['name']!r} "
                        f"enabled={task['enabled']} next_run_at={task.get('next_run_at') or 'none'}"
                    ),
                }
            ]
        except KeyError as e:
            return [{"type": "text", "text": f"Error: {e.args[0]}"}]
        except Exception as e:
            return [{"type": "text", "text": f"Error: {e}"}]

    def _delete_scheduled_task(self, args: dict) -> list:
        item_id = str(args.get("item_id") or "").strip()
        task_id = str(args.get("task_id") or "").strip()
        if not item_id or not task_id:
            return [{"type": "text", "text": "Error: item_id and task_id required"}]
        try:
            from app.services.agent.scheduled_tasks import delete_scheduled_task

            result = delete_scheduled_task(
                item_id,
                task_id=task_id,
                reason=str(args.get("reason") or "Agent decision"),
            )
            if not result.get("count"):
                return [{"type": "text", "text": "Error: scheduled task not found"}]
            return [
                {
                    "type": "text",
                    "text": f"Scheduled task deleted: id={task_id}",
                }
            ]
        except Exception as e:
            return [{"type": "text", "text": f"Error: {e}"}]

    def _save_memory(self, args: dict) -> list:
        content = args.get("content", "")
        memory_type = str(args.get("memory_type", "fact") or "fact")
        item_id = args.get("item_id", "")
        
        if not content or not item_id:
            return [{"type": "text", "text": "Error: content and item_id required"}]
        if memory_type not in {"fact", "preference", "error", "context"}:
            return [{"type": "text", "text": f"Error: invalid memory_type: {memory_type}"}]
        
        try:
            from app.services.agent.memory.vector_store import vector_store
            from app.services.agent.prompts import policy as memory_policy

            default_ttl_days = memory_policy.resolve_memory_ttl_days(str(memory_type))
            raw_ttl_days = args.get("ttl_days")
            if default_ttl_days is None:
                ttl_days = None
            else:
                ttl_days = default_ttl_days if raw_ttl_days in (None, "") else int(raw_ttl_days)
                ttl_days = max(1, min(3650, ttl_days))

            metadata: dict[str, Any] = {
                "type": "agent_saved",
                "source": "local_agent_saved",
                "verified": True,
                "content_hash": memory_policy._build_content_hash(str(content)),
                "updated_at": datetime.now().isoformat(),
            }
            memory_key = memory_policy.infer_memory_key(str(content), str(memory_type))
            if memory_key:
                metadata["memory_key"] = memory_key
            if memory_type == "error":
                metadata["status"] = "active"

            memory_id = vector_store.add_memory(
                item_id=item_id,
                content=content,
                memory_type=memory_type,
                metadata=metadata,
                ttl_days=ttl_days,
                allow_duplicate=True,
            )
            if not memory_id:
                return [{"type": "text", "text": "Memory was not saved."}]
            lifetime = "永久" if ttl_days is None else f"{ttl_days}天"
            return [{"type": "text", "text": f"✓ 记忆已保存 (ID: {memory_id[:8]}..., 类型: {memory_type}, 有效期: {lifetime})"}]
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
            results = [
                memory
                for memory in results
                if str((memory.get("metadata") or {}).get("memory_type") or "fact")
                in {"fact", "preference", "error", "context"}
            ]
            
            if not results:
                return [{"type": "text", "text": "未找到相关记忆"}]
            
            lines = ["相关长期记忆："]
            for memory in results:
                metadata = memory.get("metadata") or {}
                sender = str(
                    metadata.get("speaker")
                    or metadata.get("speaker_label")
                    or metadata.get("sender")
                    or ""
                ).strip()
                content = str(memory.get("content") or "").strip()
                if not content:
                    continue
                prefix = f"{sender}: " if sender and not content.startswith(sender) else ""
                lines.append(f"- {prefix}{content}")
            
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
            memories = [
                memory
                for memory in memories
                if str((memory.get("metadata") or {}).get("memory_type") or "fact")
                in {"fact", "preference", "error", "context"}
            ]
            
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
                return [{"type": "text", "text": "记忆不存在或删除失败"}]
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
