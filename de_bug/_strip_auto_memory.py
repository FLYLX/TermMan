import ast, pathlib, re, sys

root = pathlib.Path(r"E:\dev\TermPaws\dev\TermPaws")

# ================= policy.py =================
p = root / r"backend\app\services\agent\prompts\policy.py"
text = p.read_text(encoding="utf-8")
lines = text.splitlines(keepends=True)
tree = ast.parse(text)

drop_names = {
    "AUTO_MEMORY_DIRECT_THRESHOLD", "AUTO_MEMORY_PROMOTION_THRESHOLD",
    "AUTO_MEMORY_REPEAT_THRESHOLD", "AUTO_MEMORY_MAX_PAYLOAD_LENGTH",
    "AUTO_MEMORY_SHORT_REACTIONS", "AUTO_PROFILE_PATTERNS",
    "AUTO_REPLY_STYLE_PATTERNS", "AUTO_IDENTITY_PATTERNS",
    "AUTO_ASSISTANT_IDENTITY_PATTERNS", "AUTO_NAMED_PERSON_ALIAS_PATTERNS",
    "AUTO_STABLE_PERSON_FACT_PATTERNS", "AUTO_RELATION_FACT_PATTERNS",
    "AUTO_PREFERENCE_CUES", "AUTO_TASK_CUES", "AUTO_ERROR_CUES",
    "AUTO_GROUP_CONTEXT_CUES", "AUTO_TRANSIENT_PREFIXES",
    "_looks_like_auto_memory_noise", "_auto_memory_base_score",
    "_scope_memory_payload", "_build_auto_memory_promotion_key",
    "build_auto_conversation_memory_candidate", "ScoredMemoryCandidate",
}
ranges = []
for node in tree.body:
    if isinstance(node, ast.Assign):
        targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
        if targets & drop_names:
            ranges.append((node.lineno, node.end_lineno))
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        if node.name in drop_names:
            ranges.append((node.lineno, node.end_lineno))

found = {name for (s, e) in ranges for name in drop_names}
keep_lines = [True] * len(lines)
for (s, e) in ranges:
    for i in range(s - 1, e):
        keep_lines[i] = False
    # also drop one trailing blank line after the block
    if e < len(lines) and lines[e].strip() == "":
        keep_lines[e] = False
new_text = "".join(ln for ln, keep in zip(lines, keep_lines) if keep)
new_text = re.sub(r"\n{4,}", "\n\n\n", new_text)
p.write_text(new_text, encoding="utf-8")
print(f"policy.py: removed {len(ranges)} top-level blocks")

# verify nothing dangling inside policy.py
for name in sorted(drop_names):
    for m in re.finditer(rf"\b{re.escape(name)}\b", new_text):
        print(f"  !! dangling ref: {name}")
        sys.exit(1)

# ================= prompts/__init__.py =================
p = root / r"backend\app\services\agent\prompts\__init__.py"
text = p.read_text(encoding="utf-8")
for frag in ("    ScoredMemoryCandidate,\n", "    build_auto_conversation_memory_candidate,\n",
             '    "ScoredMemoryCandidate",\n', '    "build_auto_conversation_memory_candidate",\n'):
    assert text.count(frag) == 1, frag
    text = text.replace(frag, "")
p.write_text(text, encoding="utf-8")
print("prompts/__init__.py exports removed")

# ================= service.py =================
p = root / r"backend\app\plugins\robot\service.py"
text = p.read_text(encoding="utf-8")

# 1) drop auto section inside _persist_inbound_long_term_memory (scored/direct/promoted)
start_marker = "            scored_candidate = memory_policy.build_auto_conversation_memory_candidate("
end_marker = '''                extra_metadata={
                    "type": "conversation_auto_promoted",
                    "observations": observations,
                    "verified": False,
                },
            )
'''
s = text.index(start_marker)
e = text.index(end_marker, s) + len(end_marker)
text = text[:s] + text[e:]

# the explicit branch should now end with return; then except. Clean dangling vars check later.
# 2) drop PendingRobotMemoryCandidate dataclass
old_dc = '''@dataclass
class PendingRobotMemoryCandidate:
    candidate: object
    confidence: float
    observations: int
    updated_at: datetime


'''
assert text.count(old_dc) == 1
text = text.replace(old_dc, "")

# 3) drop pending candidates state line
old_state = "        self._pending_memory_candidates: dict[tuple[str, str, str], PendingRobotMemoryCandidate] = {}\n"
assert text.count(old_state) == 1
text = text.replace(old_state, "")

# 4) drop _record_pending_memory_candidate + _prune_pending_memory_candidates_locked methods
lines = text.splitlines(keepends=True)
tree = ast.parse(text)
drop_methods = {"_record_pending_memory_candidate", "_prune_pending_memory_candidates_locked"}
ranges = []
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name in drop_methods:
        ranges.append((node.lineno, node.end_lineno))
assert len(ranges) == 2, ranges
keep = [True] * len(lines)
for (s_, e_) in ranges:
    for i in range(s_ - 1, e_):
        keep[i] = False
    if e_ < len(lines) and lines[e_].strip() == "":
        keep[e_] = False
text = "".join(ln for ln, k in zip(lines, keep) if k)
text = re.sub(r"\n{4,}", "\n\n\n", text)

# 5) drop memory_persisted loop in _enqueue_pending_chat_followup
old_loop = '''        for entry in entries:
            if entry.memory_persisted:
                continue
            self._persist_inbound_long_term_memory(
                item_id=entry.item_id,
                robot=robot,
                message=RobotInboundMessage(
                    sender_key=entry.sender_key,
                    text=entry.message_text,
                    reply_target=entry.reply_target.model_copy(deep=True),
                ),
                conversation_key=conversation_key,
                message_text=entry.message_text,
            )

        entries = [replace(entry, memory_persisted=True) for entry in entries]
        latest = entries[-1]'''
new_loop = '''        latest = entries[-1]'''
assert text.count(old_loop) == 1
text = text.replace(old_loop, new_loop)

# 6) drop memory_persisted field
old_field = "    memory_persisted: bool = False\n"
assert text.count(old_field) == 1
text = text.replace(old_field, "")

p.write_text(text, encoding="utf-8")
print("service.py: auto pipeline removed")

print("STAGE MEM-1 DONE")
