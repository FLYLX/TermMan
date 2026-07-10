from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from app.plugins.robot import is_robot_plugin_enabled
from app.plugins.robot.internal_trace import (
    NO_QQ_REPLY_MARKER,
    compact_robot_visible_message_text,
    is_robot_internal_trace_text,
    sanitize_robot_visible_text,
)
from app.plugins.robot.mcp.context import (
    RobotMCPContext,
    build_robot_reply_context_summary,
    extract_robot_context_targets_from_text,
    register_robot_mcp_context,
    unregister_robot_mcp_context,
)
from app.plugins.robot.reply_intent import is_no_reply_intent

if TYPE_CHECKING:
    from app.plugins.robot.contracts import RobotReplyTarget
    from app.services.agent.agent import Agent
    from app.services.agent.skills.definition import SkillDefinition

logger = logging.getLogger(__name__)

ROBOT_MCP_SERVER_NAME = "robot"
ROBOT_SEND_TOOL_NAME = "mcp_robot_send_message"
QQ_MCP_SKILL_ID = "qq_mcp"
ROBOT_MESSAGING_SKILL_ID = "robot_messaging"
ROBOT_MESSAGING_COMPAT_SKILL_IDS = {QQ_MCP_SKILL_ID, ROBOT_MESSAGING_SKILL_ID}
ROBOT_MESSAGE_STAMP_RE = re.compile(r"\[Robot message; (?P<body>[^\]]+)\]")


def _has_tool(tools: list[dict[str, Any]], tool_name: str) -> bool:
    return any(tool.get("function", {}).get("name") == tool_name for tool in tools)


def _robot_context(agent: Agent) -> Any:
    return getattr(agent, "_context", None)


def _robot_conversation_key(reply_target: RobotReplyTarget, sender_key: str) -> str:
    metadata = reply_target.metadata if reply_target else {}
    conversation = metadata.get("conversation") if isinstance(metadata, dict) else {}
    if isinstance(conversation, dict):
        conversation_type = str(conversation.get("type") or "").strip().lower()
        conversation_id = str(conversation.get("id") or "").strip()
        if conversation_type and conversation_id:
            return f"{conversation_type}:{conversation_id}"

    summary = build_robot_reply_context_summary(reply_target, sender_key)
    match = re.search(r"^- conversation:\s*(.+)$", summary, flags=re.MULTILINE)
    if match:
        return match.group(1).strip()
    return sender_key


def _is_robot_send_tool_result(value: str) -> bool:
    return is_robot_internal_trace_text(value)


