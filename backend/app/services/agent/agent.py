import asyncio
import logging
import re
from dataclasses import dataclass, field

from app.models import ItemHandler
from app.services.agent.skills.loader import skill_loader
from app.services.agent.skills.definition import SkillDefinition
from app.services.agent.mcp.server_manager import mcp_server_manager
from app.services.filters.output_filter import OutputFilter, OutputFilterConfig

logger = logging.getLogger(__name__)


@dataclass
class AgentContext:
    handler_id: str
    item_id: str = ""
    model: str | None = None
    api_key: str | None = None
    api_url: str | None = None
    enabled_skills: list[str] = field(default_factory=list)
    enabled_mcp_servers: list[str] = field(default_factory=list)
    output_filter_enabled: bool = False
    output_filter_rules: dict = field(default_factory=dict)


class Agent:
    _instances: dict[str, "Agent"] = {}
    
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
        logger.info(f"[Agent] Created agent for handler {handler_id}")
    
    @classmethod
    def from_handler(cls, handler: ItemHandler) -> "Agent":
        agent = cls(str(handler.id))
        agent._context = AgentContext(
            handler_id=str(handler.id),
            model=handler.model,
            api_key=handler.api_key,
            api_url=handler.api_url,
            enabled_skills=handler.enabled_skills or [],
            enabled_mcp_servers=handler.enabled_mcp_servers or [],
        )
        agent._load_skills()
        return agent
    
    def _load_skills(self):
        self._skills.clear()
        self._mcp_servers.clear()
        self._mcp_tools.clear()
        
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
        for server_name in self._mcp_servers:
            tools = mcp_server_manager.get_tools_for_server(server_name)
            logger.info(f"[Agent] Got {len(tools)} tools from server '{server_name}'")
            for tool in tools:
                self._mcp_tools.append(tool.to_litellm_tool())
    
    async def start_mcp_servers(self):
        for server_name in self._mcp_servers:
            if not mcp_server_manager.is_server_running(server_name):
                success = await mcp_server_manager.start_server(server_name)
                if success:
                    self._load_mcp_tools()
                    tools_count = len([t for t in self._mcp_tools if t.get("function", {}).get("name", "").startswith(f"mcp_{server_name}_")])
                    logger.info(f"[Agent] Started MCP server '{server_name}', loaded {tools_count} tools")
                else:
                    logger.error(f"[Agent] Failed to start MCP server '{server_name}'")
            else:
                logger.info(f"[Agent] MCP server '{server_name}' already running")
    
    def set_item_context(self, item_id: str, item: "Item" = None):
        if self._context:
            self._context.item_id = item_id
            if item:
                self._context.output_filter_enabled = item.output_filter_enabled
                self._context.output_filter_rules = item.output_filter_rules or {}
    
    def _get_output_filter(self) -> OutputFilter | None:
        if not self._context or not self._context.output_filter_enabled:
            return None
        
        from dataclasses import dataclass
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
        
        for tool in self._mcp_tools:
            if tool.get("function", {}).get("name") == tool_name:
                input_schema = tool.get("function", {}).get("parameters", {})
                properties = input_schema.get("properties", {})
                if "item_id" in properties and "item_id" not in args:
                    if self._context and self._context.item_id:
                        args["item_id"] = self._context.item_id
                break
        
        if "command" in args:
            output_filter = self._get_output_filter()
            if output_filter:
                from app.services.filters.output_filter import FilterAction
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
            if server_name == "local":
                from app.services.agent.mcp.local_server import LocalMCPServer
                local_server = LocalMCPServer()
                result = local_server.call_tool(actual_tool_name, args)
            else:
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
            if (agent._context.enabled_skills != (handler.enabled_skills or []) or
                agent._context.enabled_mcp_servers != (handler.enabled_mcp_servers or [])):
                skill_loader.reload()
                agent._context.enabled_skills = handler.enabled_skills or []
                agent._context.enabled_mcp_servers = handler.enabled_mcp_servers or []
                agent._load_skills()
            return agent
        
        agent = Agent.from_handler(handler)
        self._agents[handler_id] = agent
        return agent


agent_manager = AgentManager()
