import re

# === test_agent_runtime_guards.py ===
f1 = r"E:\dev\TermMan\dev\TermMan\backend\tests\services\test_agent_runtime_guards.py"
with open(f1, "r", encoding="utf-8") as fh:
    lines = fh.readlines()

# Find and remove three test functions
remove_funcs = [
    "test_expected_terminal_output_match_clears_pending_command",
    "test_expected_terminal_output_timeout_does_not_interrupt_by_default",
    "test_expected_terminal_output_timeout_can_interrupt_when_explicit",
]

delete = set()
for func_name in remove_funcs:
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith(f"def {func_name}("):
            start = i
            break
    if start is None:
        print(f"WARNING: {func_name} not found")
        continue
    # Find end: next top-level def or class
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("def ") or lines[i].startswith("class "):
            end = i
            break
    # Also delete preceding blank lines
    while start > 0 and lines[start - 1].strip() == "":
        start -= 1
    for i in range(start, end):
        delete.add(i)
    print(f"Removing {func_name}: lines {start+1}-{end}")

# Also remove expected_regex from record call around line 2535
for i, line in enumerate(lines):
    if 'expected_regex=r"Done' in line:
        delete.add(i)
        print(f"Removing expected_regex param at line {i+1}")

new_lines = [line for i, line in enumerate(lines) if i not in delete]
with open(f1, "w", encoding="utf-8") as fh:
    fh.writelines(new_lines)
print(f"test_agent_runtime_guards.py: removed {len(delete)} lines")

# === test_local_mcp_server.py ===
f2 = r"E:\dev\TermMan\dev\TermMan\backend\tests\services\test_local_mcp_server.py"
with open(f2, "r", encoding="utf-8") as fh:
    lines2 = fh.readlines()

delete2 = set()
for i, line in enumerate(lines2):
    if 'assert "expected_output" in props' in line or 'assert "expected_regex" in props' in line:
        delete2.add(i)
        print(f"test_local_mcp_server.py: removing line {i+1}")

new_lines2 = [line for i, line in enumerate(lines2) if i not in delete2]
with open(f2, "w", encoding="utf-8") as fh:
    fh.writelines(new_lines2)

# === test_terminal_command_state.py ===
f3 = r"E:\dev\TermMan\dev\TermMan\backend\tests\services\test_terminal_command_state.py"
with open(f3, "r", encoding="utf-8") as fh:
    content = fh.read()

content = re.sub(r'\s*expected_regex=r"Done \(\.\*\)!",?\n', '\n', content)
with open(f3, "w", encoding="utf-8") as fh:
    fh.write(content)
print("test_terminal_command_state.py: cleaned")