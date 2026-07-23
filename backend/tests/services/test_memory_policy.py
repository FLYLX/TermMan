from types import SimpleNamespace

from app.services.agent.prompts.policy import (
    MemoryCandidate,
    PromptTurnType,
    build_auto_conversation_memory_candidate,
    build_confirmation_memory_candidate,
    build_conversation_memory_candidate,
    build_manual_status_update,
    build_status_update_memory_candidate,
    infer_memory_key,
    persist_memory_candidate,
    resolve_memory_status,
    resolve_prompt_memory_policy,
    should_reject_long_term_memory,
)


def test_build_conversation_memory_candidate_for_preference() -> None:
    candidate = build_conversation_memory_candidate(
        "记住以后都用中文并且回复简洁",
        "后续会保持简洁中文回复。",
        matched_skills=[SimpleNamespace(skill_id="system_prompt")],
    )

    assert candidate is not None
    assert candidate.content == "用户偏好：以后都用中文并且回复简洁"
    assert candidate.memory_type == "preference"
    assert candidate.ttl_days is None
    assert candidate.metadata["type"] == "conversation_explicit"
    assert candidate.metadata["source"] == "chat_user"
    assert candidate.metadata["verified"] is True
    assert candidate.metadata["skills"] == ["system_prompt"]
    assert candidate.metadata["content_hash"]


def test_prompt_memory_policy_enables_long_term_by_default() -> None:
    chat_policy = resolve_prompt_memory_policy(PromptTurnType.CHAT)
    terminal_policy = resolve_prompt_memory_policy(PromptTurnType.TERMINAL_FILTERED)
    raw_feedback_policy = resolve_prompt_memory_policy(PromptTurnType.TERMINAL_RAW_FEEDBACK)

    assert chat_policy.include_long_term is True
    assert chat_policy.max_long_term_memories == 0
    assert "task" not in chat_policy.allowed_long_term_types
    assert terminal_policy.include_long_term is True
    assert terminal_policy.max_long_term_memories == 0
    assert "task" not in terminal_policy.allowed_long_term_types
    assert raw_feedback_policy.include_long_term is False


def test_build_conversation_memory_candidate_rejects_generic_or_log_noise() -> None:
    assert build_conversation_memory_candidate("记住这个", "好的") is None
    assert (
        build_conversation_memory_candidate(
            "记住 [2026-04-02 08:39:55] # # ls\n[2026-04-02 08:39:58] # # ls",
            "好的",
        )
        is None
    )
    assert should_reject_long_term_memory("命令已发送，等待终端反馈") is True
    assert should_reject_long_term_memory("token=super-secret-value") is True
    assert (
        should_reject_long_term_memory(
            "Executing tool: mcp_robot_send_message\n"
            "Message sent to current robot conversation."
        )
        is True
    )
    assert should_reject_long_term_memory("[no_qq_reply]") is True



def test_build_auto_conversation_memory_candidate_for_preference() -> None:
    candidate = build_auto_conversation_memory_candidate(
        "我喜欢短回复",
        speaker_label="Alice (u1)",
        speaker_key="onebot_v11:group:g1:u1",
        conversation_key="group:g1",
    )

    assert candidate is not None
    assert candidate.confidence >= 0.74
    assert candidate.candidate.memory_type == "preference"
    assert "Alice (u1)" in candidate.candidate.content
    assert "我喜欢短回复" in candidate.candidate.content
    assert candidate.candidate.metadata["source"] == "chat_user_auto"
    assert candidate.candidate.metadata["conversation_key"] == "group:g1"
    assert candidate.candidate.metadata["speaker_key"] == "onebot_v11:group:g1:u1"


