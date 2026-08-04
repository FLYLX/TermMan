# -*- coding: utf-8 -*-
import sys

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

# ---------- A. integration.py: fix scope-rank kwarg bug ----------
p = r"backend\app\plugins\robot\agent\integration.py"
t, crlf = load(p)
old = """        try:
            from app.plugins.robot.memory_scope import (
                memory_content_is_question_like,
                memory_scope_rank as plugin_memory_scope_rank,
            )

            return plugin_memory_scope_rank(
                metadata=metadata,
                robot_id=robot_id,
                conversation_key=conversation_key,
                sender_key=sender_key,
            )
        except Exception:
            return 0"""
new = """        try:
            from app.plugins.robot.memory_scope import (
                memory_scope_rank as plugin_memory_scope_rank,
                speaker_global_key_from_context,
            )

            return plugin_memory_scope_rank(
                memory,
                robot_id=robot_id,
                conversation_key=conversation_key,
                speaker_global_key=speaker_global_key_from_context(sender_key),
            )
        except Exception:
            return 0"""
t = replace_once(t, old, new, "integration scope rank call")
save(p, t, crlf)
print("integration.py OK")

# ---------- B. test_robot_service.py: real @ mention in _message ----------
p = r"backend\tests\services\test_robot_service.py"
t, crlf = load(p)
old = """    reply: dict[str, Any] | None = None,
) -> RobotInboundMessage:
    metadata: dict[str, Any] = {}"""
new = """    reply: dict[str, Any] | None = None,
) -> RobotInboundMessage:
    if mentioned_bot and mentions is None:
        mentions = [{"qq": TEST_BOT_SELF_ID}]
    if mentioned_bot and bot_self_ids is None:
        bot_self_ids = [TEST_BOT_SELF_ID]
    metadata: dict[str, Any] = {}"""
t = replace_once(t, old, new, "_message mention upgrade")

old = """def _message("""
new = """TEST_BOT_SELF_ID = "10001"


def _message("""
t = replace_once(t, old, new, "TEST_BOT_SELF_ID constant")
save(p, t, crlf)
print("test_robot_service.py OK")

# ---------- C. test_memory_policy.py: new policy defaults ----------
p = r"backend\tests\services\test_memory_policy.py"
t, crlf = load(p)
old = """    assert chat_policy.include_long_term is True
    assert chat_policy.max_long_term_memories == 0
    assert "task" not in chat_policy.allowed_long_term_types
    assert terminal_policy.include_long_term is True
    assert terminal_policy.max_long_term_memories == 0
    assert "task" not in terminal_policy.allowed_long_term_types
    assert raw_feedback_policy.include_long_term is False"""
new = """    assert chat_policy.include_long_term is True
    assert chat_policy.max_long_term_memories == 3
    assert "task" not in chat_policy.allowed_long_term_types
    assert terminal_policy.include_long_term is True
    assert terminal_policy.max_long_term_memories == 12
    assert "task" not in terminal_policy.allowed_long_term_types
    assert raw_feedback_policy.include_long_term is False"""
t = replace_once(t, old, new, "policy defaults")
save(p, t, crlf)
print("test_memory_policy.py OK")

# ---------- D+E. test_memory_retrieval.py ----------
p = r"backend\tests\services\test_memory_retrieval.py"
t, crlf = load(p)

old = """    monkeypatch.setattr(
        prompt_builder,
        "_build_active_task_ledger_context",
        lambda *args, **kwargs: "",
    )

"""
t = replace_once(t, old, "", "ledger monkeypatch block")

old = """def test_robot_scoped_always_on_memory_does_not_cross_conversations(monkeypatch) -> None:
    agent = SimpleNamespace("""
new = """def _register_robot_integration(monkeypatch) -> None:
    from app.plugins.robot.agent.integration import get_robot_agent_integration
    from app.services.agent.integrations import registry as integration_registry

    integration = get_robot_agent_integration()
    monkeypatch.setitem(
        integration_registry._integrations,
        integration.name,
        integration,
    )


def test_robot_scoped_always_on_memory_does_not_cross_conversations(monkeypatch) -> None:
    _register_robot_integration(monkeypatch)
    agent = SimpleNamespace("""
t = replace_once(t, old, new, "isolation test 1 + helper")

old = """def test_robot_speaker_memory_does_not_cross_users_in_same_group(monkeypatch) -> None:
    agent = SimpleNamespace("""
new = """def test_robot_speaker_memory_does_not_cross_users_in_same_group(monkeypatch) -> None:
    _register_robot_integration(monkeypatch)
    agent = SimpleNamespace("""
t = replace_once(t, old, new, "isolation test 2")
save(p, t, crlf)
print("test_memory_retrieval.py OK")
print("ALL DONE")
