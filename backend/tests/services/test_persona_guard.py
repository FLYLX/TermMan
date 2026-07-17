from types import SimpleNamespace

from app.services.agent.persona_guard import (
    YUI_IDENTITY_REPLIES,
    enforce_persona_identity_response,
    enforce_persona_identity_robot_tool_args,
    persona_identity_reply,
)


def _agent(*skill_ids: str):
    return SimpleNamespace(
        get_skills=lambda: [SimpleNamespace(skill_id=skill_id) for skill_id in skill_ids]
    )


def test_yui_identity_question_replaces_meta_persona_reply() -> None:
    agent = _agent("hirasawa_yui_persona")
    message = (
        "[Robot message; conversation=private:2537134688]\n"
        "[Current QQ message]\n说起来你是谁啊"
    )

    rewritten = enforce_persona_identity_response(
        agent,
        message,
        "我先说人设啦，我是平泽唯。能帮你打理终端和服务器。",
    )

    assert rewritten in YUI_IDENTITY_REPLIES
    assert "人设" not in rewritten
    assert "终端" not in rewritten
    assert "服务器" not in rewritten


def test_yui_identity_question_rewrites_robot_messages_payload_to_one_reply() -> None:
    agent = _agent("hirasawa_yui_persona")

    args = enforce_persona_identity_robot_tool_args(
        agent,
        "[Current QQ message]\n[CQ:at,qq=2900669542] 你叫什么名字？",
        {"messages": ["我是一个机器人", "我能管理终端"]},
    )

    assert args["text"] in YUI_IDENTITY_REPLIES
    assert "messages" not in args


def test_yui_identity_guard_does_not_rewrite_embedded_question_for_someone_else() -> None:
    agent = _agent("hirasawa_yui_persona")

    assert persona_identity_reply(agent, "你问问汉堡你是谁") is None
    assert persona_identity_reply(agent, "你使用的是什么模型") is None


def test_identity_guard_is_inactive_without_yui_persona() -> None:
    agent = _agent("terminal_mcp")

    assert persona_identity_reply(agent, "你是谁啊") is None
    assert enforce_persona_identity_response(agent, "你是谁啊", "原回复") == "原回复"
