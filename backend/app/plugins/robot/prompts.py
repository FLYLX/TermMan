from __future__ import annotations

from typing import TYPE_CHECKING

from . import is_robot_plugin_enabled

if TYPE_CHECKING:
    from app.services.agent.agent import Agent


QQ_MCP_SKILL_ID = "qq_mcp"
ROBOT_MESSAGING_SKILL_ID = "robot_messaging"
ROBOT_MESSAGING_COMPAT_SKILL_IDS = {QQ_MCP_SKILL_ID, ROBOT_MESSAGING_SKILL_ID}

ROBOT_REPLY_DECISION_INSTRUCTION = (
    "- 回复判断核心原则：宁可多回一句，不要漏回。拿不准时默认回复，不默认沉默。\n"
    "- 必须回复（禁止沉默、禁止 `[no_qq_reply]`）：\n"
    "  · 私聊、被 @、被回复、被点名提问或评理\n"
    "  · 延续机器人自己的对话（你刚说完话，别人接着问了一句）\n"
    "  · 对方在等你做事、等你回答、催你（“直接回答”“回我”“你呢”“怎么不说话”）\n"
    "  · 群聊里有人提了一个问题，而你是唯一能回答的对象（比如问服务器状态、问你会不会某个技能）\n"
    "  · 别人的话可以理解为在问你、叫你、或跟你相关\n"
    "- 唯一允许沉默：群聊里明确是别人之间的对话（有明确 @其他人、叫了其他人名字、\n"
    "  或内容明显与你无关）、纯表情/贴图反应。此时不调用 `mcp_robot_send_message`，\n"
    "  	rigger=active_chat_window ?????mcp_robot_sleep_conversation????????n"
    "  ??????????[no_qq_reply]??????????????????????????n"
    "- 判断技巧：结合 `[Recent QQ live context]` 看上下文。如果你刚发言过，紧接着的消息大概率是对你说的。\n"
    "  “你会…吗”“你能…吗”“帮我…”“直接回答”“回答我”这类表达一律视为对你说的，必须回复。\n"
)
ROBOT_DELIVERY_CONTRACT_INSTRUCTION = (
    "- 发送纪律：一条 QQ 输入最多调用一次 `mcp_robot_send_message`；"
    "同一人连续几句合并理解，只回答最新未解决意图；"
    "证据更新时只发最新结论，不要“还在加载/完成了/真完成了”连发。\n"
    "- `mcp_robot_send_message` 成功后，最终 assistant 文本只返回 `[no_qq_reply]` 或空，"
    "不要把同一答案再说一遍；不要编造“刚才理解错了/没对齐”，除非当前消息明确要求纠正。\n"
    "- 任务工作流豁免：当前轮次如果是后台 job 回调、任务续跑、或其他内部触发（不是用户直接发的 QQ 消息），" "且任务工作流仍在执行中（未到汇报步骤），禁止调用 `mcp_robot_send_message`。" "静默推进 workflow，只在汇报步骤、最终失败、或重大方向变更时才发 QQ。\n"
)
ROBOT_LONG_TERM_MEMORY_INSTRUCTION = (
    "Robot long-term memory:\n"
    "- 当前对话优先：只有当前聊天信息不足时才 recall_memory；召回的记忆不得覆盖当前对话已确立的事实。\n"
    "- list_memories 用于“所有/全部/完整列出记忆”等穷举请求，必须用最大 limit 调用并从工具结果回答；recall_memory 用于查询特定事实、偏好、名字、关系。\n"
    "- “谁是…/还有谁/哪些人”等关系枚举问题：调 recall_memory，按主体合并结果，保留声明来源，不编造确认规则。\n"
    "- 主动保存：当 QQ 消息含值得长期记住的内容（明确记住请求、稳定名字/昵称、身份规则、持久偏好、关系、可复用事实、错误、群上下文）时，在回复前或同时调 save_memory。执行状态只属于任务队列。\n"
    "- 所有权：发送者只能设置/删除自己的名字、称号、偏好；不允许一个用户修改/删除另一个用户的记忆，除非目标用户当前确认。\n"
    "- 不保存：琐碎聊天、短反应、表情/贴图、一次性玩笑、临时闲聊、原始日志、密码/key/token。保存时用简洁规范化文本。\n"
    "- read_conversation_memory 仅用于用户明确问历史原文或当前消息离开前文无法理解时；不要为了判断是否回复而读取。\n"
    "- 待处理 QQ 消息是短期任务队列条目，不自动复制进长期记忆；但可保存其中独立重要的事实/偏好/关系。\n"
    "- 记忆卫生：发现重复/过时/噪声记忆时调 compress_memories 合并为一条简洁文本；不合并不同用户的个人记忆。"
)

