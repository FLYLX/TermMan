from __future__ import annotations

import logging
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

SOURCE_QQ = "qq"
SOURCE_WEB = "web"
SOURCE_TERMINAL = "terminal"

TICKET_TTL = timedelta(hours=6)
CURRENT_QQ_MESSAGE_MARKER = "[Current QQ message]"
CQ_IMAGE_RE = re.compile(r"\[CQ:image(?:,[^\]]*)?\]", re.IGNORECASE)


@dataclass
class ReplyTicket:
    ticket_id: str
    item_id: str
    handler_id: str
    source_type: str
    source_label: str
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    status: str = "pending"
    task_request_id: str = ""
    request_message: str = ""
    command: str = ""
    delivered_at: datetime | None = None
    delivery_error: str = ""
    robot_id: str = ""
    sender_key: str = ""
    sender_label: str = ""
    conversation_key: str = ""
    conversation_generation: int = 0
    reply_target: dict[str, Any] = field(default_factory=dict)
    scheduled_task_id: str = ""
    scheduled_execution_id: str = ""
    terminal_target: str = ""
    pending_reply_active: bool = False
    pending_reply_status: str = "pending"
    pending_reply_requester: str = ""
    pending_reply_plan: list[str] = field(default_factory=list)
    pending_reply_awaiting_kind: str = ""
    pending_reply_awaiting_key: str = ""
    pending_reply_created_at: datetime | None = None

    @property
    def is_qq(self) -> bool:
        return self.source_type == SOURCE_QQ and bool(self.robot_id and self.reply_target)


