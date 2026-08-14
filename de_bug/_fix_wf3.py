filepath = r"E:\dev\TermPaws\dev\TermPaws\backend\app\services\agent\mcp\local_server.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

old = '''                "cancel only when user abandons. After updating, call execution tool."'''
new = '''                "cancel only when user abandons. "
                "Completing the LAST step auto-transitions to ready_to_report—just report. "
                "After updating, call execution tool."'''

if old in content:
    content = content.replace(old, new, 1)
    with open(filepath, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print("PATCHED: auto-report hint added")
else:
    print("NOT FOUND")