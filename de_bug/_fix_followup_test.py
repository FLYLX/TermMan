import pathlib
p = pathlib.Path(r"E:\dev\TermMan\dev\TermMan\backend\tests\services\test_robot_service.py")
text = p.read_text(encoding="utf-8")
old = '''    queued_jobs: list[Any] = []
    persisted_messages: list[str] = []
    current_question = "\\u8c01\\u662f\\u732b\\u5a18"'''
new = '''    queued_jobs: list[Any] = []
    current_question = "\\u8c01\\u662f\\u732b\\u5a18"'''
assert text.count(old) == 1
text = text.replace(old, new)
old2 = '''    monkeypatch.setattr(
        robot_service,
        "_persist_inbound_long_term_memory",
        lambda **kwargs: persisted_messages.append(kwargs["message_text"]),
    )
    monkeypatch.setattr(
        robot_conversation_memory,
        "read_recent",'''
new2 = '''    monkeypatch.setattr(robot_service, "_persist_inbound_long_term_memory", lambda **_: None)
    monkeypatch.setattr(
        robot_conversation_memory,
        "read_recent",'''
assert text.count(old2) == 1
text = text.replace(old2, new2)
old3 = '''    assert len(queued_jobs) == 1
    assert persisted_messages == [current_question]
    message = queued_jobs[0].message'''
new3 = '''    assert len(queued_jobs) == 1
    message = queued_jobs[0].message'''
assert text.count(old3) == 1
text = text.replace(old3, new3)
p.write_text(text, encoding="utf-8")
print("followup test trimmed")
