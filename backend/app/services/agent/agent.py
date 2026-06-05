from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.models import ItemHandler
from app.services.agent.mcp.robot_context import (
    RobotMCPContext,
    build_robot_reply_context_summary,
    extract_robot_context_targets_from_text,
    register_robot_mcp_context,
    unregister_robot_mcp_context,
)
from app.services.agent.mcp.server_manager import mcp_server_manager
from app.services.agent.skills.definition import SkillDefinition
from app.services.agent.skills.loader import skill_loader
from app.services.filters.output_filter import OutputFilter, OutputFilterConfig

if TYPE_CHECKING:
    from app.models import Item
    from app.plugins.robot.contracts import RobotReplyTarget
    from app.services.agent.mcp.types import MCPTool

logger = logging.getLogger(__name__)

ROBOT_MCP_SERVER_NAME = "robot"


@dataclass
class AgentContext:
    handler_id: str
    item_id: str = ""
    model: str | None = None
    api_key: str | None = None
    api_url: str | None = None
    enabled_skills: list[str] = field(default_factory=list)
    enabled_mcp_servers: list[str] = field(default_factory=list)
    enabled_knowledge_files: list[str] = field(default_factory=list)
    output_filter_enabled: bool = False
    output_filter_rules: dict = field(default_factory=dict)
    robot_id: str = ""
    robot_sender_key: str = ""
    robot_context_token: str = ""
    robot_reply_context_summary: str = ""
    robot_mcp_server_transient: bool = False
    current_user_id: str = ""
    current_user_is_superuser: bool = False
    robot_known_targets: list[dict[str, str]] = field(default_factory=list)


