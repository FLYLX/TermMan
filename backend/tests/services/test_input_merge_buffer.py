from datetime import datetime, timezone

from app.services.agent.input_merge_buffer import (
    SOURCE_JOB_RESULT,
    SOURCE_QQ_MESSAGE,
    InputMergeBuffer,
    MergeBufferEntry,
)


def _entry(source: str, scope: str, content: str) -> MergeBufferEntry:
    return MergeBufferEntry(
        source_type=source,
        item_id="item-1",
        scope_key=scope,
        sender_label="FLY",
        sender_key="u1",
        content=content,
        enqueued_at=datetime.now(timezone.utc),
        payload={"content": content},
    )


def test_merge_buffer_add_peek_pop_roundtrip() -> None:
    buffer = InputMergeBuffer()
    buffer.add(_entry(SOURCE_QQ_MESSAGE, "conv-1", "你好"))
    buffer.add(_entry(SOURCE_QQ_MESSAGE, "conv-1", "在吗"))
    buffer.add(_entry(SOURCE_JOB_RESULT, "conv-1", "apt-get update"))

    assert buffer.count("item-1", "conv-1") == 3
    peeked = buffer.peek("item-1", "conv-1")
    assert [e.content for e in peeked] == ["你好", "在吗", "apt-get update"]
    assert peeked[0].sender_label == "FLY"
    assert peeked[2].source_type == SOURCE_JOB_RESULT

    popped = buffer.pop("item-1", "conv-1")
    assert len(popped) == 3
    assert buffer.count("item-1", "conv-1") == 0


def test_merge_buffer_scopes_do_not_mix() -> None:
    buffer = InputMergeBuffer()
    buffer.add(_entry(SOURCE_QQ_MESSAGE, "conv-a", "A群消息"))
    buffer.add(_entry(SOURCE_QQ_MESSAGE, "conv-b", "B群消息"))

    popped_a = buffer.pop("item-1", "conv-a")
    assert [e.content for e in popped_a] == ["A群消息"]
    assert [e.content for e in buffer.peek("item-1", "conv-b")] == ["B群消息"]


def test_merge_buffer_evicts_oldest_over_limit_and_returns_them() -> None:
    buffer = InputMergeBuffer()
    buffer.set_source_limit(SOURCE_QQ_MESSAGE, 2)
    buffer.add(_entry(SOURCE_QQ_MESSAGE, "conv-1", "第一条"))
    buffer.add(_entry(SOURCE_QQ_MESSAGE, "conv-1", "第二条"))
    pending_size, evicted = buffer.add(_entry(SOURCE_QQ_MESSAGE, "conv-1", "第三条"))

    assert pending_size == 2
    assert [e.content for e in evicted] == ["第一条"]
    assert [e.content for e in buffer.peek("item-1", "conv-1")] == ["第二条", "第三条"]


def test_merge_buffer_prepend_restores_entries() -> None:
    buffer = InputMergeBuffer()
    buffer.add(_entry(SOURCE_QQ_MESSAGE, "conv-1", "旧消息"))
    popped = buffer.pop("item-1", "conv-1")
    buffer.add(_entry(SOURCE_QQ_MESSAGE, "conv-1", "新消息"))
    buffer.prepend("item-1", "conv-1", popped)

    assert [e.content for e in buffer.peek("item-1", "conv-1")] == ["旧消息", "新消息"]
