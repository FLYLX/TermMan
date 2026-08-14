import ast, pathlib, re, sys

root = pathlib.Path(r"E:\dev\TermPaws\dev\TermPaws")

def delete_tests(rel, names):
    p = root / rel
    text = p.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text)
    ranges = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            ranges.append((node.lineno, node.end_lineno))
    assert len(ranges) == len(names), f"{rel}: found {len(ranges)}/{len(names)}"
    keep = [True] * len(lines)
    for (s, e) in sorted(ranges, reverse=True):
        for i in range(s - 1, e):
            keep[i] = False
        # swallow trailing blanks
        j = e
        while j < len(lines) and lines[j].strip() == "":
            keep[j] = False
            j += 1
        # but leave max 2 blanks before next def
        if j < len(lines):
            keep[j-2] = True if j-2 >= e else keep[j-2]
            keep[j-1] = True if j-1 >= e else keep[j-1]
    text = "".join(ln for ln, k in zip(lines, keep) if k)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    p.write_text(text, encoding="utf-8")
    print(f"{rel}: deleted {len(names)} tests")

# ---- test_memory_policy.py ----
rel = r"backend\tests\services\test_memory_policy.py"
delete_tests(rel, [
    "test_build_auto_conversation_memory_candidate_for_preference",
    "test_build_auto_conversation_memory_candidate_for_personal_reply_style",
    "test_build_auto_conversation_memory_candidate_skips_noise_and_questions",
    "test_build_auto_conversation_memory_candidate_for_bot_identity",
    "test_build_auto_conversation_memory_candidate_for_named_person_alias",
    "test_auto_memory_keeps_identity_fact_with_qq_mention",
    "test_build_auto_conversation_memory_candidate_promotes_stable_person_fact_after_repeats",
    "test_build_auto_conversation_memory_candidate_skips_uncertain_stable_fact_question",
])
p = root / rel
text = p.read_text(encoding="utf-8")
imp = "    build_auto_conversation_memory_candidate,\n"
assert text.count(imp) == 1
text = text.replace(imp, "")
old_body = '''def test_task_word_does_not_block_a_real_preference_memory() -> None:
    explicit = build_conversation_memory_candidate(
        "\u8bb0\u4f4f\u4ee5\u540e\u90fd\u8981\u5728\u4efb\u52a1\u5f00\u59cb\u524d\u5148\u786e\u8ba4",
        "\u5df2\u8bb0\u5f55\u3002",
    )
    automatic = build_auto_conversation_memory_candidate(
        "\u6211\u559c\u6b22\u4efb\u52a1\u5b8c\u6210\u540e\u53ea\u56de\u590d\u4e00\u6b21",
        speaker_label="FLY (2537134688)",
    )

    assert explicit is not None
    assert explicit.memory_type == "preference"
    assert automatic is not None
    assert automatic.candidate.memory_type == "preference"
'''
new_body = '''def test_task_word_does_not_block_a_real_preference_memory() -> None:
    explicit = build_conversation_memory_candidate(
        "\u8bb0\u4f4f\u4ee5\u540e\u90fd\u8981\u5728\u4efb\u52a1\u5f00\u59cb\u524d\u5148\u786e\u8ba4",
        "\u5df2\u8bb0\u5f55\u3002",
    )

    assert explicit is not None
    assert explicit.memory_type == "preference"
'''
assert text.count(old_body) == 1, "task_word body"
text = text.replace(old_body, new_body)
p.write_text(text, encoding="utf-8")
print("test_memory_policy.py cleaned")

# ---- test_robot_service.py ----
rel = r"backend\tests\services\test_robot_service.py"
delete_tests(rel, [
    "test_robot_auto_memory_high_confidence_is_persisted_with_sender_scope",
    "test_robot_auto_memory_low_confidence_promotes_after_repeat",
])
p = root / rel
text = p.read_text(encoding="utf-8")
old_patch = '''    def fail_slow_memory(**_kwargs):
        raise AssertionError("long-term memory must run in the worker, not dispatch")

    def fail_impression(**_kwargs):
        raise AssertionError("impression card must run in the worker, not dispatch")

    monkeypatch.setattr(
        robot_service,
        "_persist_inbound_long_term_memory",
        fail_slow_memory,
    )
    monkeypatch.setattr(robot_service, "_conversation_impression_card", fail_impression)
'''
new_patch = '''    def fail_impression(**_kwargs):
        raise AssertionError("impression card must run in the worker, not dispatch")

    monkeypatch.setattr(robot_service, "_conversation_impression_card", fail_impression)
'''
assert text.count(old_patch) == 1, "slow_memory patch"
text = text.replace(old_patch, new_patch)
p.write_text(text, encoding="utf-8")
print("test_robot_service.py cleaned")
print("STAGE MEM-2 DONE")