def test_build_auto_conversation_memory_candidate_for_personal_reply_style() -> None:
    candidate = build_auto_conversation_memory_candidate(
        "\u5728\u56de\u590d\u6211\u7684\u65f6\u5019\uff0c\u4f60\u8981\u5728\u6bcf\u53e5\u8bdd\u7684\u672b\u5c3e\u52a0\u4e0a\u55b5",
        speaker_label="EX_GuguX (u2)",
        speaker_key="onebot_v11:group:g1:u2",
        conversation_key="group:g1",
    )

    assert candidate is not None
    assert candidate.confidence >= 0.74
    assert candidate.candidate.memory_type == "preference"
    assert "EX_GuguX (u2)" in candidate.candidate.content
    assert candidate.candidate.ttl_days is None


def test_build_auto_conversation_memory_candidate_skips_noise_and_questions() -> None:
    assert build_auto_conversation_memory_candidate("666") is None
    assert build_auto_conversation_memory_candidate("要是跌了能不能再入一点？") is None
    assert build_auto_conversation_memory_candidate("[CQ:image,file=a.jpg]") is None


def test_build_conversation_memory_candidate_accepts_remember_variants() -> None:
    candidate = build_conversation_memory_candidate(
        "\u8bb0\u4e00\u4e0b\u4f60\u53eb\u5927\u72d7",
        "recorded",
    )

    assert candidate is not None
    assert candidate.memory_type == "fact"
    assert candidate.content == "\u4f60\u53eb\u5927\u72d7"


def test_build_auto_conversation_memory_candidate_for_bot_identity() -> None:
    candidate = build_auto_conversation_memory_candidate("\u4f60\u53eb\u5927\u72d7")

    assert candidate is not None
    assert candidate.confidence >= 0.74
    assert candidate.candidate.memory_type == "fact"
    assert candidate.candidate.content == "\u4f60\u53eb\u5927\u72d7"


def test_build_auto_conversation_memory_candidate_for_named_person_alias() -> None:
    candidate = build_auto_conversation_memory_candidate(
        "\u82b1\u7cd5\u53eb\u5c0f\u82b1",
        speaker_label="FLY (u1)",
        speaker_key="onebot_v11:group:g1:u1",
        conversation_key="group:g1",
    )

    assert candidate is not None
    assert candidate.confidence >= 0.74
    assert candidate.candidate.memory_type == "fact"
    assert "\u82b1\u7cd5\u53eb\u5c0f\u82b1" in candidate.candidate.content


def test_auto_memory_keeps_identity_fact_with_qq_mention() -> None:
    candidate = build_auto_conversation_memory_candidate(
        (
            "\u6211\u660e\u786e\u7684\u544a\u8bc9\u4f60\uff0c"
            "\u732b\u5a18\u662f\u5979 [CQ:at,qq=3385417251] "
            "\u5979\u5c31\u662f\u6708\u5f71\u6c49\u5821\u732b\u5a18"
        ),
        speaker_label="New+7 (2206406352)",
        speaker_key="onebot_v11:group:770362397:2206406352",
        conversation_key="group:770362397",
    )

    assert candidate is not None
    assert candidate.confidence >= 0.74
    assert candidate.candidate.memory_type == "fact"
    assert "[CQ:" not in candidate.candidate.content
    assert "@QQ(3385417251)" in candidate.candidate.content
    assert "\u6708\u5f71\u6c49\u5821\u732b\u5a18" in candidate.candidate.content


def test_build_auto_conversation_memory_candidate_promotes_stable_person_fact_after_repeats() -> None:
    candidate = build_auto_conversation_memory_candidate("\u82b1\u7cd5\u662f\u7fa4\u7ba1\u7406\u5458")

    assert candidate is not None
    assert 0.45 <= candidate.confidence < 0.74
    assert candidate.candidate.memory_type == "fact"


def test_build_auto_conversation_memory_candidate_skips_uncertain_stable_fact_question() -> None:
    assert build_auto_conversation_memory_candidate("\u82b1\u7cd5\u662f\u7fa4\u7ba1\u7406\u5458\u5417\uff1f") is None


