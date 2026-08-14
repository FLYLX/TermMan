filepath = r"E:\dev\TermPaws\dev\TermPaws\backend\app\services\agent\session.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

old = '''                    print(f"[TokenDebug] usage={usage} type={type(usage).__name__}", flush=True)
                    logger.info("[TokenDebug] usage=%s type=%s", usage, type(usage).__name__)'''
new = '''                    with open("/tmp/token_debug.log", "a") as _tdf:
                        _tdf.write(f"usage={usage} type={type(usage).__name__}\\n")
                    logger.warning("[TokenDebug] usage=%s type=%s", usage, type(usage).__name__)'''

if old in content:
    content = content.replace(old, new, 1)
    with open(filepath, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print("PATCHED to file+warning")
else:
    print("NOT FOUND")