class ReplyTicketManager:
    def __init__(self) -> None:
        self._tickets: dict[str, ReplyTicket] = {}
        self._lock = threading.RLock()

    def _prune_locked(self, now: datetime) -> None:
        cutoff = now - TICKET_TTL
        stale_ids = [
            ticket_id
            for ticket_id, ticket in self._tickets.items()
            if not ticket.pending_reply_active
            and ticket.updated_at < cutoff
            and (
                ticket.status == "delivered"
                or bool(ticket.scheduled_task_id)
            )
        ]
        for ticket_id in stale_ids:
            self._tickets.pop(ticket_id, None)

    def reset(self) -> None:
        with self._lock:
            self._tickets.clear()

    @staticmethod
    def _robot_request_message(reply_target: Any, fallback: str) -> str:
        metadata = getattr(reply_target, "metadata", None)
        metadata = metadata if isinstance(metadata, dict) else {}
        native_message = metadata.get("message")
        native_message = native_message if isinstance(native_message, dict) else {}
        text = str(
            native_message.get("raw_message")
            or native_message.get("plain_text")
            or ""
        ).strip()
        if not text:
            raw_fallback = str(fallback or "")
            if CURRENT_QQ_MESSAGE_MARKER in raw_fallback:
                text = raw_fallback.rsplit(CURRENT_QQ_MESSAGE_MARKER, 1)[-1].strip()
            else:
                text = raw_fallback.strip()
        text = CQ_IMAGE_RE.sub("", text)
        return re.sub(r"\s+", " ", text).strip()[:500]

    @staticmethod
    def _robot_sender_label(reply_target: Any, sender_key: str) -> str:
        metadata = getattr(reply_target, "metadata", None)
        metadata = metadata if isinstance(metadata, dict) else {}
        sender = metadata.get("sender")
        sender = sender if isinstance(sender, dict) else {}
        sender_id = str(sender.get("user_id") or "").strip()
        display_name = str(
            sender.get("display_name")
            or sender.get("card")
            or sender.get("nickname")
            or sender_id
            or sender_key
            or ""
        ).strip()
        if display_name and sender_id and display_name != sender_id:
            return f"{display_name} ({sender_id})"
        return display_name or sender_key

    def create_for_agent(
        self,
        agent: Any,
        *,
        item_id: str,
        handler_id: str,
        message: str = "",
        source_type: str | None = None,
    ) -> ReplyTicket:
        now = datetime.now()
        forced_source_type = str(source_type or "").strip().lower()
        context = getattr(agent, "_context", None)
        robot_id = str(getattr(context, "robot_id", "") or "").strip()
        ticket = ReplyTicket(
            ticket_id=uuid.uuid4().hex,
            item_id=str(item_id),
            handler_id=str(handler_id),
            source_type=SOURCE_WEB,
            source_label="TermMan web chat",
            request_message=str(message or "").strip()[:500],
        )

        if forced_source_type == SOURCE_WEB:
            robot_id = ""

        if robot_id:
            try:
                from app.plugins.robot.mcp.context import get_robot_mcp_context

                robot_context = get_robot_mcp_context(
                    str(getattr(context, "robot_context_token", "") or "").strip()
                )
            except Exception:
                robot_context = None

            reply_target = getattr(robot_context, "reply_target", None)
            sender_key = str(getattr(robot_context, "sender_key", "") or "").strip()
            conversation_key = str(
                getattr(robot_context, "conversation_key", "") or ""
            ).strip()
            if reply_target is not None and hasattr(reply_target, "model_dump"):
                ticket.source_type = SOURCE_QQ
                ticket.source_label = f"QQ {conversation_key or 'current conversation'}"
                ticket.robot_id = robot_id
                ticket.sender_key = sender_key
                ticket.sender_label = self._robot_sender_label(
                    reply_target,
                    sender_key,
                )
                ticket.conversation_key = conversation_key
                ticket.conversation_generation = int(
                    getattr(robot_context, "conversation_generation", 0) or 0
                )
                ticket.reply_target = reply_target.model_dump(mode="json")
                ticket.request_message = self._robot_request_message(
                    reply_target,
                    message,
                )

        if forced_source_type == SOURCE_QQ and ticket.source_type != SOURCE_QQ:
            logger.warning(
                "[ReplyTicket] Requested QQ source but no active robot context was available: item=%s handler=%s",
                item_id,
                handler_id,
            )

        with self._lock:
            self._prune_locked(now)
            self._tickets[ticket.ticket_id] = ticket
        self.attach_to_agent(agent, ticket.ticket_id)
        return ticket

    def create_for_scheduled_task(
        self,
        agent: Any,
        *,
        item_id: str,
        handler_id: str,
        message: str,
        scheduled_task_id: str,
        scheduled_execution_id: str = "",
    ) -> ReplyTicket:
        ticket = self.create_for_agent(
            agent,
            item_id=item_id,
            handler_id=handler_id,
            message=message,
            source_type=SOURCE_WEB,
        )
        with self._lock:
            ticket.source_label = "TermMan scheduled task"
            ticket.request_message = str(message or "")[:4000]
            ticket.scheduled_task_id = str(scheduled_task_id or "").strip()
            ticket.scheduled_execution_id = str(
                scheduled_execution_id or ""
            ).strip()
            ticket.updated_at = datetime.now()
        return ticket

    def create_for_terminal(
        self,
        agent: Any,
        *,
        item_id: str,
        handler_id: str,
        player: str,
        message: str,
    ) -> ReplyTicket:
        ticket = ReplyTicket(
            ticket_id=uuid.uuid4().hex,
            item_id=str(item_id),
            handler_id=str(handler_id),
            source_type=SOURCE_TERMINAL,
            source_label=f"Minecraft player {player}",
            sender_key=str(player),
            sender_label=str(player),
            request_message=str(message or "")[:500],
            terminal_target=str(player),
        )
        now = datetime.now()
        with self._lock:
            self._prune_locked(now)
            self._tickets[ticket.ticket_id] = ticket
        self.attach_to_agent(agent, ticket.ticket_id)
        return ticket

    @staticmethod
    def _destination_label(ticket: ReplyTicket) -> str:
        if ticket.source_type == SOURCE_QQ:
            return ticket.source_label or f"QQ {ticket.conversation_key}"
        if ticket.source_type == SOURCE_TERMINAL:
            return f"Minecraft tell {ticket.terminal_target or ticket.sender_label}"
        return ticket.source_label or "TermMan web chat"

    def upsert_pending_reply(
        self,
        ticket_id: str,
        *,
        requester: str = "",
        request_summary: str = "",
        task_plan: list[str] | None = None,
        status: str = "working",
        awaiting_kind: str = "",
        awaiting_key: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            ticket = self._tickets.get(str(ticket_id))
            if not ticket:
                raise KeyError(f"reply ticket not found: {ticket_id}")
            now = datetime.now()
            ticket.pending_reply_active = True
            ticket.pending_reply_status = str(status or "working")[:32]
            ticket.pending_reply_requester = str(
                requester
                or ticket.sender_label
                or ticket.sender_key
                or ticket.source_label
            )[:200]
            if request_summary:
                ticket.request_message = str(request_summary)[:500]
            if task_plan is not None:
                ticket.pending_reply_plan = [
                    str(step).strip()[:500]
                    for step in task_plan
                    if str(step).strip()
                ][:12]
            if awaiting_kind:
                ticket.pending_reply_awaiting_kind = str(awaiting_kind)[:64]
            if awaiting_key:
                ticket.pending_reply_awaiting_key = str(awaiting_key)[:200]
            ticket.pending_reply_created_at = ticket.pending_reply_created_at or now
            ticket.updated_at = now
            if ticket.status == "delivered":
                ticket.status = "running"
            return self._pending_reply_snapshot(ticket)

    def delete_pending_reply(self, ticket_id: str, *, reason: str = "") -> bool:
        with self._lock:
            ticket = self._tickets.get(str(ticket_id))
            if not ticket or not ticket.pending_reply_active:
                return False
            self._tickets.pop(str(ticket_id), None)
        try:
            from app.services.agent.task_workflow import task_workflow_manager

            task_workflow_manager.update(
                str(ticket_id),
                action="cancel",
                note=str(reason or "Pending reply deleted")[:500],
            )
        except Exception:
            pass
        return True

    def complete_pending_reply_after_external_delivery(self, ticket_id: str) -> bool:
        with self._lock:
            ticket = self._tickets.get(str(ticket_id))
            if not ticket or not ticket.pending_reply_active:
                return False
            now = datetime.now()
            ticket.status = "delivered"
            ticket.delivered_at = now
            ticket.updated_at = now
            ticket.delivery_error = ""
            self._tickets.pop(str(ticket_id), None)
        try:
            from app.services.agent.task_workflow import task_workflow_manager

            task_workflow_manager.on_delivery(ticket_id)
        except Exception:
            logger.exception(
                "[ReplyTicket] Failed to complete workflow after external delivery: ticket=%s",
                ticket_id,
            )
        return True

    def _pending_reply_snapshot(self, ticket: ReplyTicket) -> dict[str, Any]:
        workflow = None
        try:
            from app.services.agent.task_workflow import task_workflow_manager

            workflow = task_workflow_manager.snapshot_for_ticket(ticket.ticket_id)
        except Exception:
            pass
        plan = list(ticket.pending_reply_plan)
        if not plan and isinstance(workflow, dict):
            plan = [
                str(step.get("title") or "")
                for step in workflow.get("steps") or []
                if isinstance(step, dict) and step.get("title")
            ]
        return {
            "id": ticket.ticket_id,
            "item_id": ticket.item_id,
            "requester": ticket.pending_reply_requester
            or ticket.sender_label
            or ticket.sender_key
            or ticket.source_label,
            "request_summary": ticket.request_message,
            "task_plan": plan,
            "destination_type": ticket.source_type,
            "destination_label": self._destination_label(ticket),
            "status": ticket.pending_reply_status,
            "awaiting_kind": ticket.pending_reply_awaiting_kind,
            "awaiting_key": ticket.pending_reply_awaiting_key,
            "last_error": ticket.delivery_error,
            "created_at": (
                ticket.pending_reply_created_at or ticket.created_at
            ).isoformat(),
            "updated_at": ticket.updated_at.isoformat(),
            "workflow": workflow,
        }

    def list_pending_replies(self, item_id: str) -> list[dict[str, Any]]:
        with self._lock:
            tickets = [
                ticket
                for ticket in self._tickets.values()
                if ticket.item_id == str(item_id) and ticket.pending_reply_active
            ]
        tickets.sort(key=lambda ticket: ticket.updated_at, reverse=True)
        return [self._pending_reply_snapshot(ticket) for ticket in tickets]

    def match_pending_reply(
        self,
        item_id: str,
        current_input: str,
    ) -> dict[str, Any] | None:
        text = str(current_input or "")
        with self._lock:
            candidates = [
                ticket
                for ticket in self._tickets.values()
                if ticket.item_id == str(item_id)
                and ticket.pending_reply_active
                and ticket.pending_reply_awaiting_key
            ]
        candidates.sort(
            key=lambda ticket: ticket.pending_reply_created_at or ticket.created_at
        )
        for ticket in candidates:
            key = ticket.pending_reply_awaiting_key
            if ticket.pending_reply_awaiting_kind == "minecraft_player":
                if not re.search(
                    rf"<\s*{re.escape(key)}\s*>\s+\S",
                    text,
                    flags=re.IGNORECASE,
                ):
                    continue
            elif key.casefold() not in text.casefold():
                continue
            return self._pending_reply_snapshot(ticket)
        return None

    def build_pending_reply_prompt(
        self,
        item_id: str,
        *,
        current_input: str = "",
    ) -> str:
        entries = self.list_pending_replies(item_id)
        if not entries:
            return ""
        normalized_input = str(current_input or "").casefold()
        lines = [
            "Authoritative task queue:",
            "Each entry locks requester, task plan, and return destination together.",
        ]
        for entry in entries[:8]:
            awaiting_key = str(entry.get("awaiting_key") or "")
            matched = bool(awaiting_key and awaiting_key.casefold() in normalized_input)
            lines.append(
                f"- id={entry['id']}; requester={entry['requester']}; "
                f"destination={entry['destination_label']}; status={entry['status']}; "
                f"current_input_matches_awaiting={'yes' if matched else 'no'}"
            )
            lines.append(f"  request={entry['request_summary']}")
            if entry.get("task_plan"):
                lines.append("  plan=" + " -> ".join(entry["task_plan"]))
            if entry.get("awaiting_kind") or awaiting_key:
                lines.append(
                    f"  awaiting={entry.get('awaiting_kind') or 'event'}:"
                    f"{awaiting_key or 'unspecified'}"
                )
        lines.extend(
            [
                "Queue rules:",
                "1. For delegated, multi-step, asynchronous, or wait-for-response work, "
                "call mcp_local_write_pending_reply before or when starting the work.",
                "2. Update the same entry when the plan or awaited target changes; never "
                "create a different destination for the same task.",
                "3. When evidence completes the task, mark the task workflow ready and call "
                "mcp_local_send_pending_reply with the matching entry id.",
                "4. send_pending_reply uses the stored destination, sends first, and removes "
                "the entry only after success. Do not separately call QQ/tell/web delivery "
                "tools for the same final report.",
                "5. If current_input_matches_awaiting=yes, decide whether the new input really "
                "answers that entry. If yes, finish and send that entry; if unrelated, keep it.",
            ]
        )
        return "\n".join(lines)

    def attach_to_agent(self, agent: Any, ticket_id: str) -> None:
        context = getattr(agent, "_context", None)
        if context is not None:
            context.reply_ticket_id = ticket_id

    def detach_from_agent(self, agent: Any, ticket_id: str) -> None:
        context = getattr(agent, "_context", None)
        if context is None:
            return
        if str(getattr(context, "reply_ticket_id", "") or "") == ticket_id:
            context.reply_ticket_id = ""

    def get(self, ticket_id: str) -> ReplyTicket | None:
        if not ticket_id:
            return None
        with self._lock:
            return self._tickets.get(str(ticket_id))

    def mark_task_plan(self, ticket_id: str, task_request_id: str) -> None:
        with self._lock:
            ticket = self._tickets.get(str(ticket_id))
            if not ticket:
                return
            ticket.task_request_id = str(task_request_id or "")
            ticket.status = "running"
            ticket.updated_at = datetime.now()

    def mark_command(self, ticket_id: str, command: str) -> None:
        with self._lock:
            ticket = self._tickets.get(str(ticket_id))
            if not ticket:
                return
            ticket.command = str(command or "")
            ticket.status = "running"
            ticket.updated_at = datetime.now()

    def mark_completed(self, ticket_id: str) -> None:
        with self._lock:
            ticket = self._tickets.get(str(ticket_id))
            if not ticket:
                return
            if ticket.status != "delivered":
                ticket.status = "completed"
            ticket.updated_at = datetime.now()

    def mark_failed(self, ticket_id: str, error: str = "") -> None:
        with self._lock:
            ticket = self._tickets.get(str(ticket_id))
            if not ticket:
                return
            ticket.status = "failed"
            ticket.delivery_error = str(error or "")
            ticket.updated_at = datetime.now()

    def mark_delivered(self, ticket_id: str) -> bool:
        try:
            from app.services.agent.task_workflow import task_workflow_manager

            can_finalize, reason = task_workflow_manager.can_finalize(ticket_id)
            if not can_finalize:
                logger.info(
                    "[ReplyTicket] Kept ticket active after intermediate delivery: ticket=%s reason=%s",
                    ticket_id,
                    reason,
                )
                return False
        except Exception:
            logger.exception(
                "[ReplyTicket] Failed to validate workflow delivery state: ticket=%s",
                ticket_id,
            )
            return False

        with self._lock:
            ticket = self._tickets.get(str(ticket_id))
            if not ticket:
                return False
            if ticket.pending_reply_active:
                ticket.status = "running"
                ticket.pending_reply_status = "working"
                ticket.updated_at = datetime.now()
                ticket.delivery_error = ""
                return True
            now = datetime.now()
            ticket.status = "delivered"
            ticket.delivered_at = now
            ticket.updated_at = now
            ticket.delivery_error = ""
        try:
            from app.services.agent.task_workflow import task_workflow_manager

            task_workflow_manager.on_delivery(ticket_id)
        except Exception:
            logger.exception(
                "[ReplyTicket] Failed to complete task workflow after delivery: ticket=%s",
                ticket_id,
            )
        return True

    def build_prompt(self, ticket_id: str) -> str:
        ticket = self.get(ticket_id)
        if not ticket:
            return ""
        if ticket.pending_reply_active:
            entry = self._pending_reply_snapshot(ticket)
            return (
                "Authoritative task queue entry:\n"
                f"- entry_id: {entry['id']}\n"
                f"- requester: {entry['requester']}\n"
                f"- request: {entry['request_summary']}\n"
                f"- immutable destination: {entry['destination_label']}\n"
                f"- status: {entry['status']}\n"
                f"- plan: {' -> '.join(entry['task_plan']) or '(not recorded)'}\n"
                f"- awaiting: {entry['awaiting_kind'] or 'none'}:"
                f"{entry['awaiting_key'] or 'none'}\n"
                "- update this entry with mcp_local_write_pending_reply as work changes.\n"
                "- after the task is genuinely complete, call mcp_local_send_pending_reply "
                "with this entry_id. It sends to the immutable destination and deletes the "
                "entry only after success.\n"
                "- do not use normal final assistant text, mcp_robot_send_message, or a raw "
                "tell/say command for the final report.\n"
            )
        if ticket.scheduled_task_id:
            return (
                "Authoritative scheduled task ticket:\n"
                f"- ticket_id: {ticket.ticket_id}\n"
                f"- schedule_id: {ticket.scheduled_task_id}\n"
                f"- execution_id: {ticket.scheduled_execution_id or 'unknown'}\n"
                "- source: TermMan scheduled task\n"
                "- treat terminal/background-job feedback as the continuation of this "
                "scheduled execution.\n"
                "- on failure, keep the task for transient failures. Delete it with "
                "mcp_local_delete_scheduled_task only if it is obsolete, invalid, unsafe, "
                "or permanently unable to succeed.\n"
                "- any visible report must be labelled as a scheduled task result.\n"
            )
        if ticket.source_type == SOURCE_QQ:
            return (
                "Authoritative reply ticket:\n"
                f"- ticket_id: {ticket.ticket_id}\n"
                f"- source: QQ ({ticket.conversation_key or 'current conversation'})\n"
                "- completion route: reply to this same QQ source only. Do not send to "
                "any other QQ group/private chat.\n"
                "- if you already called `mcp_robot_send_message`, do not restate the "
                "same answer in final assistant text.\n"
                "- if you only produce normal final text, TermMan will deliver that text "
                "through this ticket to the original QQ source.\n"
            )
        if ticket.source_type == SOURCE_WEB:
            return (
                "Authoritative reply ticket:\n"
                f"- ticket_id: {ticket.ticket_id}\n"
                "- source: TermMan web chat\n"
                "- completion route: answer only in this web chat response.\n"
                "- do not call QQ tools and do not reuse old QQ targets unless the current "
                "web user explicitly asks to send a message to a specific QQ target.\n"
            )
        return (
            "Authoritative reply ticket:\n"
            f"- ticket_id: {ticket.ticket_id}\n"
            f"- source: {ticket.source_type}\n"
            "- completion route: answer back to the same source.\n"
        )

    def deliver(self, ticket_id: str, content: str) -> bool:
        text = str(content or "").strip()
        if not ticket_id or not text:
            return False
        with self._lock:
            ticket = self._tickets.get(str(ticket_id))
            if not ticket or ticket.status == "delivered":
                return False
            if not ticket.is_qq:
                return False
            ticket.status = "sending"
            ticket.updated_at = datetime.now()

        try:
            from app.plugins.robot.bridge_client import robot_bridge_client
            from app.plugins.robot.contracts import RobotReplyTarget
            from app.plugins.robot.conversation_memory import robot_conversation_memory

            target = RobotReplyTarget.model_validate(ticket.reply_target)
            robot_bridge_client.send_message(ticket.robot_id, target, text)
            if ticket.conversation_key:
                robot_conversation_memory.append_assistant_message(
                    ticket.robot_id,
                    ticket.conversation_key,
                    text,
                )
        except Exception as exc:
            logger.warning(
                "[ReplyTicket] Failed to deliver ticket=%s source=%s: %s",
                ticket_id,
                ticket.source_label,
                exc,
            )
            with self._lock:
                current = self._tickets.get(str(ticket_id))
                if current:
                    current.status = "failed"
                    current.delivery_error = str(exc)
                    current.updated_at = datetime.now()
            try:
                from app.services.agent.task_workflow import task_workflow_manager

                task_workflow_manager.mark_delivery_failed(ticket_id, str(exc))
            except Exception:
                pass
            return False

        self.mark_delivered(ticket_id)
        return True

    def send_pending_reply(self, ticket_id: str, content: str) -> tuple[bool, str]:
        text = str(content or "").strip()
        if not text:
            return False, "reply content is required"
        with self._lock:
            ticket = self._tickets.get(str(ticket_id))
            if not ticket or not ticket.pending_reply_active:
                return False, "pending reply not found"

        try:
            from app.services.agent.task_workflow import task_workflow_manager

            can_finalize, reason = task_workflow_manager.can_finalize(ticket.ticket_id)
            if not can_finalize:
                return False, reason
        except Exception as exc:
            return False, f"failed to validate task workflow: {exc}"

        with self._lock:
            current = self._tickets.get(str(ticket_id))
            if not current or not current.pending_reply_active:
                return False, "pending reply not found"
            current.status = "sending"
            current.pending_reply_status = "sending"
            current.updated_at = datetime.now()

        try:
            if ticket.source_type == SOURCE_QQ:
                from app.plugins.robot.bridge_client import robot_bridge_client
                from app.plugins.robot.contracts import RobotReplyTarget
                from app.plugins.robot.conversation_memory import (
                    robot_conversation_memory,
                )

                target = RobotReplyTarget.model_validate(ticket.reply_target)
                robot_bridge_client.send_message(ticket.robot_id, target, text)
                if ticket.conversation_key:
                    robot_conversation_memory.append_assistant_message(
                        ticket.robot_id,
                        ticket.conversation_key,
                        text,
                    )
            elif ticket.source_type == SOURCE_TERMINAL:
                from app.services.socket_pool import InputSDK

                target_player = ticket.terminal_target or ticket.sender_key
                if not target_player:
                    raise ValueError("terminal player target is missing")
                command = f"tell {target_player} {text}\n"
                if not InputSDK().send(ticket.item_id, command):
                    raise RuntimeError("terminal command was not accepted")
            elif ticket.source_type == SOURCE_WEB:
                from app.services.agent.history.chat import append_chat_message
                from app.services.agent.stream_manager import stream_manager

                event = append_chat_message(
                    ticket.item_id,
                    role="assistant",
                    content=text,
                    message_type="agent_response",
                    extra={"pending_reply_id": ticket.ticket_id},
                )
                stream_manager.broadcast_chat_event(ticket.item_id, event)
            else:
                raise ValueError(f"unsupported destination type: {ticket.source_type}")
        except Exception as exc:
            with self._lock:
                current = self._tickets.get(str(ticket_id))
                if current:
                    current.status = "failed"
                    current.pending_reply_status = "failed"
                    current.delivery_error = str(exc)[:1000]
                    current.updated_at = datetime.now()
            try:
                from app.services.agent.task_workflow import task_workflow_manager

                task_workflow_manager.mark_delivery_failed(ticket.ticket_id, str(exc))
            except Exception:
                pass
            return False, str(exc)

        with self._lock:
            self._tickets.pop(str(ticket_id), None)
        try:
            from app.services.agent.task_workflow import task_workflow_manager

            task_workflow_manager.on_delivery(ticket.ticket_id)
        except Exception:
            pass
        return True, self._destination_label(ticket)

    def snapshot(self, item_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            tickets = list(self._tickets.values())
        if item_id:
            tickets = [ticket for ticket in tickets if ticket.item_id == str(item_id)]
        tickets.sort(key=lambda ticket: ticket.updated_at, reverse=True)
        snapshots: list[dict[str, Any]] = []
        for ticket in tickets:
            workflow = None
            try:
                from app.services.agent.task_workflow import task_workflow_manager

                workflow = task_workflow_manager.snapshot_for_ticket(ticket.ticket_id)
            except Exception:
                pass
            snapshots.append(
                {
                    "ticket_id": ticket.ticket_id,
                    "item_id": ticket.item_id,
                    "handler_id": ticket.handler_id,
                    "source_type": ticket.source_type,
                    "source_label": ticket.source_label,
                    "status": ticket.status,
                    "task_request_id": ticket.task_request_id,
                    "request_message": ticket.request_message,
                    "command": ticket.command,
                    "created_at": ticket.created_at.isoformat(),
                    "updated_at": ticket.updated_at.isoformat(),
                    "delivered_at": ticket.delivered_at.isoformat()
                    if ticket.delivered_at
                    else None,
                    "delivery_error": ticket.delivery_error,
                    "scheduled_task_id": ticket.scheduled_task_id,
                    "scheduled_execution_id": ticket.scheduled_execution_id,
                    "pending_reply_active": ticket.pending_reply_active,
                    "pending_reply_status": ticket.pending_reply_status,
                    "pending_reply_requester": ticket.pending_reply_requester,
                    "pending_reply_plan": list(ticket.pending_reply_plan),
                    "pending_reply_awaiting_kind": ticket.pending_reply_awaiting_kind,
                    "pending_reply_awaiting_key": ticket.pending_reply_awaiting_key,
                    "robot_id": ticket.robot_id,
                    "sender_key": ticket.sender_key,
                    "sender_label": ticket.sender_label,
                    "conversation_key": ticket.conversation_key,
                    "conversation_generation": ticket.conversation_generation,
                    "workflow": workflow,
                }
            )
        return snapshots


reply_ticket_manager = ReplyTicketManager()
