filepath = r"E:\dev\TermMan\dev\TermMan\backend\app\services\agent\prompts\policy.py"
with open(filepath, "r", encoding="utf-8") as f:
    c = f.read()
old = "        max_recent_messages=8,"
new = "        max_recent_messages=6,"
if old in c:
    c = c.replace(old, new, 1)
    with open(filepath, "w", encoding="utf-8", newline="\n") as f:
        f.write(c)
    print("Fixed: 8 -> 6")
else:
    print("NOT FOUND")