from app.plugins.robot.memory_scope import memory_scope_rank


def _speaker_memory(speaker_global_key: str, conversation_key: str = "group:g1") -> dict:
    return {
        "content": "speaker preference",
        "metadata": {
            "memory_type": "preference",
            "memory_scope": "speaker",
            "robot_id": "robot-1",
            "robot_conversation_key": conversation_key,
            "speaker_global_key": speaker_global_key,
        },
    }


def test_speaker_memory_is_visible_only_to_the_same_qq_user() -> None:
    current = _speaker_memory("onebot_v11:user:u1", "group:other")
    other = _speaker_memory("onebot_v11:user:u2", "group:g1")

    assert (
        memory_scope_rank(
            current,
            robot_id="robot-1",
            conversation_key="group:g1",
            speaker_global_key="onebot_v11:user:u1",
        )
        == 5
    )
    assert (
        memory_scope_rank(
            other,
            robot_id="robot-1",
            conversation_key="group:g1",
            speaker_global_key="onebot_v11:user:u1",
        )
        == -1
    )


def test_legacy_speaker_memory_without_user_key_stays_conversation_local() -> None:
    legacy = {
        "content": "legacy preference",
        "metadata": {
            "memory_type": "preference",
            "memory_scope": "speaker",
            "robot_id": "robot-1",
            "robot_conversation_key": "group:g1",
        },
    }

    assert (
        memory_scope_rank(
            legacy,
            robot_id="robot-1",
            conversation_key="group:g1",
            speaker_global_key="onebot_v11:user:u1",
        )
        == 3
    )
