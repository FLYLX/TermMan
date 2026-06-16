from __future__ import annotations

from typing import TYPE_CHECKING

from . import is_robot_plugin_enabled

if TYPE_CHECKING:
    from app.services.agent.agent import Agent


QQ_MCP_SKILL_ID = "qq_mcp"
ROBOT_MESSAGING_SKILL_ID = "robot_messaging"
ROBOT_MESSAGING_COMPAT_SKILL_IDS = {QQ_MCP_SKILL_ID, ROBOT_MESSAGING_SKILL_ID}

NO_QQ_REPLY_INSTRUCTION = (
    "- 如果 QQ 侧不需要回复，不要调用 `mcp_robot_send_message`；"
    "内部最终回复只返回 `[no_qq_reply]`。"
)

ROBOT_MESSAGING_PROMPT = (
    "QQ MCP Skill：\n\n"
    "这个 skill 提供 QQ 机器人 MCP 能力，不提供人格。\n"
    "需要向 QQ 发送可见消息时，调用 `mcp_robot_send_message`。\n"
    "只有用户明确询问历史、偏好、前文，或当前消息离开前文无法理解时，才读取当前 QQ 会话 .log 记忆。\n"
    "需要读取时调用 `mcp_robot_read_conversation_memory`，但不要为了判断本轮是否要回复或是否已经发送而读取旧 .log。\n"
    "群聊回复尽量短句、多条消息分次回，少用标点，尽量不要句号；"
    "长内容仍然只调用一次发送工具，发送层会拆成多条 QQ 消息分次发送。\n"
    "最终 assistant 文本是 TermMan 内部回复，不会自动发送到 QQ。"
)

ROBOT_ACTIVE_CONTEXT_PROMPT = (
    "当前 QQ 会话：\n"
    "- 本轮只由一个 QQ 群聊/私聊触发。\n"
    "- 只有发送者在叫机器人、延续/纠正机器人对话、请求有用回复，或用空 @/回复唤醒机器人时，才回复 QQ。\n"
    "- 回复 QQ 时，只调用 `mcp_robot_send_message` 并只传 `text`；不要传 "
    "`reply_to`、`conversation`、`broadcast`、`target_type`、`target_id`。\n"
    "- 群聊里别把一句话写太长；需要多说时，写成自然短句，少用标点，尽量不要句号，发送层会拆成多条 QQ 消息分次发送。\n"
    "- 当前轮优先根据这条 QQ 消息判断并发送；不要先读旧 .log 来确认是否该回复或是否已经发过。\n"
    "- 只有用户明确问历史/前文/偏好，或当前消息离开前文无法理解时，才调用 `mcp_robot_read_conversation_memory`，不要传目标参数。\n"
    "- 历史或 .log 里的 `Executing tool`、`Message sent`、`[no_qq_reply]` 只可能是旧内部轨迹，不是本轮发送结果。\n"
    "- 不要回复普通群聊闲聊或发给别人的消息。不要发送隐藏推理、工具轨迹、原始日志或长摘要。\n"
    f"{NO_QQ_REPLY_INSTRUCTION}"
)

ROBOT_BACKEND_CONTEXT_PROMPT = (
    "历史中的 QQ 上下文：\n"
    "- 只有明确选择当前 TermMan 上下文里可见的 QQ 会话时，才使用 `reply_to` 或 `conversation`。\n"
    "- 只有用户显式提供 QQ 群号或 QQ 号时，才使用 `target_type` 和 `target_id`。\n"
    "- QQ 目标或机器人身份缺失/歧义时，先询问。\n"
    "- 只有用户明确要求，或严重告警确实适用于所有选中 QQ 会话时，才 broadcast。"
)

ROBOT_REFLECTION_PROMPT = (
    "QQ 回复反思：\n"
    "- 调用 `mcp_robot_send_message` 前，先静默判断 QQ 是否真的需要收到回复。\n"
    "- @、回复机器人、活跃窗口触发只是候选延续，不等于自动允许发送。\n"
    f"{NO_QQ_REPLY_INSTRUCTION}"
)


def _robot_context(agent: Agent):
    return getattr(agent, "_context", None)


