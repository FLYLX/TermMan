import sys

SERVICE = r"backend\app\plugins\robot\service.py"
TESTS = r"backend\tests\services\test_robot_service.py"

def load(path):
    with open(path, encoding="utf-8", newline="") as f:
        raw = f.read()
    had_crlf = "\r\n" in raw
    return raw.replace("\r\n", "\n"), had_crlf

def save(path, text, had_crlf):
    if had_crlf:
        text = text.replace("\n", "\r\n")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)

def replace_once(text, old, new, label):
    n = text.count(old)
    assert n == 1, "%s: expected 1 occurrence, found %d" % (label, n)
    return text.replace(old, new)

# ---------- service.py ----------
svc, svc_crlf = load(SERVICE)

old_call = """            return job.message

        self._persist_inbound_long_term_memory(
            item_id=item.id,
            robot=robot,
            message=inbound_message,
            conversation_key=job.conversation_key,
            message_text=message_text,
        )
        pending_message_texts"""
new_call = """            return job.message

        pending_message_texts"""
svc = replace_once(svc, old_call, new_call, "service call site")

old_funcs = """    def _persist_inbound_long_term_memory(
        self,
        *,
        item_id: uuid.UUID | str,
        robot: Robot,
        message: RobotInboundMessage,
        conversation_key: str,
        message_text: str,
    ) -> None:
        if not message_text.strip():
            return
        try:
            from app.services.agent.memory.vector_store import vector_store
            from app.services.agent.prompts import policy as memory_policy

            explicit_candidate = memory_policy.build_conversation_memory_candidate(
                message_text,
                "recorded",
            )
            if explicit_candidate is not None:
                self._persist_scoped_memory_candidate(
                    item_id=item_id,
                    robot=robot,
                    conversation_key=conversation_key,
                    sender_key=message.sender_key,
                    reply_target=message.reply_target,
                    candidate=explicit_candidate,
                    store=vector_store,
                    source="qq_robot",
                )
                return

        except Exception:
            logger.exception(
                "[RobotService] Failed to write long-term robot memory robot=%s conversation=%s",
                robot.id,
                conversation_key,
            )

    def _persist_scoped_memory_candidate(
        self,
        *,
        item_id: uuid.UUID | str,
        robot: Robot,
        conversation_key: str,
        sender_key: str = "",
        reply_target: RobotReplyTarget | None = None,
        candidate: object,
        store: object,
        source: str,
        extra_metadata: dict[str, object] | None = None,
    ) -> str | None:
        from app.services.agent.prompts import policy as memory_policy

        memory_type = str(getattr(candidate, "memory_type", "") or "")
        content = str(getattr(candidate, "content", "") or "")
        speaker_global_key = speaker_global_key_from_context(sender_key, reply_target)
        metadata = {
            **dict(getattr(candidate, "metadata", {}) or {}),
            "source": source,
            "robot_id": str(robot.id),
            "robot_conversation_key": conversation_key,
            "conversation_key": conversation_key,
            "memory_scope": memory_scope_for_content(content, memory_type),
        }
        if sender_key:
            metadata.setdefault("speaker_key", sender_key)
        if speaker_global_key:
            metadata["speaker_global_key"] = speaker_global_key
        if extra_metadata:
            metadata.update(extra_metadata)
        return memory_policy.persist_memory_candidate(
            str(item_id),
            replace(candidate, metadata=metadata),
            store=store,
        )

"""
svc = replace_once(svc, old_funcs, "", "two functions")

old_import = """from .memory_scope import (
    memory_content_is_question_like,
    memory_scope_for_content,
    memory_scope_rank,
    speaker_global_key_from_context,
)"""
new_import = """from .memory_scope import (
    memory_content_is_question_like,
    memory_scope_rank,
    speaker_global_key_from_context,
)"""
svc = replace_once(svc, old_import, new_import, "import block")

assert "_persist_inbound_long_term_memory" not in svc, "residual func1"
assert "_persist_scoped_memory_candidate" not in svc, "residual func2"
assert "memory_scope_for_content" not in svc, "residual import use"
save(SERVICE, svc, svc_crlf)
print("service.py OK")

# ---------- tests ----------
t, t_crlf = load(TESTS)

old_test = """def test_robot_explicit_memory_is_persisted_with_conversation_scope(
    db: Session,
    monkeypatch,
) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    db.add(
        RobotItem(
            robot_id=robot.id,
            item_id=item.id,
            allow_chat=True,
            receive_filtered_output=False,
            chat_alias="alpha",
            is_default_target=True,
        )
    )
    db.commit()

    captured = _capture_queued_chat(monkeypatch)
    persisted: list[tuple[str, object, object]] = []

    def fake_persist_memory_candidate(item_id, candidate, store):
        persisted.append((item_id, candidate, store))
        return "memory-1"

    monkeypatch.setattr(
        "app.services.agent.prompts.policy.persist_memory_candidate",
        fake_persist_memory_candidate,
    )

    response = robot_service.handle_inbound_message(
        db,
        robot,
        _message(
            "remember this: nickname is XiaoChai",
            target={"id": "g1"},
            mentioned_bot=True,
        ),
    )

    assert response.success is True
    assert response.ignored is False
    assert captured["job"].conversation_key == "group:g1"
    _process_captured_chat_job(monkeypatch, captured["job"])
    assert len(persisted) == 1
    assert persisted[0][0] == str(item.id)
    candidate = persisted[0][1]
    assert candidate.content == "nickname is XiaoChai"
    assert candidate.memory_type == "fact"
    assert candidate.metadata["source"] == "qq_robot"
    assert candidate.metadata["robot_id"] == str(robot.id)
    assert candidate.metadata["conversation_key"] == "group:g1"
    assert candidate.metadata["robot_conversation_key"] == "group:g1"


def test_robot_message_includes_current_conversation_impression_card("""
new_test = """def test_robot_message_includes_current_conversation_impression_card("""
t = replace_once(t, old_test, new_test, "explicit test")

stub_single = '    monkeypatch.setattr(robot_service, "_persist_inbound_long_term_memory", lambda **_: None)\n'
n = t.count(stub_single)
assert n == 8, "single-line stubs expected 8, found %d" % n
t = t.replace(stub_single, "")

stub_block_a = """    monkeypatch.setattr(
        robot_service,
        "_persist_inbound_long_term_memory",
        lambda **_: None,
    )
"""
t = replace_once(t, stub_block_a, "", "stub block A")

stub_block_b = """    monkeypatch.setattr(
        robot_service,
        "_persist_inbound_long_term_memory",
        lambda **kwargs: None,
    )
"""
t = replace_once(t, stub_block_b, "", "stub block B")

assert "_persist_inbound_long_term_memory" not in t, "residual in tests"
save(TESTS, t, t_crlf)
print("test_robot_service.py OK")
print("DONE")
