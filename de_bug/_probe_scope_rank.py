import sys
from types import SimpleNamespace

from app.services.agent.integrations import registry as integration_registry
from app.plugins.robot.agent.integration import get_robot_agent_integration
from app.services.agent.integrations.hooks import integration_memory_scope_rank

integration = get_robot_agent_integration()
integration_registry._integrations[integration.name] = integration
print("registered integrations:", [i.name for i in integration_registry._integrations.values()])

agent = SimpleNamespace(
    _context=SimpleNamespace(
        robot_id="robot-1",
        robot_conversation_key="group:g1",
        robot_sender_key="onebot_v11:group:g1:u1",
    )
)
mem_same = {"id": "ctx-g1", "content": "this group forge", "metadata": {
    "memory_type": "context", "source": "qq_robot_auto_promoted", "robot_id": "robot-1",
    "conversation_key": "group:g1", "robot_conversation_key": "group:g1", "memory_scope": "conversation"}}
mem_other = {"id": "ctx-g2", "content": "other group stocks", "metadata": {
    "memory_type": "context", "source": "qq_robot_auto_promoted", "robot_id": "robot-1",
    "conversation_key": "group:g2", "robot_conversation_key": "group:g2", "memory_scope": "conversation"}}
print("rank same:", integration_memory_scope_rank(agent, mem_same))
print("rank other:", integration_memory_scope_rank(agent, mem_other))
