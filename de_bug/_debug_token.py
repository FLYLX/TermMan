import sys
sys.path.insert(0, "/app/backend")

# Read the file
with open("/app/backend/app/services/agent/session.py", "r", encoding="utf-8") as f:
    content = f.read()

# Add debug log after usage check
old = '''                try:
                    usage = getattr(response, "usage", None)
                    if usage:'''
new = '''                try:
                    usage = getattr(response, "usage", None)
                    logger.info("[TokenDebug] usage=%s type=%s", usage, type(usage).__name__)
                    if usage:'''

if old in content:
    content = content.replace(old, new, 1)
    with open("/app/backend/app/services/agent/session.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("PATCHED OK")
else:
    print("PATTERN NOT FOUND")