def test_persist_memory_candidate_skips_duplicate_hash() -> None:
    candidate = MemoryCandidate(
        content="用户偏好：以后回复简洁",
        memory_type="preference",
        ttl_days=None,
        metadata={"content_hash": "same-hash"},
    )

    class FakeStore:
        def get_all_memories(self, item_id: str, memory_type: str | None = None):
            return [{"id": "old-1", "metadata": {"content_hash": "same-hash"}}]

        def add_memory(self, **kwargs):
            raise AssertionError("duplicate candidate should not be written")

    memory_id = persist_memory_candidate("item-1", candidate, store=FakeStore())
    assert memory_id is None


def test_persist_memory_candidate_writes_with_candidate_ttl() -> None:
    candidate = MemoryCandidate(
        content="cron_job.py 位于 /app/src/cron_job.py",
        memory_type="fact",
        ttl_days=90,
        metadata={"content_hash": "hash-1", "type": "conversation_explicit"},
    )
    captured: dict[str, object] = {}

    class FakeStore:
        def get_all_memories(self, item_id: str, memory_type: str | None = None):
            return []

        def add_memory(self, **kwargs):
            captured.update(kwargs)
            return "mem-1"

    memory_id = persist_memory_candidate("item-2", candidate, store=FakeStore())

    assert memory_id == "mem-1"
    assert captured["item_id"] == "item-2"
    assert captured["content"] == "cron_job.py 位于 /app/src/cron_job.py"
    assert captured["memory_type"] == "fact"
    assert captured["ttl_days"] == 90
    assert captured["metadata"]["content_hash"] == "hash-1"
    assert captured["metadata"]["type"] == "conversation_explicit"
    assert captured["metadata"]["updated_at"]


def test_build_confirmation_memory_candidate_uses_previous_assistant_result() -> None:
    candidate = build_confirmation_memory_candidate(
        "对，就是这个路径",
        "cron_job.py 位于 /app/src/cron_job.py",
    )

    assert candidate is not None
    assert candidate.content == "cron_job.py 位于 /app/src/cron_job.py"
    assert candidate.memory_type == "fact"
    assert candidate.ttl_days == 90
    assert candidate.metadata["type"] == "conversation_confirmed"
    assert candidate.metadata["verified"] is True
    assert candidate.metadata["memory_key"] == "fact.cron_job.py"


def test_build_confirmation_memory_candidate_skips_generic_previous_reply() -> None:
    candidate = build_confirmation_memory_candidate(
        "对，就是这个",
        "已经处理好了",
    )
    assert candidate is None


def test_infer_memory_key_detects_preference_axes() -> None:
    assert infer_memory_key("用户偏好：以后都用中文", "preference") == "preference.language"
    assert infer_memory_key("用户偏好：回复简洁", "preference") == "preference.verbosity"
    assert infer_memory_key("当前任务：修复 daemon 状态同步", "task") is None
    assert infer_memory_key("已知错误：cron_job.py 找不到", "error") == "error.cron_job.py_找不到"


def test_persist_memory_candidate_updates_existing_same_key_memory() -> None:
    candidate = MemoryCandidate(
        content="用户偏好：以后都用英文",
        memory_type="preference",
        ttl_days=None,
        metadata={
            "content_hash": "new-hash",
            "memory_key": "preference.language",
            "type": "conversation_explicit",
        },
    )
    captured: dict[str, object] = {}

    class FakeStore:
        def get_all_memories(self, item_id: str, memory_type: str | None = None):
            return [
                {
                    "id": "old-1",
                    "content": "用户偏好：以后都用中文",
                    "metadata": {
                        "content_hash": "old-hash",
                        "memory_key": "preference.language",
                        "type": "conversation_explicit",
                    },
                }
            ]

        def update_memory(self, **kwargs):
            captured.update(kwargs)
            return True

        def add_memory(self, **kwargs):
            raise AssertionError("same-key candidate should update instead of add")

    memory_id = persist_memory_candidate("item-3", candidate, store=FakeStore())

    assert memory_id == "old-1"
    assert captured["memory_id"] == "old-1"
    assert captured["content"] == "用户偏好：以后都用英文"
    assert captured["metadata"]["memory_key"] == "preference.language"
    assert captured["metadata"]["content_hash"] == "new-hash"


