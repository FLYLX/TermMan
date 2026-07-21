from __future__ import annotations

import logging
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from dataclasses import fields as dataclass_fields
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

SOURCE_QQ = "qq"
SOURCE_WEB = "web"
SOURCE_TERMINAL = "terminal"

TICKET_TTL = timedelta(hours=6)
CURRENT_QQ_MESSAGE_MARKER = "[Current QQ message]"
CQ_CODE_RE = re.compile(r"\[CQ:[^\]]+\]", re.IGNORECASE)

TICKET_ALIASES_KV_KEY = "reply_ticket_aliases"


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def ticket_to_payload(ticket: ReplyTicket) -> dict[str, Any]:
    payload = asdict(ticket)
    for key in ("created_at", "updated_at", "delivered_at"):
        value = payload.get(key)
        payload[key] = value.isoformat() if isinstance(value, datetime) else None
    return payload


def ticket_from_payload(payload: dict[str, Any]) -> ReplyTicket:
    allowed = {field_info.name for field_info in dataclass_fields(ReplyTicket)}
    kwargs = {key: value for key, value in dict(payload or {}).items() if key in allowed}
    kwargs["created_at"] = _parse_dt(kwargs.get("created_at")) or datetime.now()
    kwargs["updated_at"] = _parse_dt(kwargs.get("updated_at")) or datetime.now()
    kwargs["delivered_at"] = _parse_dt(kwargs.get("delivered_at"))
    kwargs["reply_target"] = dict(kwargs.get("reply_target") or {})
    return ReplyTicket(**kwargs)


def _persist_ticket(ticket: ReplyTicket | None) -> None:
    if ticket is None:
        return
    try:
        from app.services.agent import state_store

        state_store.save_ticket(ticket_to_payload(ticket))
    except Exception as exc:
        logger.debug("[ReplyTicket] Persist ticket failed: %s", exc)


def _delete_persisted_tickets(ticket_ids: list[str]) -> None:
    if not ticket_ids:
        return
    try:
        from app.services.agent import state_store

        for ticket_id in ticket_ids:
            state_store.delete_ticket(ticket_id)
    except Exception as exc:
        logger.debug("[ReplyTicket] Delete persisted tickets failed: %s", exc)


def _persist_aliases(aliases: dict[str, str]) -> None:
    try:
        from app.services.agent import state_store

        state_store.save_kv(TICKET_ALIASES_KV_KEY, {"aliases": dict(aliases)})
    except Exception as exc:
        logger.debug("[ReplyTicket] Persist ticket aliases failed: %s", exc)


def restore_tickets_from_store() -> int:
    try:
        from app.services.agent import state_store
    except Exception:
        return 0
    restored = 0
    with reply_ticket_manager._lock:
        for payload in state_store.load_tickets():
            try:
                ticket = ticket_from_payload(payload)
            except Exception:
                continue
            reply_ticket_manager._tickets[ticket.ticket_id] = ticket
            restored += 1
        aliases = state_store.load_kv(TICKET_ALIASES_KV_KEY).get("aliases")
        if isinstance(aliases, dict):
            reply_ticket_manager._ticket_aliases.update(
                {str(key): str(value) for key, value in aliases.items()}
            )
        # Drop tickets that went stale while the process was down; otherwise
        # they would be restored forever and fake "processing" in the UI.
        reply_ticket_manager._prune_locked(datetime.now())
    return restored


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
    external_report_sent: bool = False

    @property
    def is_qq(self) -> bool:
        return self.source_type == SOURCE_QQ and bool(self.robot_id and self.reply_target)