def _parse_robot_message_stamp_body(body: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for part in body.split(";"):
        key, separator, value = part.strip().partition("=")
        if not separator:
            continue
        normalized_key = key.strip().lower()
        normalized_value = value.strip()
        if normalized_key and normalized_value:
            parsed[normalized_key] = normalized_value
    return parsed


def _robot_message_conversation_key(content: str) -> str:
    match = ROBOT_MESSAGE_STAMP_RE.search(content or "")
    if not match:
        return ""
    stamp = _parse_robot_message_stamp_body(match.group("body"))
    return stamp.get("conversation", "").strip()


def _event_is_assistant_context(event: dict[str, Any]) -> bool:
    return event.get("role") == "assistant" or event.get("type") in {
        "agent_action",
        "agent_tool_result",
        "agent_response",
        "agent_warning",
        "agent_error",
    }


def _reply_target_is_direct_wakeup(robot_reply_target: RobotReplyTarget | None) -> bool:
    if robot_reply_target is None:
        return False

    metadata = robot_reply_target.metadata
    return bool(metadata.get("mentioned_bot") or metadata.get("replied_to_bot"))


def _int_context_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _should_send_final_response_fallback(
    *,
    robot_id: str | None,
    robot_reply_target: RobotReplyTarget | None,
    content: str,
    robot_message_sent: bool,
    reply_requires_awake: bool = False,
) -> bool:
    return (
        bool(robot_id)
        and robot_reply_target is not None
        and bool(content.strip())
        and not robot_message_sent
        and (
            _reply_target_is_direct_wakeup(robot_reply_target)
            or reply_requires_awake
        )
    )


class RobotAgentIntegration:
    name = "robot"

    def build_system_prompt(self, agent: Agent) -> str:
        from app.plugins.robot.prompts import build_robot_context_prompt

        return build_robot_context_prompt(agent)

    def build_history_prompt(
        self,
        agent: Agent,
        *,
        message: str,
        context_messages: list[dict[str, str]],
    ) -> str:
        has_robot_context = "[Robot message;" in message or any(
            "[Robot message;" in context_message.get("content", "")
            for context_message in context_messages
        )
        if not has_robot_context:
            return ""

        from app.plugins.robot.prompts import build_robot_history_prompt

        return build_robot_history_prompt(agent, has_robot_context=has_robot_context)

    def history_scope_key(self, agent: Agent) -> str:
        context = _robot_context(agent)
        if context is None:
            return ""
        return str(getattr(context, "robot_conversation_key", "") or "").strip()

    def annotate_history_events(
        self,
        events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        annotated_events: list[dict[str, Any]] = []
        active_robot_conversation = ""

        for event in events:
            content = str(event.get("content", ""))
            if _event_is_assistant_context(event):
                sanitized_content = sanitize_robot_visible_text(content)
                if not sanitized_content:
                    continue
                if sanitized_content != content.strip():
                    event = {**event, "content": sanitized_content}
                    content = sanitized_content

            event_conversation = _robot_message_conversation_key(content)
            associated_conversation = ""

            if event_conversation:
                active_robot_conversation = event_conversation
                associated_conversation = event_conversation
            elif "[Robot message;" in content:
                active_robot_conversation = ""
                associated_conversation = "__unknown_robot_conversation__"
            elif _event_is_assistant_context(event):
                associated_conversation = active_robot_conversation
            elif event.get("role") in {"user", "terminal"} or event.get("type") in {
                "chat_user",
                "terminal_output",
            }:
                active_robot_conversation = ""

            if associated_conversation:
                event = {**event, "_integration_robot_conversation_key": associated_conversation}
            annotated_events.append(event)

        return annotated_events

    def history_event_matches_scope(
        self,
        event: dict[str, Any],
        scope_key: str,
    ) -> bool:
        if not scope_key:
            return True

        associated_conversation = str(
            event.get("_integration_robot_conversation_key", "") or ""
        ).strip()
        if associated_conversation:
            return associated_conversation == scope_key

        content = str(event.get("content", ""))
        event_conversation = _robot_message_conversation_key(content)
        if event_conversation:
            return event_conversation == scope_key
        if "[Robot message;" in content:
            return False
        return True

    def extract_context_targets(
        self,
        agent: Agent,
        messages: list[dict[str, Any]],
    ) -> None:
        context = _robot_context(agent)
        if context is None:
            return

        targets_by_key: dict[str, dict[str, str]] = {}
        for message in messages:
            content = message.get("content") if isinstance(message, dict) else ""
            if not isinstance(content, str):
                continue
            for target in extract_robot_context_targets_from_text(content):
                target_data = dict(target)
                if getattr(context, "robot_id", "") and not target_data.get("robot_id"):
                    target_data["robot_id"] = context.robot_id
                key = f"{target_data.get('target_type')}:{target_data.get('target_id')}"
                targets_by_key[key] = target_data

        context.robot_known_targets = list(targets_by_key.values())

    def record_context_targets(self, agent: Agent, item_id: str) -> None:
        context = _robot_context(agent)
        if context is None:
            return

        targets = getattr(context, "robot_known_targets", None) or []
        if not targets:
            return

        robot_ids = {
            str(target.get("robot_id") or "").strip()
            for target in targets
            if isinstance(target, dict) and str(target.get("robot_id") or "").strip()
        }
        if not robot_ids and getattr(context, "robot_id", ""):
            robot_ids.add(str(context.robot_id))

        if not robot_ids:
            return

        from app.plugins.robot.debug_log import record_robot_event

        payload_targets = [
            {
                "conversation": target.get("conversation"),
                "target_type": target.get("target_type"),
                "target_id": target.get("target_id"),
                "sender": target.get("sender"),
            }
            for target in targets
            if isinstance(target, dict)
        ]
        for robot_id in robot_ids:
            record_robot_event(
                robot_id,
                direction="agent_internal",
                event="robot_context_targets",
                message=f"{len(payload_targets)} QQ context target(s)",
                payload={
                    "item_id": item_id,
                    "targets": payload_targets,
                },
            )

    def setup_chat_context(self, agent: Agent, context: dict[str, Any]) -> bool:
        agent_context = _robot_context(agent)
        if agent_context is None:
            return False

        robot_id = str(context.get("robot_id") or "").strip()
        sender_key = str(context.get("sender_key") or "").strip()
        reply_target = context.get("reply_target")
        if not robot_id or not sender_key or reply_target is None:
            return False

        self.clear_chat_context(agent, context)
        conversation_key = str(context.get("conversation_key") or "").strip()
        if not conversation_key:
            conversation_key = _robot_conversation_key(reply_target, sender_key)
        conversation_generation = _int_context_value(context.get("conversation_generation"))
        reply_requires_awake = bool(context.get("reply_requires_awake"))
        mcp_context = RobotMCPContext(
            robot_id=robot_id,
            sender_key=sender_key,
            reply_target=reply_target.model_copy(deep=True),
            conversation_key=conversation_key,
            conversation_generation=conversation_generation,
            reply_requires_awake=reply_requires_awake,
        )
        agent_context.robot_id = robot_id
        agent_context.robot_sender_key = sender_key
        agent_context.robot_conversation_key = conversation_key
        agent_context.robot_context_token = register_robot_mcp_context(mcp_context)
        agent_context.robot_reply_context_summary = build_robot_reply_context_summary(
            reply_target,
            sender_key,
        )
        agent_context.robot_mcp_server_transient = False
        return True

    async def ensure_chat_context_tools(
        self,
        agent: Agent,
        context: dict[str, Any],
    ) -> bool:
        agent_context = _robot_context(agent)
        if agent_context is None or not getattr(agent_context, "robot_id", ""):
            return False
        return await self._ensure_messaging_tools(agent)

    def clear_chat_context(self, agent: Agent, context: dict[str, Any]) -> None:
        agent_context = _robot_context(agent)
        if agent_context is None:
            return

        should_remove_robot_mcp = bool(getattr(agent_context, "robot_mcp_server_transient", False))
        unregister_robot_mcp_context(getattr(agent_context, "robot_context_token", ""))
        agent_context.robot_id = ""
        agent_context.robot_sender_key = ""
        agent_context.robot_conversation_key = ""
        agent_context.robot_context_token = ""
        agent_context.robot_reply_context_summary = ""
        agent_context.robot_mcp_server_transient = False
        if should_remove_robot_mcp and ROBOT_MCP_SERVER_NAME in agent._mcp_servers:
            agent._mcp_servers = [
                server_name
                for server_name in agent._mcp_servers
                if server_name != ROBOT_MCP_SERVER_NAME
            ]
            agent._load_mcp_tools()

    def inject_tool_args(
        self,
        agent: Agent,
        *,
        server_name: str,
        tool_name: str,
        args: dict[str, Any],
    ) -> None:
        if server_name != ROBOT_MCP_SERVER_NAME:
            return

        args.pop("_robot_context_token", None)
        args.pop("_termman_user_id", None)
        args.pop("_termman_is_superuser", None)
        args.pop("_termman_item_id", None)
        args.pop("_robot_known_targets", None)

        context = _robot_context(agent)
        if context is None:
            return

        if getattr(context, "current_user_id", ""):
            args["_termman_user_id"] = context.current_user_id
            args["_termman_is_superuser"] = context.current_user_is_superuser
        if getattr(context, "item_id", ""):
            args["_termman_item_id"] = context.item_id
        if getattr(context, "robot_known_targets", None):
            args["_robot_known_targets"] = [
                dict(target) for target in context.robot_known_targets
            ]
        if getattr(context, "robot_id", "") and getattr(context, "robot_context_token", ""):
            args["_robot_context_token"] = context.robot_context_token

    def should_retry_delivery(
        self,
        agent: Agent,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        final_response: str,
        retry_used: bool,
    ) -> bool:
        return (
            bool(final_response.strip())
            and not retry_used
            and not is_no_reply_intent(final_response)
            and _has_tool(tools, ROBOT_SEND_TOOL_NAME)
            and self._has_delivery_context(agent, messages)
        )

    def delivery_correction_message(self, final_response: str) -> dict[str, str]:
        from app.plugins.robot.prompts import build_robot_delivery_reflection_prompt

        reflection_prompt = build_robot_delivery_reflection_prompt(final_response)
        if reflection_prompt:
            return {"role": "system", "content": reflection_prompt}

        return {
            "role": "system",
            "content": (
                "Robot message delivery reflection:\n"
                "You produced a final assistant response without calling "
                "`mcp_robot_send_message`:\n"
                f"{final_response.strip()}\n\n"
                "Re-evaluate whether QQ should receive that text. If it should, "
                "call `mcp_robot_send_message` now using the QQ conversation "
                "visible in context. If not, respond with a concise internal note "
                "explaining that no QQ message was sent. Do not output the "
                "reflection itself."
            ),
        }

    def record_delivery_correction(
        self,
        agent: Agent,
        item_id: str,
        final_response: str,
    ) -> None:
        context = _robot_context(agent)
        if context is None:
            return

        robot_ids = {
            str(target.get("robot_id") or "").strip()
            for target in getattr(context, "robot_known_targets", []) or []
            if isinstance(target, dict) and str(target.get("robot_id") or "").strip()
        }
        if not robot_ids and getattr(context, "robot_id", ""):
            robot_ids.add(str(context.robot_id))

        if not robot_ids:
            return

        from app.plugins.robot.debug_log import preview_text, record_robot_event

        for robot_id in robot_ids:
            record_robot_event(
                robot_id,
                direction="agent_internal",
                event="robot_delivery_correction",
                message=preview_text(final_response),
                payload={
                    "item_id": item_id,
                    "reason": "plain_final_response_without_robot_tool_call",
                },
            )

    def is_delivery_tool_result(self, value: str) -> bool:
        return _is_robot_send_tool_result(value)

    def fallback_response_content(
        self,
        context: dict[str, Any],
        *,
        tool_results: list[str],
        warnings: list[str],
        done_seen: bool,
    ) -> str:
        if not context.get("robot_id"):
            return ""

        for result in reversed(tool_results):
            normalized = result.strip()
            if _is_robot_send_tool_result(normalized):
                return normalized

        for result in reversed(tool_results):
            if result.strip():
                return result.strip()

        for warning in reversed(warnings):
            if warning.strip():
                return warning.strip()

        if done_seen:
            return NO_QQ_REPLY_MARKER
        return ""

    def record_no_final_response(
        self,
        context: dict[str, Any],
        *,
        fallback_content: str,
        tool_results: list[str],
        warnings: list[str],
    ) -> None:
        robot_id = str(context.get("robot_id") or "").strip()
        if not robot_id:
            return

        from app.plugins.robot.debug_log import preview_text, record_robot_event

        record_robot_event(
            robot_id,
            direction="agent_internal",
            event="agent_no_final_response",
            message=preview_text(fallback_content),
            payload={
                "tool_result_count": len(tool_results),
                "warning_count": len(warnings),
                "used_fallback": bool(fallback_content),
            },
        )

    def send_final_response_fallback(
        self,
        context: dict[str, Any],
        *,
        content: str,
        message_sent: bool,
    ) -> bool:
        robot_id = str(context.get("robot_id") or "").strip()
        robot_reply_target = context.get("reply_target")
        raw_content = str(content or "").strip()
        text = compact_robot_visible_message_text(sanitize_robot_visible_text(raw_content))
        if not text:
            if robot_id and is_no_reply_intent(raw_content):
                from app.plugins.robot.debug_log import preview_text, record_robot_event

                record_robot_event(
                    robot_id,
                    direction="agent_internal",
                    event="agent_final_response_no_qq_reply",
                    message=preview_text(raw_content),
                    payload={"reason": "no_reply_intent"},
                )
            return False
        if raw_content == text and is_no_reply_intent(text):
            if robot_id:
                from app.plugins.robot.debug_log import preview_text, record_robot_event

                record_robot_event(
                    robot_id,
                    direction="agent_internal",
                    event="agent_final_response_no_qq_reply",
                    message=preview_text(raw_content),
                    payload={"reason": "no_reply_intent"},
                )
            return False
        reply_requires_awake = bool(context.get("reply_requires_awake"))
        if not _should_send_final_response_fallback(
            robot_id=robot_id,
            robot_reply_target=robot_reply_target,
            content=text,
            robot_message_sent=message_sent,
            reply_requires_awake=reply_requires_awake,
        ):
            return False

        conversation_key = str(context.get("conversation_key") or "").strip()
        if not conversation_key:
            conversation_key = _robot_conversation_key(
                robot_reply_target,
                str(context.get("sender_key") or "").strip(),
            )
        conversation_generation = _int_context_value(context.get("conversation_generation"))
        if reply_requires_awake:
            from app.plugins.robot.debug_log import preview_text, record_robot_event
            from app.plugins.robot.service import robot_service

            if not robot_service.conversation_controller_allows_reply(
                robot_id,
                conversation_key,
                conversation_generation,
                requires_awake=True,
            ):
                record_robot_event(
                    robot_id,
                    direction="agent_internal",
                    event="agent_final_response_dropped_sleeping_conversation",
                    message=preview_text(text),
                    payload={
                        "conversation": conversation_key,
                        "generation": conversation_generation,
                    },
                )
                return False

        from app.plugins.robot.bridge_client import robot_bridge_client

        self._record_final_response_fallback(
            robot_id,
            robot_reply_target=robot_reply_target,
            content=text,
        )
        robot_bridge_client.send_message(robot_id, robot_reply_target, text)
        try:
            from app.plugins.robot.conversation_memory import (
                conversation_key_from_reply_target,
                robot_conversation_memory,
            )

            robot_conversation_memory.append_assistant_message(
                robot_id,
                conversation_key_from_reply_target(robot_reply_target),
                text,
            )
        except Exception as exc:
            logger.warning("[RobotIntegration] Failed to write conversation memory: %s", exc)
        return True

    def should_enable_for_terminal_alert(self, agent: Agent, content: str) -> bool:
        context = _robot_context(agent)
        if context is None:
            return False
        return (
            bool(
                ROBOT_MESSAGING_COMPAT_SKILL_IDS.intersection(
                    set(getattr(context, "enabled_skills", []) or [])
                )
            )
            or ROBOT_MCP_SERVER_NAME in set(getattr(context, "enabled_mcp_servers", []) or [])
        )

    async def ensure_terminal_alert_tools(self, agent: Agent, content: str) -> bool:
        if not self.should_enable_for_terminal_alert(agent, content):
            return False
        return await self._ensure_messaging_tools(agent)

    def clear_terminal_alert_tools(self, agent: Agent) -> None:
        context = _robot_context(agent)
        if context is None or not getattr(context, "robot_mcp_server_transient", False):
            return
        if getattr(context, "robot_id", ""):
            return

        context.robot_mcp_server_transient = False
        if ROBOT_MCP_SERVER_NAME in agent._mcp_servers:
            agent._mcp_servers = [
                server_name
                for server_name in agent._mcp_servers
                if server_name != ROBOT_MCP_SERVER_NAME
            ]
            agent._load_mcp_tools()

    def builtin_skill_definitions(self) -> list[SkillDefinition]:
        from app.plugins.robot.prompts import build_robot_messaging_skill_definition

        skill = build_robot_messaging_skill_definition()
        return [skill] if skill is not None else []

    def builtin_mcp_server_factories(self) -> dict[str, Any]:
        def factory() -> Any:
            from app.plugins.robot.mcp.server import RobotMCPServer

            return RobotMCPServer()

        return {ROBOT_MCP_SERVER_NAME: factory}

    async def _ensure_messaging_tools(self, agent: Agent) -> bool:
        from app.services.agent.mcp.server_manager import mcp_server_manager

        context = _robot_context(agent)
        if context is None:
            return False

        added_transient = False
        if ROBOT_MCP_SERVER_NAME not in agent._mcp_servers:
            agent._mcp_servers.append(ROBOT_MCP_SERVER_NAME)
            context.robot_mcp_server_transient = True
            added_transient = True

        if not mcp_server_manager.is_server_running(ROBOT_MCP_SERVER_NAME):
            started = await mcp_server_manager.start_server(ROBOT_MCP_SERVER_NAME)
            if not started:
                logger.warning(
                    "[RobotIntegration] Robot MCP server is not available for handler %s",
                    agent.handler_id,
                )
                return False

        agent._load_mcp_tools()
        return added_transient

    def _has_delivery_context(
        self,
        agent: Agent,
        messages: list[dict[str, Any]],
    ) -> bool:
        context = _robot_context(agent)
        if context is not None:
            if getattr(context, "robot_id", ""):
                return True
            if getattr(context, "robot_known_targets", None):
                return True

        return any(
            isinstance(message.get("content"), str)
            and "[Robot message;" in message.get("content", "")
            for message in messages
        )

    def _record_final_response_fallback(
        self,
        robot_id: str | None,
        *,
        robot_reply_target: RobotReplyTarget,
        content: str,
    ) -> None:
        if not robot_id:
            return

        from app.plugins.robot.debug_log import preview_text, record_robot_event

        metadata = robot_reply_target.metadata
        record_robot_event(
            robot_id,
            direction="agent_internal",
            event="agent_final_response_bridge_fallback",
            message=preview_text(content),
            payload={
                "target_type": robot_reply_target.target_type,
                "target_id": robot_reply_target.target_id,
                "mentioned_bot": bool(metadata.get("mentioned_bot")),
                "replied_to_bot": bool(metadata.get("replied_to_bot")),
            },
        )


def get_robot_agent_integration() -> RobotAgentIntegration:
    return RobotAgentIntegration()


def register_robot_agent_integration() -> None:
    if not is_robot_plugin_enabled():
        return
    from app.services.agent.integrations.registry import (
        register_agent_integration as register_core_agent_integration,
    )

    register_core_agent_integration(get_robot_agent_integration())


def register_agent_integration() -> None:
    register_robot_agent_integration()


__all__ = [
    "ROBOT_MCP_SERVER_NAME",
    "ROBOT_MESSAGING_SKILL_ID",
    "QQ_MCP_SKILL_ID",
    "ROBOT_SEND_TOOL_NAME",
    "RobotAgentIntegration",
    "get_robot_agent_integration",
    "register_agent_integration",
    "register_robot_agent_integration",
    "_is_robot_send_tool_result",
    "_should_send_final_response_fallback",
]
