import sys, time
sys.path.insert(0, "/app/backend")

ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
HANDLER = "288d27b5-82cf-41f2-90dd-f56a5300521e"

from app.services.agent.session import agent_session_manager, InputMessage, InputType
from app.services.agent.reply_ticket import reply_ticket_manager

session = agent_session_manager.get_or_create_session(ITEM, HANDLER)
agent = session.get_agent()
if not agent:
    print("No agent yet, waiting...")
    time.sleep(5)
    agent = session.get_agent()
if not agent:
    print("FAILED: no agent")
    sys.exit(1)
print(f"Agent OK, model={agent._context.model}")

ticket = reply_ticket_manager.create_for_agent(
    agent, item_id=ITEM, handler_id=HANDLER,
    message="小柴在吗", source_type="qq",
)
print(f"Ticket: {ticket.ticket_id[:12]}, source={ticket.source_type}")

agent._context.robot_sender_key = "private_2537134688"
agent._context.robot_conversation_key = "private_2537134688"
agent._context.robot_id = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"

input_msg = InputMessage(
    content="小柴在吗",
    input_type=InputType.CHAT,
    reply_ticket_id=ticket.ticket_id,
    query="小柴在吗",
)

print("Processing QQ message...")
session.process_input(input_msg)
time.sleep(15)

t = reply_ticket_manager.get(ticket.ticket_id)
if t:
    print(f"\nTicket: status={t.status}, source={t.source_type}")

from app.services.agent.history.chat import get_chat_messages
msgs = get_chat_messages(ITEM)
for m in msgs[-5:]:
    mtype = m.get("type", "")
    tool = m.get("tool_name", "")
    content = str(m.get("content", ""))[:200]
    print(f"  [{mtype}|{tool}] {content}")