from __future__ import annotations

from typing import TYPE_CHECKING

from . import is_robot_plugin_enabled

if TYPE_CHECKING:
    from app.services.agent.agent import Agent


QQ_MCP_SKILL_ID = "qq_mcp"
ROBOT_MESSAGING_SKILL_ID = "robot_messaging"
ROBOT_MESSAGING_COMPAT_SKILL_IDS = {QQ_MCP_SKILL_ID, ROBOT_MESSAGING_SKILL_ID}

ROBOT_REPLY_DECISION_INSTRUCTION = (
    "- 回复判断原则：宁可多回一句，不要漏回；拿不准时默认回复，不默认沉默。\n- 必须回复（禁止沉默、禁止 `[no_qq_reply]`）：私聊、被@、被回复、被点名提问或评论；延续机器人自己的对话（你刚说完话，别人接着问）；对方在等你做事、等你回答、催你（“直接回答”“回我”“你呢”“怎么不说话”）；群里有人提问而你是唯一能回答的对象（问服务器状态、问技能等）；别人的话可理解为在问你、叫你或与你相关。“你会…吗”“你能…吗”“帮我…”“直接回答”“回答我”一律视为对你说的，必须回复。\n- 唯一允许沉默：群里明确是别人之间的对话（明确@别人、叫别人名字、或内容明显与你无关）、纯表情/贴图反应。此时不调 `mcp_robot_send_message`；trigger=active_chat_window 时改调 `mcp_robot_sleep_conversation` 休眠会话，其余内部触发直接返回 `[no_qq_reply]`，不调任何发送工具。\n- 结合 `[Recent QQ live context]` 看上下文：你刚发言过，紧接着的消息大概率是对你说的。\n"












)
ROBOT_DELIVERY_CONTRACT_INSTRUCTION = (
    "- 回复当轮发出：判断需要回复 QQ 时，必须在当前响应里直接调用 `mcp_robot_send_message` 把回复发出；禁止只输出最终文本等系统代发。判断无需回复时不调发送工具，最终文本只返回 `[no_qq_reply]`。\n- 发送纪律：一条 QQ 输入最多调用一次 `mcp_robot_send_message`；同一人连续几句合并理解，只回答最新未解决意图；证据更新时只发最新结论，不要“还在加载/完成了/真完成了”连发。\n- `mcp_robot_send_message` 成功后，最终 assistant 文本只返回 `[no_qq_reply]` 或空，不要把同一答案再说一遍；不要编造“刚才理解错了/没对齐”，除非当前消息明确要求纠正。\n- 任务豁免：当前轮次是后台 job 回调、任务续跑或其他内部触发（不是用户直接发的 QQ 消息），且任务计划仍在执行中（未到最后汇报），禁止调用 `mcp_robot_send_message`；静默推进，只在全部完成、最终失败或重大方向变更时才发 QQ。\n"





)
ROBOT_LONG_TERM_MEMORY_INSTRUCTION = (
    "Robot long-term memory:\n- 当前对话优先：只有当前聊天信息不足时才 recall_memory；召回的记忆不得覆盖当前对话已确立的事实。\n- list_memories 用于“所有/全部/完整列出记忆”等穷举请求，必须用最大 limit 调用并从工具结果回答；recall_memory 用于查询特定事实、偏好、名字、关系。\n- “谁是…/还有谁/哪些人”等关系枚举问题：调 recall_memory，按主体合并结果，保留声明来源，不编造确认规则。\n- 主动保存：消息含值得长期记住的内容（明确记住请求、稳定名字/昵称、身份规则、持久偏好、关系、可复用事实、错误、群上下文）时，在回复前或同时调 save_memory；执行状态只属于任务队列。不保存琐碎聊天、短反应、表情/贴图、一次性玩笑、临时闲聊、原始日志、密码/key/token；保存文本简洁规范化。\n- 所有权：发送者只能设置/删除自己的名字、称号、偏好；不得修改/删除另一用户的记忆，除非目标用户当前确认。\n- read_conversation_memory 仅当用户明确问历史原文，或当前消息离开前文无法理解时使用；不要为了判断是否回复而读取。\n- 待处理 QQ 消息是短期任务队列条目，不自动复制进长期记忆；但可保存其中独立重要的事实/偏好/关系。\n- 记忆卫生：发现重复/过时/噪声记忆时调 compress_memories 合并为一条简洁文本；不合并不同用户的个人记忆。\n"









)