class Agent:
    _instances: dict[str, Agent] = {}

    def __new__(cls, handler_id: str):
        if handler_id in cls._instances:
            return cls._instances[handler_id]
        instance = super().__new__(cls)
        cls._instances[handler_id] = instance
        return instance

    def __init__(self, handler_id: str):
        if hasattr(self, "_initialized") and self._initialized:
            return

        self._initialized = True
        self.handler_id = handler_id
        self._context: AgentContext | None = None
        self._skills: dict[str, SkillDefinition] = {}
        self._mcp_servers: list[str] = []
        self._mcp_tools: list[dict] = []
        self._mcp_tools_raw: list[MCPTool] = []
        logger.info(f"[Agent] Created agent for handler {handler_id}")

    @classmethod
    def from_handler(cls, handler: ItemHandler) -> Agent:
        agent = cls(str(handler.id))
        agent._context = AgentContext(
            handler_id=str(handler.id),
            model=handler.model,
            api_key=handler.api_key,
            api_url=handler.api_url,
            enabled_skills=handler.enabled_skills or [],
            enabled_mcp_servers=handler.enabled_mcp_servers or [],
            enabled_knowledge_files=handler.enabled_knowledge_files or [],
        )
        agent._load_skills()
        return agent

    def _load_skills(self):
        self._skills.clear()
        self._mcp_servers.clear()
        self._mcp_tools.clear()
        self._mcp_tools_raw.clear()

        if self._context:
            if self._context.enabled_mcp_servers:
                for server_name in self._context.enabled_mcp_servers:
                    if server_name not in self._mcp_servers:
                        self._mcp_servers.append(server_name)
                        logger.info(f"[Agent] Added MCP server from handler config: {server_name}")

            if self._context.enabled_skills:
                for skill_id in self._context.enabled_skills:
                    skill = skill_loader.get(skill_id)
                    if skill:
                        self._skills[skill_id] = skill
                        if skill.mcp_servers:
                            for server_name in skill.mcp_servers:
                                if server_name not in self._mcp_servers:
                                    self._mcp_servers.append(server_name)
                                    logger.info(f"[Agent] Added MCP server from skill '{skill_id}': {server_name}")
                    else:
                        logger.warning(f"[Agent] Skill '{skill_id}' not found")

        self._load_mcp_tools()

        logger.info(f"[Agent] Loaded {len(self._skills)} skills, {len(self._mcp_servers)} MCP servers ({self._mcp_servers}), {len(self._mcp_tools)} tools for handler {self.handler_id}")

    def _load_mcp_tools(self):
        self._mcp_tools.clear()
        self._mcp_tools_raw.clear()
        seen_tool_names: set[str] = set()

        for server_name in self._mcp_servers:
            tools = mcp_server_manager.get_tools_for_server(server_name)
            logger.info(f"[Agent] Got {len(tools)} tools from server '{server_name}'")
            for tool in tools:
                full_tool_name = f"mcp_{tool.server_name}_{tool.name}"
                if full_tool_name in seen_tool_names:
                    continue
                seen_tool_names.add(full_tool_name)
                self._mcp_tools_raw.append(tool)
                self._mcp_tools.append(tool.to_litellm_tool())

    @property
    def enabled_knowledge_files(self) -> list[str]:
        if not self._context:
            return []
        return self._context.enabled_knowledge_files

    async def start_mcp_servers(self):
        running_servers: list[str] = []
        for server_name in self._mcp_servers:
            if mcp_server_manager.is_server_running(server_name):
                running_servers.append(server_name)
            else:
                logger.warning(f"[Agent] MCP server '{server_name}' not running")

        if not running_servers:
            return

        self._load_mcp_tools()
        for server_name in running_servers:
            tools_count = len(
                [
                    t
                    for t in self._mcp_tools
                    if t.get("function", {}).get("name", "").startswith(f"mcp_{server_name}_")
                ]
            )
            logger.info(f"[Agent] MCP server '{server_name}' running, loaded {tools_count} tools")

    def set_item_context(self, item_id: str, item: Item | None = None):
        if self._context:
            self._context.item_id = item_id
            if item:
                self._context.output_filter_enabled = item.output_filter_enabled
                self._context.output_filter_rules = item.output_filter_rules or {}

    def set_user_context(self, user_id: str, is_superuser: bool = False) -> None:
        if self._context:
            self._context.current_user_id = user_id
            self._context.current_user_is_superuser = is_superuser

    def set_robot_known_targets_from_messages(self, messages: list[dict]) -> None:
        if not self._context:
            return

        targets_by_key: dict[str, dict[str, str]] = {}
        for message in messages:
            content = message.get("content") if isinstance(message, dict) else ""
            if not isinstance(content, str):
                continue
            for target in extract_robot_context_targets_from_text(content):
                target_data = dict(target)
                if self._context.robot_id and not target_data.get("robot_id"):
                    target_data["robot_id"] = self._context.robot_id
                key = f"{target_data.get('target_type')}:{target_data.get('target_id')}"
                targets_by_key[key] = target_data

        self._context.robot_known_targets = list(targets_by_key.values())

    def set_robot_context(
        self,
        *,
        robot_id: str,
        sender_key: str,
        reply_target: RobotReplyTarget,
    ) -> None:
        if self._context:
            self.clear_robot_context()
            context = RobotMCPContext(
                robot_id=robot_id,
                sender_key=sender_key,
                reply_target=reply_target.model_copy(deep=True),
            )
            self._context.robot_id = robot_id
            self._context.robot_sender_key = sender_key
            self._context.robot_context_token = register_robot_mcp_context(context)
            self._context.robot_reply_context_summary = (
                build_robot_reply_context_summary(reply_target, sender_key)
            )
            self._context.robot_mcp_server_transient = False

    async def ensure_robot_context_tools(self) -> None:
        if not self._context or not self._context.robot_id:
            return

        if ROBOT_MCP_SERVER_NAME not in self._mcp_servers:
            self._mcp_servers.append(ROBOT_MCP_SERVER_NAME)
            self._context.robot_mcp_server_transient = True

        if not mcp_server_manager.is_server_running(ROBOT_MCP_SERVER_NAME):
            started = await mcp_server_manager.start_server(ROBOT_MCP_SERVER_NAME)
            if not started:
                logger.warning(
                    "[Agent] Robot MCP server is not available for handler %s",
                    self.handler_id,
                )
                return

        self._load_mcp_tools()

    def clear_robot_context(self) -> None:
        if self._context:
            should_remove_robot_mcp = self._context.robot_mcp_server_transient
            unregister_robot_mcp_context(self._context.robot_context_token)
            self._context.robot_id = ""
            self._context.robot_sender_key = ""
            self._context.robot_context_token = ""
            self._context.robot_reply_context_summary = ""
            self._context.robot_mcp_server_transient = False
            if should_remove_robot_mcp and ROBOT_MCP_SERVER_NAME in self._mcp_servers:
                self._mcp_servers = [
                    server_name
                    for server_name in self._mcp_servers
                    if server_name != ROBOT_MCP_SERVER_NAME
                ]
                self._load_mcp_tools()

    def _get_output_filter(self) -> OutputFilter | None:
        if not self._context or not self._context.output_filter_enabled:
            return None

        from app.services.filters.output_filter import FilterRule

        filters = []
        for filter_name, filter_config in self._context.output_filter_rules.items():
            if isinstance(filter_config, dict):
                filter_rule = FilterRule(
                    name=filter_name,
                    regex_patterns=filter_config.get("regex_patterns", []),
                    action_type=filter_config.get("action_type", "ignore"),
                    replace_rules=filter_config.get("action", {}).get("replace_rules", {}),
                )
                filters.append(filter_rule)

        config = OutputFilterConfig(enabled=True, filters=filters)
        return OutputFilter(config)

    def get_skills(self) -> list[SkillDefinition]:
        return list(self._skills.values())

    def reload_skills(self):
        self._load_skills()

    def refresh_from_handler(self, handler: ItemHandler):
        if self._context is None:
            self._context = AgentContext(handler_id=str(handler.id))

        self._context.model = handler.model
        self._context.api_key = handler.api_key
        self._context.api_url = handler.api_url
        self._context.enabled_skills = handler.enabled_skills or []
        self._context.enabled_mcp_servers = handler.enabled_mcp_servers or []
        self._context.enabled_knowledge_files = handler.enabled_knowledge_files or []
        self._load_skills()

    def update_skills(self, enabled_skills: list[str]):
        skill_loader.reload()
        if self._context:
            self._context.enabled_skills = enabled_skills
        self._load_skills()

    def update_mcp_servers(self, enabled_mcp_servers: list[str]):
        if self._context:
            self._context.enabled_mcp_servers = enabled_mcp_servers
        self._load_skills()

    def match_skills(self, query: str) -> list[SkillDefinition]:
        matched = []
        query_lower = query.lower()

        for skill in self._skills.values():
            if skill.trigger and skill.trigger.patterns:
                for pattern in skill.trigger.patterns:
                    try:
                        if re.search(pattern, query_lower):
                            matched.append(skill)
                            break
                    except re.error:
                        if pattern.lower() in query_lower:
                            matched.append(skill)
                            break
            else:
                keywords = [skill.skill_id.lower(), skill.name.lower()]
                if skill.description:
                    keywords.extend(skill.description.lower().split())
                for kw in keywords:
                    if kw in query_lower:
                        matched.append(skill)
                    break

        return matched

    def get_mcp_servers(self) -> list[str]:
        return self._mcp_servers.copy()

    def get_skip_memory_tools(self) -> list[str]:
        return [
            f"mcp_{tool.server_name}_{tool.name}"
            for tool in self._mcp_tools_raw
            if tool.skip_memory
        ]

    def get_tools_for_litellm(self) -> list[dict]:
        return self._mcp_tools.copy()

    async def execute_tool(self, tool_name: str, args: dict) -> dict:
        if not tool_name.startswith("mcp_"):
            return {"success": False, "error": f"Tool '{tool_name}' is not an MCP tool"}

        parts = tool_name.split("_", 2)
        if len(parts) < 3:
            return {"success": False, "error": f"Invalid MCP tool name: {tool_name}"}

        server_name = parts[1]
        actual_tool_name = parts[2]

        if server_name not in self._mcp_servers:
            return {"success": False, "error": f"MCP server '{server_name}' not available for this agent"}

        if tool_name == "mcp_robot_send_message":
            args.pop("_robot_context_token", None)
            args.pop("_termman_user_id", None)
            args.pop("_termman_is_superuser", None)
            args.pop("_robot_known_targets", None)
            if self._context and self._context.current_user_id:
                args["_termman_user_id"] = self._context.current_user_id
                args["_termman_is_superuser"] = self._context.current_user_is_superuser
            if self._context and self._context.robot_known_targets:
                args["_robot_known_targets"] = [
                    dict(target) for target in self._context.robot_known_targets
                ]

        for tool in self._mcp_tools:
            if tool.get("function", {}).get("name") == tool_name:
                input_schema = tool.get("function", {}).get("parameters", {})
                properties = input_schema.get("properties", {})
                if "item_id" in properties and "item_id" not in args:
                    if self._context and self._context.item_id:
                        args["item_id"] = self._context.item_id
                if (
                    tool_name == "mcp_robot_send_message"
                    and self._context
                    and self._context.robot_id
                    and self._context.robot_context_token
                ):
                    args["_robot_context_token"] = self._context.robot_context_token
                break

        if "command" in args:
            output_filter = self._get_output_filter()
            if output_filter:
                filter_result = output_filter.filter(args["command"])

                if filter_result.is_blocked:
                    logger.warning(f"[Agent] Command blocked by output filter: {filter_result.reason}")
                    return {
                        "success": False,
                        "error": f"Command blocked by security filter: {filter_result.reason}",
                        "blocked": True,
                    }

                if filter_result.action.value == "modified":
                    logger.info(f"[Agent] Command modified by output filter: {args['command']} -> {filter_result.command}")
                    args["command"] = filter_result.command

        try:
            result = await mcp_server_manager.call_tool(server_name, actual_tool_name, args)
            logger.info(f"[Agent] Executed MCP tool '{tool_name}' with args: {args}")
            return {"success": True, "result": result}
        except Exception as e:
            logger.error(f"[Agent] Error executing MCP tool '{tool_name}': {e}")
            return {"success": False, "error": str(e)}


class AgentManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._agents = {}
        return cls._instance

    def get_or_create(self, handler: ItemHandler) -> Agent:
        handler_id = str(handler.id)

        if handler_id in self._agents:
            agent = self._agents[handler_id]
            context = agent._context
            if context is None:
                agent.refresh_from_handler(handler)
                return agent

            if (
                context.model != handler.model
                or context.api_key != handler.api_key
                or context.api_url != handler.api_url
                or context.enabled_skills != (handler.enabled_skills or [])
                or context.enabled_mcp_servers != (handler.enabled_mcp_servers or [])
                or context.enabled_knowledge_files != (handler.enabled_knowledge_files or [])
            ):
                skill_loader.reload()
                agent.refresh_from_handler(handler)
            return agent

        agent = Agent.from_handler(handler)
        self._agents[handler_id] = agent
        return agent

    def refresh_cached(self, handler: ItemHandler) -> Agent | None:
        handler_id = str(handler.id)
        agent = self._agents.get(handler_id)
        if not agent:
            return None

        skill_loader.reload()
        agent.refresh_from_handler(handler)
        return agent


class ItemHandlerContext:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._item_handlers: dict[str, str] = {}
        self._global_lock = threading.RLock()
        logger.info("[ItemHandlerContext] Initialized")

    def set_handler(self, item_id: str, handler_id: str):
        with self._global_lock:
            self._item_handlers[item_id] = handler_id
            logger.info(f"[ItemHandlerContext] Set handler={handler_id} for item={item_id}")

    def get_handler(self, item_id: str) -> str | None:
        with self._global_lock:
            return self._item_handlers.get(item_id)

    def remove_handler(self, item_id: str):
        with self._global_lock:
            if item_id in self._item_handlers:
                del self._item_handlers[item_id]
                logger.info(f"[ItemHandlerContext] Removed handler for item={item_id}")


agent_manager = AgentManager()
item_handler_context = ItemHandlerContext()
