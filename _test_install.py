import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"}, timeout=10)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Clear tokens
from sqlmodel import Session, text
sys.path.insert(0, "/app/backend")
from app.core.db import engine
with Session(engine) as s:
    s.exec(text("DELETE FROM token_usage_record"))
    s.commit()

# Send install java21 message
msg = "\u5b89\u88c5java21\uff0c\u88c5\u5b8c\u9a8c\u8bc1\u7248\u672c"
print(f"Sending: {msg}")
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": msg, "history": []}, headers=h, timeout=120)
print(f"Status: {r2.status_code}")
data = r2.json()
print(f"Response: {json.dumps(data, ensure_ascii=False)[:500]}")