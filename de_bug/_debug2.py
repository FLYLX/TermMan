import sys

with open("/app/backend/app/services/agent/session.py", "r", encoding="utf-8") as f:
    content = f.read()

old = '''                    logger.info("[TokenDebug] usage=%s type=%s", usage, type(usage).__name__)'''
new = '''                    print(f"[TokenDebug] usage={usage} type={type(usage).__name__}", flush=True)
                    logger.info("[TokenDebug] usage=%s type=%s", usage, type(usage).__name__)'''

if old in content:
    content = content.replace(old, new, 1)
    with open("/app/backend/app/services/agent/session.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("PATCHED print OK")
else:
    print("PATTERN NOT FOUND - checking what's there")
    for i, line in enumerate(content.split("\n")):
        if "TokenDebug" in line:
            print(f"  Line {i+1}: {line.strip()}")