class ReplyTicketManager:
    def __init__(self) -> None:
        self._tickets: dict[str, ReplyTicket] = {}
        self._ticket_aliases: dict[str, str] = {}
        self._lock = threading.RLock()

    def _resolve_ticket_id_locked(self, ticket_id: str) -> str:
        current = str(ticket_id or "")
        visited: set[str] = set()
        while current in self._ticket_aliases and current not in visited:
            visited.add(current)
            current = self._ticket_aliases[current]
        return current

    def resolve_ticket_id(self, ticket_id: str) -> str:
        with self._lock:
            return self._resolve_ticket_id_locked(ticket_id)

    def _remove_aliases_for_locked(self, ticket_id: str) -> None:
        resolved = self._resolve_ticket_id_locked(ticket_id)
        stale_aliases = [
            alias
            for alias, target in self._ticket_aliases.items()
            if alias == resolved or self._resolve_ticket_id_locked(target) == resolved
        ]
        for alias in stale_aliases:
            self._ticket_aliases.pop(alias, None)

    def _prune_locked(self, now: datetime) -> None:
        cutoff = now - TICKET_TTL
        # Prune every ticket untouched for longer than the TTL, regardless of
        # status: a ticket stuck in pending/running/failed that long will
        # never be delivered (in-memory agent state cannot survive that), and
        # keeping it only fakes a permanent "processing" row in the UI.
        stale_ids = [
            ticket_id
            for ticket_id, ticket in self._tickets.items()
            if ticket.updated_at < cutoff
        ]
        for ticket_id in stale_ids:
            self._tickets.pop(ticket_id, None)
            self._remove_aliases_for_locked(ticket_id)
        _delete_persisted_tickets(stale_ids)
        _persist_aliases(self._ticket_aliases)

    def reset(self) -> None:
        with self._lock:
            _delete_persisted_tickets(list(self._tickets.keys()))
            self._tickets.clear()
            self._ticket_aliases.clear()
            _persist_aliases(self._ticket_aliases)
        try:
            from app.services.agent.task_workflow import task_workflow_manager

            task_workflow_manager.reset()
        except Exception:
            pass

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
        text = CQ_CODE_RE.sub(" ", text)
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
        _persist_ticket(ticket)
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
        _persist_ticket(ticket)
        return ticket

    @staticmethod
    def _sanitize_delivery_text(content: Any) -> str:
        try:
            from app.plugins.robot.internal_trace import sanitize_robot_visible_text

            return sanitize_robot_visible_text(content).strip()
        except Exception:
            return str(content or "").strip()

    def create_for_terminal(        self,
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
        _persist_ticket(ticket)
        return ticket

    def attach_to_agent(self, agent: Any, ticket_id: str) -> None:
        context = getattr(agent, "_context", None)
        if context is not None:
            context.reply_ticket_id = self.resolve_ticket_id(ticket_id)

    def detach_from_agent(self, agent: Any, ticket_id: str) -> None:
        context = getattr(agent, "_context", None)
        if context is None:
            return
        resolved_ticket_id = self.resolve_ticket_id(ticket_id)
        if str(getattr(context, "reply_ticket_id", "") or "") in {
            str(ticket_id or ""),
            resolved_ticket_id,
        }:
            context.reply_ticket_id = ""

    def get(self, ticket_id: str) -> ReplyTicket | None:
        if not ticket_id:
            return None
        with self._lock:
            return self._tickets.get(self._resolve_ticket_id_locked(ticket_id))

    def mark_task_plan(self, ticket_id: str, task_request_id: str) -> None:
        with self._lock:
            ticket_id = self._resolve_ticket_id_locked(ticket_id)
            ticket = self._tickets.get(ticket_id)
            if not ticket:
                return
            ticket.task_request_id = str(task_request_id or "")
            ticket.status = "running"
            ticket.updated_at = datetime.now()
            _persist_ticket(ticket)

    def mark_command(self, ticket_id: str, command: str) -> None:
        with self._lock:
            ticket_id = self._resolve_ticket_id_locked(ticket_id)
            ticket = self._tickets.get(ticket_id)
            if not ticket:
                return
            ticket.command = str(command or "")
            ticket.status = "running"
            ticket.updated_at = datetime.now()
            _persist_ticket(ticket)

    def mark_completed(self, ticket_id: str) -> None:
        with self._lock:
            ticket_id = self._resolve_ticket_id_locked(ticket_id)
            ticket = self._tickets.get(ticket_id)
            if not ticket:
                return
            if ticket.status != "delivered":
                ticket.status = "completed"
            ticket.updated_at = datetime.now()
            _persist_ticket(ticket)

    def mark_failed(self, ticket_id: str, error: str = "") -> None:
        with self._lock:
            ticket_id = self._resolve_ticket_id_locked(ticket_id)
            ticket = self._tickets.get(ticket_id)
            if not ticket:
                return
            ticket.status = "failed"
            ticket.delivery_error = str(error or "")
            ticket.updated_at = datetime.now()
            _persist_ticket(ticket)

    def mark_external_report_sent(self, ticket_id: str) -> None:
        """Record that a result for this ticket already reached its QQ source.

        Set when ``mcp_robot_send_message`` succeeded during a turn attached
        to this ticket while the workflow was not yet finalizable. Later
        bookkeeping deliveries (e.g. workflow closure after a watchdog
        resume) must not re-send a duplicate report to QQ.
        """
        with self._lock:
            ticket_id = self._resolve_ticket_id_locked(ticket_id)
            ticket = self._tickets.get(ticket_id)
            if not ticket or ticket.external_report_sent:
                return
            ticket.external_report_sent = True
            ticket.updated_at = datetime.now()
            _persist_ticket(ticket)

    def mark_delivered(self, ticket_id: str) -> bool:
        ticket_id = self.resolve_ticket_id(ticket_id)
        try:
            from app.services.agent.task_workflow import task_workflow_manager

            # Hard constraint: if the report already reached the user via
            # the send tool, skip the can_finalize gate and force-close.
            pre_ticket = self.get(ticket_id)
            if not (pre_ticket and pre_ticket.external_report_sent):
                can_finalize, reason = task_workflow_manager.can_finalize(ticket_id)
                if not can_finalize:
                    if task_workflow_manager.complete_final_step_on_delivery(ticket_id):
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

        ticket = self.get(ticket_id)
        if ticket is not None:
            # A delivered conclusion also closes any last-step workflow in this
            # item, even when this ticket was never attached to it.
            task_workflow_manager.complete_last_step_workflow_on_delivery(
                ticket.item_id
            )

        with self._lock:
            ticket = self._tickets.get(ticket_id)
            if not ticket:
                return False
            now = datetime.now()
            ticket.status = "delivered"
            ticket.delivered_at = now
            ticket.updated_at = now
            ticket.delivery_error = ""
            _persist_ticket(ticket)
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
        text = self._sanitize_delivery_text(content)
        if not ticket_id or not text:
            return False
        with self._lock:
            ticket_id = self._resolve_ticket_id_locked(ticket_id)
            ticket = self._tickets.get(ticket_id)
            if not ticket or ticket.status == "delivered":
                return False
            if (
                ticket.external_report_sent
                and ticket.source_type == SOURCE_QQ
                and ticket.status != "failed"
            ):
                # The result already reached QQ via the send tool in an
                # earlier turn. This call is bookkeeping (e.g. workflow
                # closure after a watchdog resume); finalize silently instead
                # of sending a duplicate report. Failure reports (status
                # "failed") always go through.
                return self.mark_delivered(ticket_id)
            ticket.status = "sending"
            ticket.updated_at = datetime.now()
            _persist_ticket(ticket)

        try:
            self._deliver_ticket_content(ticket, text)
        except Exception as exc:
            logger.warning(
                "[ReplyTicket] Failed to deliver ticket=%s source=%s: %s",
                ticket_id,
                ticket.source_label,
                exc,
            )
            with self._lock:
                current = self._tickets.get(ticket_id)
                if current:
                    current.status = "failed"
                    current.delivery_error = str(exc)
                    current.updated_at = datetime.now()
                _persist_ticket(current)
            try:
                from app.services.agent.task_workflow import task_workflow_manager

                task_workflow_manager.mark_delivery_failed(ticket_id, str(exc))
            except Exception:
                pass
            return False

        self.mark_delivered(ticket_id)
        return True

    def _deliver_ticket_content(self, ticket: ReplyTicket, text: str) -> None:
        if ticket.source_type == SOURCE_QQ:
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
            return
        if ticket.source_type == SOURCE_TERMINAL:
            from app.services.socket_pool import InputSDK

            target_player = ticket.terminal_target or ticket.sender_key
            if not target_player:
                raise ValueError("terminal player target is missing")
            if not InputSDK().send(ticket.item_id, f"tell {target_player} {text}\n"):
                raise RuntimeError("terminal command was not accepted")
            return
        if ticket.source_type == SOURCE_WEB:
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
            return
        raise ValueError(f"unsupported destination type: {ticket.source_type}")

    def snapshot(self, item_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self._prune_locked(datetime.now())
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
                    "pending_reply_status": str(
                        (workflow or {}).get("queue_status") or ""
                    ),
                    "pending_reply_requester": str(
                        (workflow or {}).get("requester") or ""
                    ),
                    "pending_reply_plan": [
                        str(step.get("title") or "")
                        for step in (workflow or {}).get("steps") or []
                        if isinstance(step, dict) and step.get("title")
                    ],
                    "pending_reply_awaiting_kind": str(
                        (workflow or {}).get("awaiting_kind") or ""
                    ),
                    "pending_reply_awaiting_key": str(
                        (workflow or {}).get("awaiting_key") or ""
                    ),
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
