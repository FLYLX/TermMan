import os

# Fix local_server.py
path1 = r"E:\dev\TermPaws\dev\TermPaws\backend\app\services\agent\mcp\local_server.py"
with open(path1, "r", encoding="utf-8") as f:
    content = f.read()

old = '                        success=bool(result.get("success")),'
new = '''                        success=(
                            bool(result.get("success"))
                            and result.get("exit_code") == 0
                            and not result.get("timed_out")
                            and not result.get("cancelled")
                        ),'''

count = content.count(old)
print(f"Found {count} occurrences of old pattern in local_server.py")
if count > 0:
    content = content.replace(old, new, 1)
    with open(path1, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    # Verify
    with open(path1, "r", encoding="utf-8") as f:
        verify = f.read()
    if "and not result.get" in verify:
        print("[OK] Fix applied and verified in local_server.py")
    else:
        print("[FAIL] Fix not found after write!")
else:
    print("[SKIP] Pattern not found")

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

count2 = content.count(old2)
print(f"Found {count2} occurrences of old pattern in task_watchdog.py")
if count2 > 0:
    content = content.replace(old2, new2, 1)
    with open(path2, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    with open(path2, "r", encoding="utf-8") as f:
        verify = f.read()
    if "and not result.get" in verify:
        print("[OK] Fix applied and verified in task_watchdog.py")
    else:
        print("[FAIL] Fix not found after write!")
else:
    print("[SKIP] Pattern not found")