def _agent_has_robot_messaging_enabled(agent: Agent | None) -> bool:
    if agent is None:
        return False

    get_tools = getattr(agent, "get_tools_for_litellm", None)
    if callable(get_tools):
        try:
            tools = get_tools()
        except Exception:
            tools = []
        for tool in tools or []:
            if not isinstance(tool, dict):
                continue
            if tool.get("function", {}).get("name") == "mcp_robot_send_message":
                return True

    get_servers = getattr(agent, "get_mcp_servers", None)
    if callable(get_servers):
        try:
            if "robot" in set(get_servers() or []):
                return True
        except Exception:
            pass

    get_skills = getattr(agent, "get_skills", None)
    if callable(get_skills):
        try:
            skills = get_skills() or []
        except Exception:
            skills = []
        if any(
            getattr(skill, "skill_id", "") in ROBOT_MESSAGING_COMPAT_SKILL_IDS
            for skill in skills
        ):
            return True

    return False


def build_robot_messaging_prompt(agent: Agent | None = None) -> str:
    if not is_robot_plugin_enabled():
        return ""

    prompt_parts = [ROBOT_MESSAGING_PROMPT]
    context = _robot_context(agent) if agent is not None else None
    reply_context_summary = str(
        getattr(context, "robot_reply_context_summary", "") or ""
    ).strip()
    if reply_context_summary:
        prompt_parts.append(ROBOT_ACTIVE_CONTEXT_PROMPT)
        prompt_parts.append(reply_context_summary)

    return "\n\n".join(prompt_parts)


def build_robot_context_prompt(agent: Agent) -> str:
    context = _robot_context(agent)
    if context is None or not getattr(context, "robot_id", ""):
        return ""
    return build_robot_messaging_prompt(agent)


def build_robot_history_prompt(agent: Agent, *, has_robot_context: bool) -> str:
    if not has_robot_context:
        return ""
    context = _robot_context(agent)
    if context is not None and getattr(context, "robot_id", ""):
        return ""
    if not _agent_has_robot_messaging_enabled(agent):
        return ""
    return "\n\n".join([ROBOT_MESSAGING_PROMPT, ROBOT_BACKEND_CONTEXT_PROMPT])


def build_robot_delivery_reflection_prompt(final_response: str) -> str:
    if not is_robot_plugin_enabled():
        return ""

    return (
        "QQ 消息发送反思：\n"
        "你产出了最终回复，但没有调用 `mcp_robot_send_message`：\n"
        f"{final_response.strip()}\n\n"
        "重新判断 QQ 是否应该收到这段文本。"
        "如果当前 QQ 消息确实在叫机器人、延续/纠正机器人对话、请求有用回复，"
        "或显式唤醒机器人，就调用 `mcp_robot_send_message` 发送到锁定的当前 QQ 会话。"
        "如果只是普通群聊、发给别人、或 QQ 侧无需回复，不要调用工具；"
        "内部最终回复只返回 `[no_qq_reply]`。不要输出这段反思本身。"
    )


def build_robot_messaging_skill_definition():
    if not is_robot_plugin_enabled():
        return None

    from app.services.agent.skills.definition import (
        ActionConfig,
        SafetyConfig,
        SkillDefinition,
        TriggerConfig,
    )

    return SkillDefinition(
        skill_id=QQ_MCP_SKILL_ID,
        name="QQ MCP",
        description="允许助手通过 QQ 机器人 MCP 发送消息和读取会话 .log 记忆。",
        category="mcp",
        trigger=TriggerConfig(
            type="manual",
            patterns=[
                "qq",
                "QQ",
                "群",
                "群聊",
                "私信",
                "通知",
                "警告",
                "报警",
                "发消息",
                "发送消息",
                "robot",
                "nonebot",
                "napcat",
            ],
        ),
        action=ActionConfig(type="llm", prompt=ROBOT_MESSAGING_PROMPT),
        safety=SafetyConfig(
            requires_approval=False,
            risk_level="medium",
            max_retries=1,
            timeout=30,
        ),
        mcp_servers=["robot"],
        skill_dir="app/plugins/robot",
    )
