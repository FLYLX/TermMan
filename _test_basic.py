import requests, json, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BASE = "http://127.0.0.1:28888"
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
r = requests.post(f"{BASE}/api/v1/login/access-token", data={"username": "admin@example.com", "password": "changethis"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Test 1: Simple chat - persona check
print("=== TEST 1: Chat/Persona ===")
r1 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": "\u4f60\u662f\u8c01\u5440", "history": []}, headers=h, timeout=30)
print(f"  {r1.json().get('content','')[:200]}")

time.sleep(3)

# Test 2: Simple question - no workflow
print("\n=== TEST 2: Simple question ===")
r2 = requests.post(f"{BASE}/api/v1/chat/{ITEM}", json={"message": "1+1\u7b49\u4e8e", "history": []}, headers=h, timeout=30)
print(f"  {r2.json().get('content','')[:200]}")
