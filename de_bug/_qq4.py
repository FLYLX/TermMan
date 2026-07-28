import sys, time
sys.path.insert(0, "/app/backend")

ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
HANDLER = "288d27b5-82cf-41f2-90dd-f56a5300521e"

from app.services.agent.session import agent_session_manager, InputMessage, InputType
from app.services.agent.reply_ticket import reply_ticket_manager

session = agent_session_manager.get_or_create_session(ITEM, HANDLER)
agent = session.get_agent()
if not agent:
    time.sleep(5)
    agent = session.get_agent()
print(f"Agent OK")

# Set robot context BEFORE creating ticket
agent._context.robot_sender_key = "private_2537134688"
agent._context.robot_conversation_key = "private_2537134688"
agent._context.robot_id = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"
print(f"Robot context set: id={agent._context.robot_id}")

ticket = reply_ticket_manager.create_for_agent(
    agent, item_id=ITEM, handler_id=HANDLER,
    message="你好呀小柴", source_type="qq",
)
print(f"Ticket: {ticket.ticket_id[:12]}, source={ticket.source_type}")

input_msg = InputMessage(
    content="你好呀小柴",
    input_type=InputType.CHAT,
    reply_ticket_id=ticket.ticket_id,
    query="你好呀小柴",
)

print("Processing...")
session.process_input(input_msg)
time.sleep(15)

t = reply_ticket_manager.get(ticket.ticket_id)
if t:
    print(f"\nTicket: status={t.status}, source={t.source_type}")
    print(f"Reply targets: {len(t.reply_ticket_ids) if hasattr(t, 'reply_ticket_ids') else 'N/A'}")

from app.services.agent.history.chat import get_chat_messages
msgs = get_chat_messages(ITEM)
for m in msgs[-4:]:
    mtype = m.get("type", "")
    tool = m.get("tool_name", "")
    content = str(m.get("content", ""))[:250]
    print(f"  [{mtype}|{tool}] {content}")