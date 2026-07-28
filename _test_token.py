import sys
sys.path.insert(0, "/app/backend")
from app.services.agent.token_usage import token_usage_tracker
token_usage_tracker.record("test-item", "test-model", 100, 50, 150)
stats = token_usage_tracker.get_item_stats("test-item")
print("Test record:", stats)
from sqlmodel import Session, text
from app.core.db import engine
with Session(engine) as s:
    s.exec(text("DELETE FROM token_usage_record WHERE item_id='test-item'"))
    s.commit()
print("Cleanup done")