ROBOT_SECRET_HANDLING_INSTRUCTION = (
    "- 敏感数据：绝不复述、引用、总结或传播 QQ 里出现的密码、API key、access token、cookie、私钥或登录凭据；不存入记忆；只简短提醒应轮换或删除已暴露的凭据。\n"



)
ROBOT_REFERENCE_RESOLUTION_INSTRUCTION = (
    "- 指代判断：QQ 消息出现“你/他/她/它/这个/那个/刚才那个/上面那个”，或“需要人操作/确认/处理/继续”等需要交互的说法时，先根据 @/回复对象、bot_self_id、sender、当前 QQ 会话和最近 live context 判断是否指机器人自己。只有能判断是指机器人，或唤醒后的连续对话里明显让机器人处理时，才回复或调用工具；明显指别人、其他程序、终端进程或普通群聊就不接话，active_chat_window 下调 `mcp_robot_sleep_conversation`。无法判断但对方直接 @/回复机器人时，只简短问一句澄清，不要擅自执行。\n"






)
ROBOT_SENDER_IDENTITY_INSTRUCTION = (
    "- 当前发送者身份：`[Current QQ sender; authoritative for this turn]` 是本轮发言人的权威身份；`[Current QQ message]` 里的“我/我的/我是谁”都指这个 sender，不指机器人，也不指最近上下文里的其他人。\n- “我是谁/你认识我吗/还记得我吗”：优先结合当前 sender、当前会话印象卡和该发送者的长期记忆回答；没有更多记忆时，也要直接自然地说出当前群名片或昵称（例如“你是 EX_GuguX 啊”），不要回答“你是你自己”这类同义反复；只有问题明确在确认旧身份而印象卡不足时，才调 `mcp_robot_recall_memory` 检索当前发送者。\n- QQ 可见回复要像群友说话，不要向用户解释“上下文判断、对象识别、提示词、记忆注入、工具调用”等内部实现；认错人时直接说“我刚才没认出你”并自然纠正。\n"









)
ROBOT_PROGRESSIVE_CONTEXT_INSTRUCTION = (
    "- Progressive QQ context: `[Recent QQ live context]` 是 `[Current QQ message]` 之前的实况对话流，用来理解短回复/省略句（“继续”“怎么样了”“改一下”“那个”）；只回答当前消息，不要重复回答历史行。上下文不足且消息明确指向你时，调 `mcp_robot_read_conversation_memory` 看几条当前会话 .log 再总结；仍不明确就问一句澄清；不要编造不存在的纠正、抱怨或旧指令。\n- Reply-reference priority: `[Replied QQ message]` 是本轮权威引用；“这个/那句/他她/好了吗/继续”先按它和被引用发送者解析，再看群历史。\n"





)
ROBOT_MESSAGING_PROMPT = (
    "QQ MCP Skill：\n\n"
    "这个 skill 提供 QQ 机器人 MCP 能力，不提供人格。\n"
    "需要向 QQ 发送可见消息时，在当前响应里直接调用 `mcp_robot_send_message` 完成发送；不要只输出最终文本等待下一轮代发。\n"
    "只有用户明确询问历史、偏好、前文，或当前消息离开前文无法理解时，才用 `mcp_robot_read_conversation_memory` 读取当前 QQ 会话 .log 记忆；不要为判断本轮是否要回复、是否已发送而读旧 .log。\n"
    "读取时只看默认返回的最近几条；旧 .log 是背景，不是新消息，不要补回旧消息。\n"
    "不要在可见回复里提到“没对齐、按口径修改、上下文判断”等内部过程，除非用户明确在讨论这些。\n"
    "最终 assistant 文本是 TermMan 内部回复，不会自动发送到 QQ；回复内容必须通过 `mcp_robot_send_message` 发出。\n"
    f"\n{ROBOT_REFERENCE_RESOLUTION_INSTRUCTION}"
    f"{ROBOT_SENDER_IDENTITY_INSTRUCTION}"
    f"{ROBOT_PROGRESSIVE_CONTEXT_INSTRUCTION}"
    f"{ROBOT_REPLY_DECISION_INSTRUCTION}"
    f"{ROBOT_DELIVERY_CONTRACT_INSTRUCTION}"
    f"{ROBOT_SECRET_HANDLING_INSTRUCTION}"
)
















