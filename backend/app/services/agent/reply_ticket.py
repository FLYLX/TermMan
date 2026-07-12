from __future__ import annotations

import logging
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
    command: str = ""
    delivered_at: datetime | None = None
    delivery_error: str = ""
    robot_id: str = ""
    sender_key: str = ""
    conversation_key: str = ""
    conversation_generation: int = 0
    reply_target: dict[str, Any] = field(default_factory=dict)

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
            if ticket.updated_at < cutoff
        ]
        for ticket_id in stale_ids:
            self._tickets.pop(ticket_id, None)

    def reset(self) -> None:
        with self._lock:
            self._tickets.clear()

    def create_for_agent(
        self,
        agent: Any,
        *,
        item_id: str,
        handler_id: str,
        message: str = "",
    ) -> ReplyTicket:
        now = datetime.now()
        context = getattr(agent, "_context", None)
        robot_id = str(getattr(context, "robot_id", "") or "").strip()
        ticket = ReplyTicket(
            ticket_id=uuid.uuid4().hex,
            item_id=str(item_id),
            handler_id=str(handler_id),
            source_type=SOURCE_WEB,
            source_label="TermMan web chat",
        )

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
                ticket.conversation_key = conversation_key
                ticket.conversation_generation = int(
                    getattr(robot_context, "conversation_generation", 0) or 0
                )
                ticket.reply_target = reply_target.model_dump(mode="json")

        with self._lock:
            self._prune_locked(now)
            self._tickets[ticket.ticket_id] = ticket
        self.attach_to_agent(agent, ticket.ticket_id)
        return ticket

    def attach_to_agent(self, agent: Any, ticket_id: str) -> None:
        context = getattr(agent, "_context", None)
        if context is not None:
            setattr(context, "reply_ticket_id", ticket_id)

    def detach_from_agent(self, agent: Any, ticket_id: str) -> None:
        context = getattr(agent, "_context", None)
        if context is None:
            return
        if str(getattr(context, "reply_ticket_id", "") or "") == ticket_id:
            setattr(context, "reply_ticket_id", "")

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

    def mark_delivered(self, ticket_id: str) -> None:
        with self._lock:
            ticket = self._tickets.get(str(ticket_id))
            if not ticket:
                return
            now = datetime.now()
            ticket.status = "delivered"
            ticket.delivered_at = now
            ticket.updated_at = now
            ticket.delivery_error = ""

    def build_prompt(self, ticket_id: str) -> str:
        ticket = self.get(ticket_id)
        if not ticket:
            return ""
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
            return False

        self.mark_delivered(ticket_id)
        return True

    def snapshot(self, item_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            tickets = list(self._tickets.values())
        if item_id:
            tickets = [ticket for ticket in tickets if ticket.item_id == str(item_id)]
        tickets.sort(key=lambda ticket: ticket.updated_at, reverse=True)
        return [
            {
                "ticket_id": ticket.ticket_id,
                "item_id": ticket.item_id,
                "handler_id": ticket.handler_id,
                "source_type": ticket.source_type,
                "source_label": ticket.source_label,
                "status": ticket.status,
                "task_request_id": ticket.task_request_id,
                "command": ticket.command,
                "created_at": ticket.created_at.isoformat(),
                "updated_at": ticket.updated_at.isoformat(),
                "delivered_at": ticket.delivered_at.isoformat()
                if ticket.delivered_at
                else None,
                "delivery_error": ticket.delivery_error,
            }
            for ticket in tickets
        ]


reply_ticket_manager = ReplyTicketManager()
