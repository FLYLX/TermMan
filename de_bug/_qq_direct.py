import sys, json, time
sys.path.insert(0, "/app/backend")

from app.services.agent.session import agent_session_manager, InputMessage, InputType
from app.services.agent.reply_ticket import reply_ticket_manager
from app.services.agent.agent import Agent
from app.core.db import engine
from sqlmodel import Session
from app.models import ItemHandler, Item

ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

# Get handler
with Session(engine) as s:
    from sqlmodel import select
    item = s.exec(select(Item).where(Item.id == ITEM)).first()
    if not item:
        # Try by uuid
        item = s.exec(select(Item).where(Item.id == ITEM)).first()
    handlers = s.exec(select(ItemHandler).where(ItemHandler.item_id == item.id if item else None)).all()
    if not handlers:
        print("No handler found")
        sys.exit(1)
    handler = handlers[0]
    print(f"Handler: {handler.id}, model={handler.model}")

# Get or create agent session
session = agent_session_manager.get_or_create(str(handler.id), ITEM)
agent = session.get_agent()
if not agent:
    print("No agent")
    sys.exit(1)

# Create a QQ reply ticket
ticket = reply_ticket_manager.create_for_agent(
    agent,
    item_id=ITEM,
    handler_id=str(handler.id),
    message="小柴在吗",
    source_type="qq",
)
print(f"Ticket: {ticket.ticket_id}, source={ticket.source_type}")

# Build input message as QQ
input_msg = InputMessage(
    content="小柴在吗",
    input_type=InputType.CHAT,
    reply_ticket_id=ticket.ticket_id,
    query="小柴在吗",
)

# Set robot context on agent
agent._context.robot_sender_key = "private_2537134688"
agent._context.robot_conversation_key = "private_2537134688"
agent._context.robot_id = "5cbc7f55-04a2-40f6-900a-05e0b0dd652a"

print("\nProcessing QQ message...")
session.process_input(input_msg)

# Wait for processing
time.sleep(15)

# Check what happened
print("\n=== Results ===")
# Check ticket status
t = reply_ticket_manager.get(ticket.ticket_id)
if t:
    print(f"Ticket status: {t.status}")
    print(f"Ticket source: {t.source_type}")

# Check session for response
from app.services.agent.history.chat import get_chat_messages
msgs = get_chat_messages(ITEM)
for m in msgs[-5:]:
    mtype = m.get("type", "")
    content = str(m.get("content", ""))[:200]
    print(f"  [{mtype}] {content}")