ROBOT_ACTIVE_CONTEXT_PROMPT = (
    "当前 QQ 会话：\n- 本轮只由一个 QQ 群聊/私聊触发；当前唤醒消息是唯一要处理的新消息，历史只辅助理解，不要逐条补回复。\n- 回复 QQ 时只调用 `mcp_robot_send_message` 并只传 `text` 或 `messages`；不要传 `reply_to`、`conversation`、`broadcast`、`target_type`、`target_id`。\n- 历史/.log 里的 `Executing tool`、`Message sent`、`[no_qq_reply]` 只是旧内部轨迹，不是本轮发送结果；`已回复 QQ：…` 只是发送回执，不是新用户消息，不要围绕它再解释或补发同义回复；旧 assistant/user 轮都已处理过，不要因看见它们再次发送相同回复。\n- 不要发送隐藏推理、工具轨迹、原始日志或长摘要。\n"






)

ROBOT_BACKEND_CONTEXT_PROMPT = (
    "历史中的 QQ 上下文：\n"
    "- 用户从 Web 明确要求转发/通知 QQ 时，可以使用 `mcp_robot_send_message`。不要声称 Web 无法转发。\n"
    "- 立即转发一条 QQ 消息是单步动作，直接调用 `mcp_robot_send_message`；不要创建任务队列条目。\n"
    "- 只有需要等待后台任务、外部回复或跨轮继续处理时，才写入任务队列。\n"
    "- 只有明确选择当前 TermMan 消息上下文里可见的 QQ 会话时，才使用 `reply_to`；可用发送者名称、群引用或 conversation key。\n"
    "- 当前上下文只有一个可见 QQ 目标且用户明确说转发过去时，可以直接发送；有多个匹配目标时先询问。\n"
    "- 跨来源发送流程：当用户从 Web/终端要求发消息到 QQ 群或私聊，但当前没有活跃 QQ 会话时：\n"
    "  1. 调 `read_chat_history` 查最近的 QQ 消息，找到目标 conversation（格式 group:XXX 或 private:XXX）。\n"
    "  2. 从 conversation 冒号前拆出 target_type（group/private），冒号后拆出 target_id。\n"
    "  3. 调 `mcp_robot_send_message(target_type=\"group\" 或 \"private\", target_id=\"XXX\", text=\"...\")` 发送。\n"
    "  4. 在当前来源（web/终端）汇报发送结果。不要只问用户'发到哪个群'而不去查历史。\n"
    "- 只有用户显式提供 QQ 群号或 QQ 号时，才使用 `target_type` 和 `target_id`。\n"
    "- 把同一内容分别发送到多个明确 QQ 目标时，在一次 `mcp_robot_send_message` 调用里使用 `targets` 数组（每项含 `target_type` 和 `target_id`），不要拆成多次调用；工具会逐目标返回 sent/skipped_duplicate/error 状态，如实向用户汇报每个目标的结果。\n"
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