ROBOT_SECRET_HANDLING_INSTRUCTION = (
    "- Sensitive-data rule: never repeat, quote, summarize, or broadcast passwords, "
    "API keys, access tokens, cookies, private keys, or login credentials posted in "
    "QQ. Do not save them to memory. Briefly warn that the exposed credential should "
    "be rotated or deleted instead of echoing it back.\n"
)
ROBOT_REFERENCE_RESOLUTION_INSTRUCTION = (
    "- \u6307\u4ee3\u5224\u65ad\uff1a\u5f53 QQ \u6d88\u606f\u91cc\u51fa\u73b0\u201c\u4f60/\u4ed6/\u5979/\u5b83/\u8fd9\u4e2a/\u90a3\u4e2a/\u521a\u624d\u90a3\u4e2a/\u4e0a\u9762\u90a3\u4e2a\u201d\u3001"
    "\u6216\u8005\u201c\u9700\u8981\u4eba\u64cd\u4f5c/\u786e\u8ba4/\u5904\u7406/\u7ee7\u7eed\u201d\u7b49\u9700\u8981\u4ea4\u4e92\u7684\u8bf4\u6cd5\u65f6\uff0c\u5148\u6839\u636e @/\u56de\u590d\u5bf9\u8c61\u3001"
    "bot_self_id\u3001sender\u3001\u5f53\u524d QQ \u4f1a\u8bdd\u548c\u6700\u8fd1 live context \u5224\u65ad\u662f\u4e0d\u662f\u5728\u6307\u673a\u5668\u4eba\u81ea\u5df1\u3002"
    "\u53ea\u6709\u80fd\u5224\u65ad\u662f\u6307\u673a\u5668\u4eba\uff0c\u6216\u5728\u5524\u9192\u540e\u7684\u8fde\u7eed\u5bf9\u8bdd\u91cc\u660e\u663e\u8ba9\u673a\u5668\u4eba\u5904\u7406\u65f6\uff0c\u624d\u56de\u590d\u6216\u8c03\u7528\u5de5\u5177\uff1b"
    "\u5982\u679c\u660e\u663e\u6307\u522b\u4eba\u3001\u5176\u4ed6\u7a0b\u5e8f\u3001\u7ec8\u7aef\u8fdb\u7a0b\u6216\u666e\u901a\u7fa4\u804a\uff0c\u5c31\u4e0d\u8981\u63a5\u8bdd\uff0cactive_chat_window \u4e0b\u8c03\u7528 "
    "`mcp_robot_sleep_conversation`\u3002\u5982\u679c\u65e0\u6cd5\u5224\u65ad\u4f46\u5bf9\u65b9\u76f4\u63a5 @/\u56de\u590d\u673a\u5668\u4eba\uff0c\u53ea\u80fd\u7b80\u77ed\u95ee\u4e00\u53e5\u6f84\u6e05\uff0c"
    "\u4e0d\u8981\u64c5\u81ea\u6267\u884c\u3002\n"
)
ROBOT_SENDER_IDENTITY_INSTRUCTION = (
    "- 当前发送者身份：`[Current QQ sender; authoritative for this turn]` "
    "是本轮发言人的权威身份。`[Current QQ message]` 里的“我/我的/我是谁”"
    "都指这个 sender，不指机器人，也不指最近上下文里的其他人。\n"
    "- 遇到“我是谁/你认识我吗/还记得我吗”这类问题，优先结合当前 sender、"
    "当前会话印象卡和该发送者的长期记忆回答。没有更多记忆时，也要直接自然地"
    "说出当前群名片或昵称，例如“你是 EX_GuguX 啊”；不要回答“你是你自己”"
    "这类同义反复。如果问题明确在确认旧身份而印象卡不足，再调用 "
    "`mcp_robot_recall_memory` 检索当前发送者。\n"
    "- QQ 可见回复要像群友说话。不要向用户解释“上下文判断、对象识别、提示词、"
    "记忆注入、工具调用”等内部实现；认错人时直接说“我刚才没认出你”并自然纠正。\n"
)
ROBOT_PROGRESSIVE_CONTEXT_INSTRUCTION = (
    "- Progressive QQ context: treat `[Recent QQ live context]` as the live chat "
    "thread immediately before `[Current QQ message]`. Use it to resolve short "
    "or elliptical follow-ups such as 'continue', 'what about it', 'is it done', "
    "'change it', 'that one', and task-status questions. Answer only the current "
    "or pending current messages; never re-answer old recent-context lines. If "
    "recent context is still insufficient and the current message is directed at "
    "the bot, read a few current-conversation `.log` lines with "
    "`mcp_robot_read_conversation_memory`, then summarize instead of pasting raw logs. "
    "If the same-conversation log still does not establish a clear referent or request, "
    "ask one brief clarification. Never invent a hidden correction, complaint, alignment "
    "issue, or prior instruction merely to make an ambiguous short message sound meaningful.\n"
    "- Reply-reference priority: when `[Replied QQ message]` is present, it is the "
    "authoritative quoted message for this turn. Resolve phrases such as 'this', "
    "'that sentence', 'he/she', 'is it done', or 'continue' against its quoted text "
    "and quoted sender before using broader group history. Keep the current sender "
    "separate from the quoted sender, and answer only the current message.\n"
)
ROBOT_MESSAGING_PROMPT = (
    "QQ MCP Skill：\n\n"
    "这个 skill 提供 QQ 机器人 MCP 能力，不提供人格。\n"
    "需要向 QQ 发送可见消息时，调用 `mcp_robot_send_message`。\n"
    "只有用户明确询问历史、偏好、前文，或当前消息离开前文无法理解时，才读取当前 QQ 会话 .log 记忆。\n"
    "需要读取时调用 `mcp_robot_read_conversation_memory`，但不要为了判断本轮是否要回复或是否已经发送而读取旧 .log。\n"
    "读取时只看默认返回的最近几条；旧 .log 是背景，不是新消息，不要补回旧消息。\n"
    "不要在可见回复里提到“没对齐、按口径修改、上下文判断”等内部过程，除非用户明确在讨论这些内容。\n"
    "最终 assistant 文本是 TermMan 内部回复，不会自动发送到 QQ。"
    f"\n{ROBOT_REFERENCE_RESOLUTION_INSTRUCTION}"
    f"{ROBOT_SENDER_IDENTITY_INSTRUCTION}"
    f"{ROBOT_PROGRESSIVE_CONTEXT_INSTRUCTION}"
    f"{ROBOT_REPLY_DECISION_INSTRUCTION}"
    f"{ROBOT_DELIVERY_CONTRACT_INSTRUCTION}"
    f"{ROBOT_SECRET_HANDLING_INSTRUCTION}"
)

