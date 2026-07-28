import requests, json, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Cancel any existing workflow first
r0 = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
    json={"message": "\u53d6\u6d88\u6240\u6709\u4efb\u52a1", "history": []},
    headers=h)
print(f"Cancel: {r0.json().get('content','')[:80]}")
time.sleep(5)

# Clear token table
import subprocess
subprocess.run(["docker", "exec", "termman-backend-1", "python", "-c",
    "import sys; sys.path.insert(0,'/app/backend'); from sqlmodel import Session,text; from app.core.db import engine; s=Session(engine); s.exec(text('DELETE FROM token_usage_record')); s.commit(); s.close(); print('cleared')"],
    capture_output=True, timeout=10)
print("Token table cleared")
time.sleep(2)

# THE test message - bare minimum
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}",
    json={"message": "\u4e0b\u8f7djava21\uff0c\u7136\u540e\u5f001.20.1\u670d\u52a1\u5668", "history": []},
    headers=h)
print(f"Task sent: {r2.json().get('content','')[:80]}")
