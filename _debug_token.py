import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"

r = requests.post(f"{BASE}/api/v1/login/access-token",
    data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Test token API
r2 = requests.get(f"{BASE}/api/v1/items/{ITEM}/token-usage", headers=h)
print(f"Token API: {r2.status_code} {r2.text[:300]}")

# Check backend logs for errors
import subprocess
result = subprocess.run(
    ["docker", "logs", "termman-backend-1", "--tail", "30"],
    capture_output=True, text=True, timeout=10
)
errors = [l for l in result.stderr.split('\n') if 'error' in l.lower() or 'Error' in l or 'Traceback' in l]
print(f"\nRecent errors ({len(errors)}):")
for e in errors[-5:]:
    print(f"  {e[:150]}")