def test_build_conversation_memory_candidate_maps_explicit_task_to_context() -> None:
    candidate = build_conversation_memory_candidate(
        "记住当前任务是修复 daemon 状态同步",
        "已记录。",
    )

    assert candidate is not None
    assert candidate.memory_type == "context"
    assert candidate.content == "当前任务是修复 daemon 状态同步"
    assert "status" not in candidate.metadata


def test_task_word_does_not_block_a_real_preference_memory() -> None:
    explicit = build_conversation_memory_candidate(
        "记住以后都要在任务开始前先确认",
        "已记录。",
    )
    automatic = build_auto_conversation_memory_candidate(
        "我喜欢任务完成后只回复一次",
        speaker_label="FLY (2537134688)",
    )

    assert explicit is not None
    assert explicit.memory_type == "preference"
    assert automatic is not None
    assert automatic.candidate.memory_type == "preference"


def test_build_status_update_memory_candidate_ignores_task_queue_state() -> None:
    class FakeStore:
        def get_all_memories(self, item_id: str, memory_type: str | None = None):
            return [
                {
                    "id": "task-1",
                    "content": "当前任务：修复 daemon 状态同步",
                    "metadata": {
                        "memory_type": "task",
                        "memory_key": "task.修复_daemon_状态同步",
                        "status": "active",
                        "created_at": "2026-04-02T09:00:00",
                    },
                }
            ]

    candidate = build_status_update_memory_candidate(
        "item-4",
        "这个任务已经完成了",
        store=FakeStore(),
    )

    assert candidate is None


def test_persist_memory_candidate_rejects_removed_task_memory_type() -> None:
    candidate = MemoryCandidate(
        content="当前任务：修复 daemon 状态同步",
        memory_type="task",
        ttl_days=14,
        metadata={},
    )

    class FakeStore:
        def get_all_memories(self, *_args, **_kwargs):
            return []

        def add_memory(self, **kwargs):
            raise AssertionError("removed task memory type must not be written")

    assert persist_memory_candidate("item-task", candidate, store=FakeStore()) is None


def test_build_status_update_memory_candidate_skips_ambiguous_targets() -> None:
    class FakeStore:
        def get_all_memories(self, item_id: str, memory_type: str | None = None):
            return [
                {
                    "id": "task-1",
                    "content": "当前任务：修复 daemon 状态同步",
                    "metadata": {
                        "memory_type": "task",
                        "memory_key": "task.修复_daemon_状态同步",
                        "status": "active",
                        "created_at": "2026-04-02T09:00:00",
                    },
                },
                {
                    "id": "task-2",
                    "content": "当前任务：补前端中断按钮",
                    "metadata": {
                        "memory_type": "task",
                        "memory_key": "task.补前端中断按钮",
                        "status": "active",
                        "created_at": "2026-04-02T09:10:00",
                    },
                },
            ]

    candidate = build_status_update_memory_candidate(
        "item-5",
        "任务完成了",
        store=FakeStore(),
    )

    assert candidate is None


def test_build_manual_status_update_marks_error_resolved() -> None:
    memory = {
        "id": "error-1",
        "content": "已知错误：cron_job.py 找不到",
        "metadata": {
            "memory_type": "error",
            "status": "active",
            "item_id": "item-1",
            "created_at": "2026-04-02T09:00:00",
        },
    }

    update_payload = build_manual_status_update(memory, "resolved")

    assert update_payload is not None
    updated_content, updated_metadata = update_payload
    assert updated_content == "已知错误：cron_job.py 找不到（已解决）"
    assert updated_metadata["status"] == "resolved"
    assert updated_metadata["type"] == "manual_status_action"
    assert updated_metadata["content_hash"]


def test_resolve_memory_status_ignores_removed_legacy_task_memory() -> None:
    memory = {
        "id": "task-legacy",
        "content": "当前任务：补中断按钮（已完成）",
        "metadata": {"memory_type": "task"},
    }

    assert resolve_memory_status(memory) is None
