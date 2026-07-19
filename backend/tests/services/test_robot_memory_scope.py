from app.plugins.robot.memory_scope import memory_scope_for_content, memory_scope_rank


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


def test_third_party_identity_fact_is_shared_inside_conversation() -> None:
    content = (
        "New+7 (2206406352): \u732b\u5a18\u662f\u5979 @QQ(3385417251) "
        "\u5979\u5c31\u662f\u6708\u5f71\u6c49\u5821\u732b\u5a18"
    )

    assert memory_scope_for_content(content, "fact") == "conversation"
    assert (
        memory_scope_for_content(
            "FLY (2537134688): \u6211\u53eb\u72d7\u5b9dsama",
            "fact",
        )
        == "speaker"
    )


def test_legacy_speaker_scoped_relation_fact_is_recovered_for_group() -> None:
    memory = {
        "content": (
            "New+7 (2206406352): \u732b\u5a18\u662f\u5979 @QQ(3385417251) "
            "\u5979\u5c31\u662f\u6708\u5f71\u6c49\u5821\u732b\u5a18"
        ),
        "metadata": {
            "memory_type": "fact",
            "memory_scope": "speaker",
            "robot_id": "robot-1",
            "robot_conversation_key": "group:770362397",
            "speaker_global_key": "onebot_v11:user:2206406352",
        },
    }

    assert (
        memory_scope_rank(
            memory,
            robot_id="robot-1",
            conversation_key="group:770362397",
            speaker_global_key="onebot_v11:user:2537134688",
        )
        == 4
    )


def test_same_group_speaker_scoped_fact_is_visible_to_other_group_members() -> None:
    memory = {
        "content": "和煦的糖果风 (641681910): 我是猫娘",
        "metadata": {
            "memory_type": "fact",
            "memory_scope": "speaker",
            "robot_id": "robot-1",
            "robot_conversation_key": "group:770362397",
            "speaker_global_key": "onebot_v11:user:641681910",
        },
    }

    assert (
        memory_scope_rank(
            memory,
            robot_id="robot-1",
            conversation_key="group:770362397",
            speaker_global_key="onebot_v11:user:2537134688",
        )
        == 4
    )
    assert (
        memory_scope_rank(
            memory,
            robot_id="robot-1",
            conversation_key="group:other",
            speaker_global_key="onebot_v11:user:2537134688",
        )
        == -1
    )
