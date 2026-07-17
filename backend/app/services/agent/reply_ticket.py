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
TASK_QUEUE_EVENT_TYPE = "task_queue_changed"

TICKET_TTL = timedelta(hours=6)
CURRENT_QQ_MESSAGE_MARKER = "[Current QQ message]"
CQ_CODE_RE = re.compile(r"\[CQ:[^\]]+\]", re.IGNORECASE)


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
            self._remove_aliases_for_locked(ticket_id)

    def reset(self) -> None:
        with self._lock:
            self._tickets.clear()
            self._ticket_aliases.clear()
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

    @staticmethod
    def _destination_key(ticket: ReplyTicket) -> tuple[str, ...]:
        if ticket.source_type == SOURCE_QQ:
            return (
                SOURCE_QQ,
                ticket.robot_id,
                ticket.conversation_key,
            )
        if ticket.source_type == SOURCE_TERMINAL:
            return (
                SOURCE_TERMINAL,
                ticket.terminal_target or ticket.sender_key,
            )
        if ticket.source_type == SOURCE_WEB:
            return (SOURCE_WEB, ticket.item_id)
        return (ticket.source_type, ticket.source_label)

    def _workflow_pending_tickets(self, ticket_id: str) -> list[ReplyTicket]:
        resolved_ticket_id = self.resolve_ticket_id(ticket_id)
        try:
            from app.services.agent.task_workflow import task_workflow_manager

            workflow = task_workflow_manager.get_by_ticket(resolved_ticket_id)
            target_ids = (
                task_workflow_manager.ticket_ids(workflow.workflow_id)
                if workflow
                else [resolved_ticket_id]
            )
        except Exception:
            target_ids = [resolved_ticket_id]

        tickets: list[ReplyTicket] = []
        seen: set[str] = set()
        with self._lock:
            for candidate_id in target_ids:
                current_id = self._resolve_ticket_id_locked(candidate_id)
                if current_id in seen:
                    continue
                candidate = self._tickets.get(current_id)
                if not candidate or not candidate.pending_reply_active:
                    continue
                seen.add(current_id)
                tickets.append(candidate)
        return tickets

    def find_matching_pending_destination(
        self,
        workflow_id: str,
        ticket_id: str,
    ) -> str:
        new_ticket = self.get(ticket_id)
        if not new_ticket:
            return ""
        try:
            from app.services.agent.task_workflow import task_workflow_manager

            target_ids = task_workflow_manager.ticket_ids(workflow_id)
        except Exception:
            return ""
        destination_key = self._destination_key(new_ticket)
        with self._lock:
            for candidate_id in target_ids:
                resolved_id = self._resolve_ticket_id_locked(candidate_id)
                candidate = self._tickets.get(resolved_id)
                if (
                    candidate
                    and candidate.pending_reply_active
                    and self._destination_key(candidate) == destination_key
                ):
                    return candidate.ticket_id
        return ""

    def add_pending_reply_target(
        self,
        ticket_id: str,
        *,
        destination_type: str,
        target_id: str,
        robot_id: str = "",
        target_kind: str = "group",
        label: str = "",
    ) -> dict[str, Any]:
        base_ticket = self.get(ticket_id)
        if not base_ticket or not base_ticket.pending_reply_active:
            raise KeyError("pending reply not found")
        normalized_type = str(destination_type or "").strip().lower()
        normalized_target_id = str(target_id or "").strip()
        if not normalized_target_id:
            raise ValueError("additional target_id is required")

        new_ticket = ReplyTicket(
            ticket_id=uuid.uuid4().hex,
            item_id=base_ticket.item_id,
            handler_id=base_ticket.handler_id,
            source_type=normalized_type,
            source_label=str(label or "").strip(),
            status="running",
            task_request_id=base_ticket.task_request_id,
            request_message=base_ticket.request_message,
            sender_key=normalized_target_id,
            sender_label=str(label or normalized_target_id),
            pending_reply_active=True,
        )
        if normalized_type == SOURCE_QQ:
            normalized_robot_id = str(robot_id or "").strip()
            normalized_kind = str(target_kind or "group").strip().lower()
            if normalized_kind not in {"group", "private"}:
                raise ValueError("QQ target_kind must be group or private")
            if not normalized_robot_id:
                raise ValueError("QQ additional target requires robot_id")
            from app.plugins.robot.contracts import RobotReplyTarget

            conversation_key = f"{normalized_kind}:{normalized_target_id}"
            reply_target = RobotReplyTarget(
                target_type=normalized_kind,
                target_id=normalized_target_id,
                metadata={
                    "conversation": {
                        "type": normalized_kind,
                        "id": normalized_target_id,
                    }
                },
            )
            new_ticket.robot_id = normalized_robot_id
            new_ticket.conversation_key = conversation_key
            new_ticket.reply_target = reply_target.model_dump(mode="json")
            new_ticket.source_label = (
                str(label or "").strip() or f"QQ {conversation_key}"
            )
        elif normalized_type == SOURCE_TERMINAL:
            new_ticket.terminal_target = normalized_target_id
            new_ticket.source_label = (
                str(label or "").strip()
                or f"Minecraft player {normalized_target_id}"
            )
        else:
            raise ValueError("additional target type must be qq or terminal")

        try:
            from app.services.agent.task_workflow import task_workflow_manager

            workflow = task_workflow_manager.get_by_ticket(base_ticket.ticket_id)
        except Exception:
            workflow = None
        if not workflow:
            raise ValueError("pending reply has no task workflow")

        destination_key = self._destination_key(new_ticket)
        for existing in self._workflow_pending_tickets(base_ticket.ticket_id):
            if self._destination_key(existing) == destination_key:
                return self._pending_reply_snapshot(existing)

        with self._lock:
            self._tickets[new_ticket.ticket_id] = new_ticket
        task_workflow_manager.attach_ticket(
            workflow.workflow_id,
            new_ticket.ticket_id,
        )
        self._broadcast_pending_reply_change(new_ticket, action="created")
        return self._pending_reply_snapshot(new_ticket)

    def _workflow_destination_labels(self, ticket_id: str) -> list[str]:
        return [
            self._destination_label(ticket)
            for ticket in self._workflow_pending_tickets(ticket_id)
        ]

    @staticmethod
    def _sanitize_delivery_text(content: Any) -> str:
        try:
            from app.plugins.robot.internal_trace import sanitize_robot_visible_text

            return sanitize_robot_visible_text(content).strip()
        except Exception:
            return str(content or "").strip()

    @staticmethod
    def _broadcast_pending_reply_change(
        ticket: ReplyTicket,
        *,
        action: str,
    ) -> None:
        try:
            from app.services.agent.stream_manager import stream_manager

            stream_manager.broadcast_chat_event(
                ticket.item_id,
                {
                    "type": TASK_QUEUE_EVENT_TYPE,
                    "item_id": ticket.item_id,
                    "entry_id": ticket.ticket_id,
                    "action": action,
                    "timestamp": datetime.now().isoformat(),
                },
            )
        except Exception:
            logger.exception(
                "[ReplyTicket] Failed to broadcast task queue change: ticket=%s action=%s",
                ticket.ticket_id,
                action,
            )

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
        normalized_plan = [
            str(step).strip()[:500]
            for step in (task_plan or [])
            if str(step).strip()
        ][:12]
        with self._lock:
            ticket_id = self._resolve_ticket_id_locked(ticket_id)
            ticket = self._tickets.get(ticket_id)
            if not ticket:
                raise KeyError(f"reply ticket not found: {ticket_id}")
            was_active = ticket.pending_reply_active
            now = datetime.now()
            ticket.pending_reply_active = True
            if request_summary:
                ticket.request_message = str(request_summary)[:500]
            ticket.updated_at = now
            if ticket.status == "delivered":
                ticket.status = "running"

        from app.services.agent.task_workflow import task_workflow_manager

        workflow = task_workflow_manager.get_by_ticket(ticket.ticket_id)
        workflow_created = workflow is None
        if workflow is None:
            workflow = task_workflow_manager.create(
                item_id=ticket.item_id,
                handler_id=ticket.handler_id,
                reply_ticket_id=ticket.ticket_id,
                objective=ticket.request_message or "Complete requested task",
                source_type=ticket.source_type,
                source_label=ticket.source_label,
                step_titles=normalized_plan,
                workflow_id=ticket.task_request_id or None,
            )
            ticket.task_request_id = workflow.workflow_id
        task_workflow_manager.update_queue_metadata(
            ticket.ticket_id,
            requester=(
                requester
                or ticket.sender_label
                or ticket.sender_key
                or ticket.source_label
            ),
            status=status or "working",
            awaiting_kind=awaiting_kind,
            awaiting_key=awaiting_key,
        )
        if workflow_created and str(status or "").lower() == "ready":
            while workflow.status == "active" and workflow.current_step() is not None:
                task_workflow_manager.update(
                    ticket.ticket_id,
                    action="complete_current_step",
                    note="Queue-only task is ready for delivery.",
                )
        snapshot = self._pending_reply_snapshot(ticket)
        self._broadcast_pending_reply_change(
            ticket,
            action="updated" if was_active else "created",
        )
        return snapshot

    def delete_pending_reply(self, ticket_id: str, *, reason: str = "") -> bool:
        tickets = self._workflow_pending_tickets(ticket_id)
        if not tickets:
            return False
        canonical_ticket_id = tickets[0].ticket_id
        with self._lock:
            for ticket in tickets:
                self._tickets.pop(ticket.ticket_id, None)
                self._remove_aliases_for_locked(ticket.ticket_id)
        try:
            from app.services.agent.task_workflow import task_workflow_manager

            task_workflow_manager.update(
                canonical_ticket_id,
                action="cancel",
                note=str(reason or "Pending reply deleted")[:500],
            )
            for ticket in tickets:
                task_workflow_manager.detach_ticket(ticket.ticket_id)
        except Exception:
            pass
        for ticket in tickets:
            self._broadcast_pending_reply_change(ticket, action="removed")
        return True

    def rebind_pending_reply(self, old_ticket_id: str, new_ticket_id: str) -> bool:
        if not old_ticket_id or old_ticket_id == new_ticket_id:
            return True
        with self._lock:
            old_ticket_id = self._resolve_ticket_id_locked(old_ticket_id)
            new_ticket_id = self._resolve_ticket_id_locked(new_ticket_id)
            old_ticket = self._tickets.get(old_ticket_id)
            new_ticket = self._tickets.get(new_ticket_id)
            if not new_ticket:
                return False
            was_active = bool(old_ticket and old_ticket.pending_reply_active)
            if old_ticket:
                self._tickets.pop(old_ticket_id, None)
            for alias, target in list(self._ticket_aliases.items()):
                if self._resolve_ticket_id_locked(target) == old_ticket_id:
                    self._ticket_aliases[alias] = new_ticket_id
            self._ticket_aliases[old_ticket_id] = new_ticket_id
            new_ticket.pending_reply_active = was_active
            new_ticket.status = "running"
            new_ticket.updated_at = datetime.now()
        if was_active:
            try:
                from app.services.agent.task_workflow import task_workflow_manager

                task_workflow_manager.replace_ticket(
                    old_ticket_id,
                    new_ticket_id,
                )
                task_workflow_manager.update_queue_metadata(
                    new_ticket_id,
                    requester=(
                        new_ticket.sender_label
                        or new_ticket.sender_key
                        or new_ticket.source_label
                    ),
                )
            except Exception:
                pass
            if old_ticket:
                self._broadcast_pending_reply_change(old_ticket, action="removed")
            self._broadcast_pending_reply_change(new_ticket, action="created")
        return True

    def complete_pending_reply_after_external_delivery(self, ticket_id: str) -> bool:
        with self._lock:
            ticket_id = self._resolve_ticket_id_locked(ticket_id)
            ticket = self._tickets.get(ticket_id)
            if not ticket or not ticket.pending_reply_active:
                return False
            now = datetime.now()
            ticket.status = "delivered"
            ticket.delivered_at = now
            ticket.updated_at = now
            ticket.delivery_error = ""
            self._tickets.pop(ticket_id, None)
            self._remove_aliases_for_locked(ticket_id)
        try:
            from app.services.agent.task_workflow import task_workflow_manager

            task_workflow_manager.detach_ticket(ticket_id)
            if not self._workflow_pending_tickets(ticket_id):
                task_workflow_manager.on_delivery(ticket_id)
        except Exception:
            logger.exception(
                "[ReplyTicket] Failed to complete workflow after external delivery: ticket=%s",
                ticket_id,
            )
        self._broadcast_pending_reply_change(ticket, action="removed")
        return True

    def _pending_reply_snapshot(self, ticket: ReplyTicket) -> dict[str, Any]:
        workflow = None
        try:
            from app.services.agent.task_workflow import task_workflow_manager

            workflow = task_workflow_manager.snapshot_for_ticket(ticket.ticket_id)
        except Exception:
            pass
        plan = [
            str(step.get("title") or "")
            for step in (workflow or {}).get("steps") or []
            if isinstance(step, dict) and step.get("title")
        ]
        return {
            "id": ticket.ticket_id,
            "item_id": ticket.item_id,
            "requester": str((workflow or {}).get("requester") or "")
            or ticket.sender_label
            or ticket.sender_key
            or ticket.source_label,
            "request_summary": str((workflow or {}).get("objective") or "")
            or ticket.request_message,
            "task_plan": plan,
            "destination_type": ticket.source_type,
            "destination_label": self._destination_label(ticket),
            "status": str((workflow or {}).get("queue_status") or "working"),
            "awaiting_kind": str((workflow or {}).get("awaiting_kind") or ""),
            "awaiting_key": str((workflow or {}).get("awaiting_key") or ""),
            "last_error": ticket.delivery_error,
            "created_at": str((workflow or {}).get("created_at") or "")
            or ticket.created_at.isoformat(),
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

    def list_pending_tasks(self, item_id: str) -> list[dict[str, Any]]:
        entries = self.list_pending_replies(item_id)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            workflow = entry.get("workflow") or {}
            workflow_id = str(workflow.get("workflow_id") or entry["id"])
            grouped.setdefault(workflow_id, []).append(entry)

        tasks: list[dict[str, Any]] = []
        for target_entries in grouped.values():
            target_entries.sort(
                key=lambda entry: str(entry.get("updated_at") or ""),
                reverse=True,
            )
            workflow = target_entries[0].get("workflow") or {}
            primary_id = str(workflow.get("reply_ticket_id") or "")
            primary = next(
                (
                    entry
                    for entry in target_entries
                    if entry.get("id") == primary_id
                ),
                target_entries[0],
            )
            destinations = [
                {
                    "id": entry["id"],
                    "type": entry["destination_type"],
                    "label": entry["destination_label"],
                    "requester": entry["requester"],
                    "status": entry["status"],
                    "last_error": entry.get("last_error") or "",
                }
                for entry in target_entries
            ]
            requesters = list(
                dict.fromkeys(
                    str(entry.get("requester") or "")
                    for entry in target_entries
                    if str(entry.get("requester") or "")
                )
            )
            task = dict(primary)
            task["destinations"] = destinations
            task["destination_type"] = (
                destinations[0]["type"] if len(destinations) == 1 else "multiple"
            )
            task["destination_label"] = " / ".join(
                destination["label"] for destination in destinations
            )
            task["requester"] = " / ".join(requesters)
            task["updated_at"] = max(
                str(entry.get("updated_at") or "") for entry in target_entries
            )
            tasks.append(task)

        tasks.sort(key=lambda task: str(task.get("updated_at") or ""), reverse=True)
        return tasks

    def match_pending_reply(
        self,
        item_id: str,
        current_input: str,
    ) -> dict[str, Any] | None:
        text = str(current_input or "")
        candidates = [
            entry
            for entry in self.list_pending_replies(item_id)
            if str(entry.get("awaiting_key") or "")
        ]
        candidates.sort(key=lambda entry: str(entry.get("created_at") or ""))
        for entry in candidates:
            key = str(entry.get("awaiting_key") or "")
            if entry.get("awaiting_kind") == "minecraft_player":
                if not re.search(
                    rf"<\s*{re.escape(key)}\s*>\s+\S",
                    text,
                    flags=re.IGNORECASE,
                ):
                    continue
            elif key.casefold() not in text.casefold():
                continue
            return entry
        return None

    def build_pending_reply_prompt(
        self,
        item_id: str,
        *,
        current_input: str = "",
        current_ticket_id: str = "",
    ) -> str:
        entries = self.list_pending_replies(item_id)
        if not entries:
            return ""
        selected = next(
            (
                entry
                for entry in entries
                if entry["id"] == str(current_ticket_id or "")
            ),
            None,
        )
        if selected is None and current_input:
            matched = self.match_pending_reply(item_id, current_input)
            if matched:
                selected = next(
                    (entry for entry in entries if entry["id"] == matched["id"]),
                    None,
                )

        if selected is None:
            return "\n".join(
                [
                    f"Background task index: {len(entries)} unfinished task(s).",
                    "The current turn is not linked to any background task. Handle only the "
                    "current message. Do not mention, inspect, resume, update, or deliver a "
                    "background task unless the user explicitly refers to it or a matching "
                    "awaited event is present. Use mcp_local_list_pending_replies only when "
                    "that explicit link exists.",
                ]
            )

        lines = [
            "Authoritative task queue entry for this turn:",
            f"- id={selected['id']}",
            f"- requester={selected['requester']}",
            f"- destination={selected['destination_label']}",
            f"- status={selected['status']}",
            f"- request={selected['request_summary']}",
        ]
        destination_labels = self._workflow_destination_labels(selected["id"])
        if destination_labels:
            lines.append("- destinations=" + " | ".join(destination_labels))
        if selected.get("task_plan"):
            lines.append("- plan=" + " -> ".join(selected["task_plan"]))
        if selected.get("awaiting_kind") or selected.get("awaiting_key"):
            lines.append(
                f"- awaiting={selected.get('awaiting_kind') or 'event'}:"
                f"{selected.get('awaiting_key') or 'unspecified'}"
            )
        lines.extend(
            [
                "Complete or explicitly fail this task, then call "
                "mcp_local_send_pending_reply with this id. Delivery uses the stored immutable "
                "destination and removes the task only after success. A failed delivery keeps "
                "the task for retry.",
            ]
        )
        return "\n".join(lines)

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

    def mark_command(self, ticket_id: str, command: str) -> None:
        with self._lock:
            ticket_id = self._resolve_ticket_id_locked(ticket_id)
            ticket = self._tickets.get(ticket_id)
            if not ticket:
                return
            ticket.command = str(command or "")
            ticket.status = "running"
            ticket.updated_at = datetime.now()

    def mark_completed(self, ticket_id: str) -> None:
        with self._lock:
            ticket_id = self._resolve_ticket_id_locked(ticket_id)
            ticket = self._tickets.get(ticket_id)
            if not ticket:
                return
            if ticket.status != "delivered":
                ticket.status = "completed"
            ticket.updated_at = datetime.now()

    def mark_failed(self, ticket_id: str, error: str = "") -> None:
        with self._lock:
            ticket_id = self._resolve_ticket_id_locked(ticket_id)
            ticket = self._tickets.get(ticket_id)
            if not ticket:
                return
            ticket.status = "failed"
            ticket.delivery_error = str(error or "")
            ticket.updated_at = datetime.now()
            pending_reply_active = ticket.pending_reply_active
        if pending_reply_active:
            try:
                from app.services.agent.task_workflow import task_workflow_manager

                task_workflow_manager.update_queue_metadata(
                    ticket_id,
                    status="failed",
                )
            except Exception:
                pass
            self._broadcast_pending_reply_change(ticket, action="updated")

    def mark_pending_reply_waiting(
        self,
        ticket_id: str,
        *,
        awaiting_kind: str,
        awaiting_key: str = "",
        reason: str = "",
    ) -> bool:
        with self._lock:
            ticket_id = self._resolve_ticket_id_locked(ticket_id)
            ticket = self._tickets.get(ticket_id)
            if not ticket or not ticket.pending_reply_active:
                return False
            ticket.status = "waiting"
            ticket.delivery_error = ""
            ticket.updated_at = datetime.now()

        try:
            from app.services.agent.task_workflow import task_workflow_manager

            if not task_workflow_manager.mark_waiting(
                ticket_id,
                awaiting_kind=awaiting_kind,
                awaiting_key=awaiting_key,
                note=reason,
            ):
                return False
        except Exception:
            logger.exception(
                "[ReplyTicket] Failed to mark pending task waiting: ticket=%s",
                ticket_id,
            )
            return False

        self._broadcast_pending_reply_change(ticket, action="updated")
        return True

    def mark_delivered(self, ticket_id: str) -> bool:
        ticket_id = self.resolve_ticket_id(ticket_id)
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
            ticket = self._tickets.get(ticket_id)
            if not ticket:
                return False
            if ticket.pending_reply_active:
                ticket.status = "running"
                ticket.updated_at = datetime.now()
                ticket.delivery_error = ""
                pending_reply_active = True
            else:
                pending_reply_active = False
                now = datetime.now()
                ticket.status = "delivered"
                ticket.delivered_at = now
                ticket.updated_at = now
                ticket.delivery_error = ""
        if pending_reply_active:
            task_workflow_manager.update_queue_metadata(
                ticket_id,
                status="working",
            )
            self._broadcast_pending_reply_change(ticket, action="updated")
            return True
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
            destination_labels = self._workflow_destination_labels(ticket.ticket_id)
            return (
                "Authoritative task queue entry:\n"
                f"- entry_id: {entry['id']}\n"
                f"- requester: {entry['requester']}\n"
                f"- request: {entry['request_summary']}\n"
                f"- immutable destinations: "
                f"{' | '.join(destination_labels) or entry['destination_label']}\n"
                f"- status: {entry['status']}\n"
                f"- plan: {' -> '.join(entry['task_plan']) or '(not recorded)'}\n"
                f"- awaiting: {entry['awaiting_kind'] or 'none'}:"
                f"{entry['awaiting_key'] or 'none'}\n"
                "- update this entry with mcp_local_write_pending_reply as work changes.\n"
                "- after the task is genuinely complete, call mcp_local_send_pending_reply "
                "with this entry_id. It sends to every immutable destination and deletes the "
                "task only after every target succeeds.\n"
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
        text = self._sanitize_delivery_text(content)
        if not ticket_id or not text:
            return False
        with self._lock:
            ticket_id = self._resolve_ticket_id_locked(ticket_id)
            ticket = self._tickets.get(ticket_id)
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
                current = self._tickets.get(ticket_id)
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

    def _deliver_pending_ticket_content(self, ticket: ReplyTicket, text: str) -> None:
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

    def send_pending_reply(self, ticket_id: str, content: str) -> tuple[bool, str]:
        text = self._sanitize_delivery_text(content)
        if not text:
            return False, "reply content contains no visible text"
        tickets = self._workflow_pending_tickets(ticket_id)
        if not tickets:
            return False, "pending reply not found"
        primary_ticket = next(
            (ticket for ticket in tickets if ticket.ticket_id == self.resolve_ticket_id(ticket_id)),
            tickets[0],
        )

        try:
            from app.services.agent.task_workflow import task_workflow_manager

            can_finalize, reason = task_workflow_manager.can_finalize(
                primary_ticket.ticket_id
            )
            if not can_finalize:
                return False, reason
        except Exception as exc:
            return False, f"failed to validate task workflow: {exc}"

        now = datetime.now()
        with self._lock:
            for ticket in tickets:
                current = self._tickets.get(ticket.ticket_id)
                if current:
                    current.status = "sending"
                    current.delivery_error = ""
                    current.updated_at = now
        task_workflow_manager.update_queue_metadata(
            primary_ticket.ticket_id,
            status="sending",
        )
        for ticket in tickets:
            self._broadcast_pending_reply_change(ticket, action="updated")

        delivered: list[ReplyTicket] = []
        failed: list[tuple[ReplyTicket, str]] = []
        for ticket in tickets:
            try:
                self._deliver_pending_ticket_content(ticket, text)
                delivered.append(ticket)
            except Exception as exc:
                error = str(exc)[:1000]
                failed.append((ticket, error))
                with self._lock:
                    current = self._tickets.get(ticket.ticket_id)
                    if current:
                        current.status = "failed"
                        current.delivery_error = error
                        current.updated_at = datetime.now()
                self._broadcast_pending_reply_change(ticket, action="updated")

        for ticket in delivered:
            with self._lock:
                self._tickets.pop(ticket.ticket_id, None)
                self._remove_aliases_for_locked(ticket.ticket_id)
            task_workflow_manager.detach_ticket(ticket.ticket_id)
            self._broadcast_pending_reply_change(ticket, action="removed")

        if failed:
            failure_summary = "; ".join(
                f"{self._destination_label(ticket)}: {error}"
                for ticket, error in failed
            )
            task_workflow_manager.mark_delivery_failed(
                failed[0][0].ticket_id,
                failure_summary,
            )
            task_workflow_manager.update_queue_metadata(
                failed[0][0].ticket_id,
                status="failed",
            )
            return False, failure_summary

        task_workflow_manager.on_delivery(primary_ticket.ticket_id)
        destinations = " / ".join(
            self._destination_label(ticket) for ticket in delivered
        )
        return True, destinations

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
