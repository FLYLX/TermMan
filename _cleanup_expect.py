import re

# === session.py ===
f = r"E:\dev\TermMan\dev\TermMan\backend\app\services\agent\session.py"
with open(f, "r", encoding="utf-8") as fh:
    lines = fh.readlines()

# Track lines to delete (0-indexed)
delete = set()

# 1. PendingCommand fields: expected_output, expected_regex (lines 657-658)
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped == 'expected_output: str = ""' or stripped == 'expected_regex: str = ""':
        delete.add(i)

# 2. has_expectation() and expectation_label() methods (lines 664-672)
in_method = False
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped == "def has_expectation(self) -> bool:":
        in_method = True
    if in_method:
        delete.add(i)
        if stripped.startswith("return") and "expected" in stripped:
            # Keep deleting until blank line
            pass
    if in_method and stripped == "" and i > 665:
        # Check if next line is another method or blank
        if i+1 < len(lines) and lines[i+1].strip().startswith("def expectation_label"):
            continue  # keep deleting
        else:
            in_method = False

# Re-scan for expectation_label method
in_method = False
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped == "def expectation_label(self) -> str:":
        in_method = True
    if in_method:
        delete.add(i)
        if stripped == 'return ""':
            in_method = False

# 3. expected_output/expected_regex variable assignments in _set_pending_command
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped.startswith("expected_output = _normalize_optional_text"):
        delete.add(i)
    if stripped.startswith("expected_regex = _normalize_optional_text"):
        delete.add(i)

# 4. expected_output/expected_regex in PendingCommand constructor and state manager
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped == "expected_output=expected_output,":
        delete.add(i)
    if stripped == "expected_regex=expected_regex,":
        delete.add(i)

# 5. _pending_expectation_matches method - delete entire method
in_method = False
brace_depth = 0
for i, line in enumerate(lines):
    stripped = line.strip()
    if "def _pending_expectation_matches(" in stripped:
        in_method = True
    if in_method:
        delete.add(i)
        # Method ends when we hit the next def at same indent or blank line after return
        if stripped.startswith("def ") and "_pending_expectation_matches" not in stripped:
            delete.discard(i)  # Don't delete the next method
            in_method = False
        if stripped == "return False" and i > 1530:
            # Check if next non-blank line is a new method
            for j in range(i+1, min(i+3, len(lines))):
                if lines[j].strip().startswith("def "):
                    in_method = False
                    break

# 6. expectation_label reference in _send_interrupt_for_pending_timeout
# Replace the return message
for i, line in enumerate(lines):
    if "pending.expectation_label()" in line and "没有匹配预期输出" in lines[i-1] if i > 0 else False:
        # Replace these two lines with a simpler message
        pass

# 7. has_expectation block in _run_pending_command_recheck (lines 1604-1610)
in_block = False
for i, line in enumerate(lines):
    stripped = line.strip()
    if "if pending.has_expectation() and elapsed_seconds >= pending.timeout_seconds:" in stripped:
        in_block = True
    if in_block:
        delete.add(i)
        if stripped == "return" and i > 1605:
            # Check if this is the last return in the block
            if i+1 < len(lines) and lines[i+1].strip() == "":
                delete.add(i+1) if i+1 < len(lines) else None
                in_block = False

# 8. has_expectation block in _maybe_hold_for_pending_terminal_feedback (lines 1859-1887)
in_block = False
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped == "if pending.has_expectation():":
        in_block = True
    if in_block:
        delete.add(i)
        if stripped == "return True, None, False" and i > 1860:
            in_block = False

# Apply deletions
new_lines = [line for i, line in enumerate(lines) if i not in delete]

# Fix the _send_interrupt_for_pending_timeout message
result = []
skip_next = False
for i, line in enumerate(new_lines):
    if skip_next:
        skip_next = False
        continue
    if "没有匹配预期输出" in line:
        # Replace with simpler message
        indent = line[:len(line) - len(line.lstrip())]
        result.append(f'{indent}f"命令 `{{pending.command}}` 在 {{pending.timeout_seconds}} 秒内未完成。"\n')
        # Skip next line if it has expectation_label
        if i+1 < len(new_lines) and "expectation_label" in new_lines[i+1]:
            skip_next = True
        continue
    result.append(line)

with open(f, "w", encoding="utf-8") as fh:
    fh.writelines(result)

print(f"session.py: deleted {len(delete)} lines, fixed interrupt message")

# === local_server.py ===
f2 = r"E:\dev\TermMan\dev\TermMan\backend\app\services\agent\mcp\local_server.py"
with open(f2, "r", encoding="utf-8") as fh:
    content = fh.read()

# Remove expected_output and expected_regex parameter definitions
content = re.sub(r'\s*"expected_output":\s*\{[^}]*\},?\n', '\n', content)
content = re.sub(r'\s*"expected_regex":\s*\{[^}]*\},?\n', '\n', content)

with open(f2, "w", encoding="utf-8") as fh:
    fh.write(content)

print("local_server.py: removed expected_output/expected_regex params")