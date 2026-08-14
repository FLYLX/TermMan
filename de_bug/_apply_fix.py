import re

# Fix local_server.py
path1 = r"E:\dev\TermPaws\dev\TermPaws\backend\app\services\agent\mcp\local_server.py"
with open(path1, "r", encoding="utf-8") as f:
    content = f.read()

old1 = '                        success=bool(result.get("success")),'
new1 = '''                        success=(
                            bool(result.get("success"))
                            and result.get("exit_code") == 0
                            and not result.get("timed_out")
                            and not result.get("cancelled")
                        ),'''

if old1 in content:
    content = content.replace(old1, new1, 1)
    with open(path1, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print(f"[OK] Fixed {path1}")
else:
    print(f"[SKIP] Pattern not found in {path1}")

# Fix task_watchdog.py
path2 = r"E:\dev\TermPaws\dev\TermPaws\backend\app\services\agent\task_watchdog.py"
with open(path2, "r", encoding="utf-8") as f:
    content = f.read()

old2 = '                success=bool(result.get("success")),'
new2 = '''                success=(
                    bool(result.get("success"))
                    and result.get("exit_code") == 0
                    and not result.get("timed_out")
                    and not result.get("cancelled")
                ),'''

if old2 in content:
    content = content.replace(old2, new2, 1)
    with open(path2, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print(f"[OK] Fixed {path2}")
else:
    print(f"[SKIP] Pattern not found in {path2}")