ROBOT_ACTIVE_CONTEXT_PROMPT = (
    "当前 QQ 会话：\n"
    "- 本轮只由一个 QQ 群聊/私聊触发；当前唤醒消息是唯一要处理的新消息，历史只辅助理解，不要逐条补回复。\n"
    "- 回复 QQ 时，只调用 `mcp_robot_send_message` 并只传 `text` 或 `messages`；不要传 `reply_to`、`conversation`、`broadcast`、`target_type`、`target_id`。\n"
    "- 历史或 .log 里的 `Executing tool`、`Message sent`、`[no_qq_reply]` 只可能是旧内部轨迹，不是本轮发送结果。\n"
    "- 历史或 TermMan 里的 `已回复 QQ：...` 只是发送回执，不是新的用户消息；不要围绕它再解释或补发同义回复。\n"
    "- 历史或 .log 里的旧 assistant/user 轮次都已经处理过，不要因为看见它们再次发送相同回复。\n"
    "- 不要发送隐藏推理、工具轨迹、原始日志或长摘要。"
)

ROBOT_BACKEND_CONTEXT_PROMPT = (
    "历史中的 QQ 上下文：\n"
    "- 用户从 Web 明确要求转发/通知 QQ 时，可以使用 `mcp_robot_send_message`。不要声称 Web 无法转发。\n"
    "- 立即转发一条 QQ 消息是单步动作，直接调用 `mcp_robot_send_message`；不要创建任务队列条目。\n"
    "- 只有需要等待后台任务、外部回复或跨轮继续处理时，才写入任务队列。\n"
    "- 只有明确选择当前 TermMan 消息上下文里可见的 QQ 会话时，才使用 `reply_to`；可用发送者名称、群引用或 conversation key。\n"
    "- 当前上下文只有一个可见 QQ 目标且用户明确说转发过去时，可以直接发送；有多个匹配目标时先询问。\n"
    "- 只有用户显式提供 QQ 群号或 QQ 号时，才使用 `target_type` 和 `target_id`。\n"
    "- QQ 目标或机器人身份缺失/歧义时，先询问。\n"
    "- 不要把密码、API key、token、cookie、私钥或登录凭据转发到 QQ；提醒用户撤回并更换凭据。\n"
    "- 只有用户明确要求，或严重告警确实适用于所有选中 QQ 会话时，才 broadcast。"
)

ROBOT_REFLECTION_PROMPT = (
    "QQ 回复反思：\n"
    "- 调用 `mcp_robot_send_message` 前，先静默判断 QQ 是否真的需要收到回复。\n"
    "- @、回复机器人、活跃窗口触发只是候选延续，不等于自动允许发送。\n"
    "- 如果本轮已经调用过 `mcp_robot_send_message`，不要再把同一结论作为最终文本交给 fallback 发送。\n"
    f"{ROBOT_REFERENCE_RESOLUTION_INSTRUCTION}"
    f"{ROBOT_SENDER_IDENTITY_INSTRUCTION}"
    f"{ROBOT_REPLY_DECISION_INSTRUCTION}"
    f"{ROBOT_DELIVERY_CONTRACT_INSTRUCTION}"
    f"{ROBOT_SECRET_HANDLING_INSTRUCTION}"
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


def build_robot_delivery_reflection_prompt(final_response: str, *, workflow_active: bool = False) -> str:
    if not is_robot_plugin_enabled():
        return ""
    if workflow_active:
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
        f"{ROBOT_REFERENCE_RESOLUTION_INSTRUCTION}"
        f"{ROBOT_SENDER_IDENTITY_INSTRUCTION}"
        f"{ROBOT_REPLY_DECISION_INSTRUCTION}"
        f"{ROBOT_DELIVERY_CONTRACT_INSTRUCTION}"
        f"{ROBOT_SECRET_HANDLING_INSTRUCTION}"
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
