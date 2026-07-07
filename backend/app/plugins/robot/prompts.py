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

ROBOT_LONG_TERM_MEMORY_INSTRUCTION = (
    "Robot long-term memory:\n"
    "- Use `mcp_robot_recall_memory` for stable facts, user preferences, tasks, errors, reusable context, names, habits, and remembered instructions.\n"
    "- When a live QQ message contains something worth remembering long term, call `mcp_robot_save_memory` proactively before or alongside the normal QQ reply. Save explicit remember requests, stable names/nicknames, bot identity/name rules, durable user preferences, relationships, ongoing tasks, reusable facts, and recurring group context.\n"
    "- Do not save trivial chat, short reactions, images/stickers, one-off jokes, temporary market chatter, raw logs, or sensitive secrets. Prefer concise normalized memory text instead of copying the whole message.\n"
    "- Use `mcp_robot_read_conversation_memory` only for raw current QQ .log when the user explicitly asks about exact previous chat or the current message cannot be understood without recent chat lines.\n"
    "- Do not read either memory tool just to decide whether to reply. First decide from the current QQ message and the wake/sleep rules.\n"
)
ACTIVE_CHAT_WINDOW_SLEEP_INSTRUCTION = (
    "- For a QQ `trigger=active_chat_window` turn, this group/private chat is "
    "only in a short judgement window after the bot was woken. If the current "
    "message is ordinary group chatter, is aimed at someone else, or is not "
    "continuing the bot conversation, call `mcp_robot_sleep_conversation` with "
    "no arguments. Do not call `mcp_robot_send_message`, and do not answer with "
    "a visible explanation. This closes the current robot conversation "
    "controller until someone wakes the bot again by @ or reply.\n"
)
ROBOT_MESSAGING_PROMPT = (
    "QQ MCP Skill：\n\n"
    "这个 skill 提供 QQ 机器人 MCP 能力，不提供人格。\n"
    "需要向 QQ 发送可见消息时，调用 `mcp_robot_send_message`。\n"
    "只有用户明确询问历史、偏好、前文，或当前消息离开前文无法理解时，才读取当前 QQ 会话 .log 记忆。\n"
    "需要读取时调用 `mcp_robot_read_conversation_memory`，但不要为了判断本轮是否要回复或是否已经发送而读取旧 .log。\n"
    "读取时只看默认返回的最近几条；旧 .log 是背景，不是新消息，不要补回旧消息。\n"
    "群聊回复像正常人聊天：有语气、有停顿，但别嘴碎；多数情况发一条消息就够。"
    "只有自然追一句、补一句时，才用 `messages` 数组分 2 到 3 条发；"
    "每条都要像一句自然的话，不要拆成电报式碎片。"
    "群聊单条 `text` 不要超过 36 个字；更长就必须用 `messages` 自己分成几条自然消息。"
    "不要在单条 QQ 消息里写空行、回车段落或多个信息块；多个信息点用 `messages` 的多个元素。\n"
    "最终 assistant 文本是 TermMan 内部回复，不会自动发送到 QQ。"
)

ROBOT_ACTIVE_CONTEXT_PROMPT = (
    "当前 QQ 会话：\n"
    "- 本轮只由一个 QQ 群聊/私聊触发。\n"
    "- 只有发送者在叫机器人、延续/纠正机器人对话、请求有用回复，或用空 @/回复唤醒机器人时，才回复 QQ。\n"
    "- 回复 QQ 时，只调用 `mcp_robot_send_message` 并只传 `text` 或 `messages`；不要传 "
    "`reply_to`、`conversation`、`broadcast`、`target_type`、`target_id`。\n"
    "- 群聊里别把一句话写太长，但也别嘴碎；多数情况发一条消息。需要自然追一句、补一句时，用 `messages` 数组分 2 到 3 条发。\n"
    "- 群聊单条 `text` 不要超过 36 个字；更长就必须用 `messages` 自己分成几条自然消息。\n"
    "- 不要在单条 QQ 消息里写空行、回车段落或多个信息块；多个信息点用 `messages` 的多个元素。\n"
    "- 当前轮优先根据这条 QQ 消息判断并发送；不要先读旧 .log 来确认是否该回复或是否已经发过。\n"
    "- 当前唤醒消息是本轮唯一要处理的新消息；历史只辅助理解，不要对历史逐条补回复。\n"
    "- 只有用户明确问历史/前文/偏好，或当前消息离开前文无法理解时，才调用 `mcp_robot_read_conversation_memory`，不要传目标参数。\n"
    "- 读取 .log 时只使用返回的最新几条作为背景；不要把旧 user 行当成当前还没处理的新消息。\n"
    "- 历史或 .log 里的 `Executing tool`、`Message sent`、`[no_qq_reply]` 只可能是旧内部轨迹，不是本轮发送结果。\n"
    "- 历史或 .log 里的旧 assistant/user 轮次都已经处理过，不要因为看见它们再次发送相同回复。\n"
    "- 不要回复普通群聊闲聊或发给别人的消息。不要发送隐藏推理、工具轨迹、原始日志或长摘要。\n"
    f"{ACTIVE_CHAT_WINDOW_SLEEP_INSTRUCTION}"
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
    f"{ACTIVE_CHAT_WINDOW_SLEEP_INSTRUCTION}"
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

    prompt_parts = [ROBOT_MESSAGING_PROMPT, ROBOT_LONG_TERM_MEMORY_INSTRUCTION]
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
    return "\n\n".join([ROBOT_MESSAGING_PROMPT, ROBOT_LONG_TERM_MEMORY_INSTRUCTION, ROBOT_BACKEND_CONTEXT_PROMPT])


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
        "内部最终回复只返回 `[no_qq_reply]`。不要输出这段反思本身。\n"
        "For `trigger=active_chat_window`, if this is ordinary group chatter or not for the bot, "
        "call `mcp_robot_sleep_conversation` with no arguments instead of returning only `[no_qq_reply]`."
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
        action=ActionConfig(type="llm", prompt="\n\n".join([ROBOT_MESSAGING_PROMPT, ROBOT_LONG_TERM_MEMORY_INSTRUCTION])),
        safety=SafetyConfig(
            requires_approval=False,
            risk_level="medium",
            max_retries=1,
            timeout=30,
        ),
        mcp_servers=["robot"],
        skill_dir="app/plugins/robot",
    )
