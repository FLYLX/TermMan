---
skill_id: robot_messaging
name: Robot Messaging
description: Allow the agent to send concise proactive messages through the NoneBot/NapCat QQ robot by MCP.
category: integration
trigger:
  type: manual
  patterns:
    - robot
    - nonebot
    - napcat
    - qq
    - QQ
    - 群
    - 群聊
    - 私信
    - 通知
    - 告警
    - 报错
    - 发消息
    - 发送消息
action:
  type: llm
  prompt: |
    Robot Messaging Skill:

    You can send concise user-visible messages through the TermMan NoneBot/NapCat QQ robot by calling `mcp_robot_send_message`.

    Target selection:
    - Incoming QQ messages are shown in context with their source conversation and sender, for example a group conversation or a private conversation.
    - Decide whether QQ should receive a message. Your final assistant message is internal to TermMan and will not be sent to QQ.
    - If the system prompt includes `Current robot reply target`, you are handling an incoming QQ robot conversation. To reply to that current QQ conversation, call `mcp_robot_send_message` with only `text`; omit `reply_to`, `target_type`, and `target_id`.
    - Use `reply_to` only when intentionally choosing a different QQ conversation visible in context. The backend resolves that context reference to the actual QQ target.
    - If you are chatting in the TermMan backend, choose the target from the QQ context history. If the target is not present or ambiguous, ask which group/private chat to use.
    - For severe terminal alerts, if multiple QQ conversations are visible and they should all receive the same concise alert, call `mcp_robot_send_message` with `broadcast: true` and `text`.

    Rules:
    - Use `target_type` and `target_id` only when the target is outside the visible QQ context and the user explicitly supplied the group number or QQ number.
    - If multiple robots are available and the user specified which robot to use, pass `robot_id`; otherwise the backend can use the only accessible enabled robot.
    - If the target group/private conversation or robot identity is missing or ambiguous, ask for that value instead of saying you cannot send because there is no robot context.
    - If history contains messages from multiple QQ conversations, choose the one the user refers to; if unclear, ask which conversation to use, except for explicit severe alert broadcasts where `broadcast: true` is appropriate.
    - Send only concise, user-visible QQ messages.
    - Do not invent robot IDs, group IDs, QQ numbers, or target IDs.
    - Do not send hidden reasoning, tool traces, raw terminal logs, or long summaries.
    - If no QQ-side reply is needed, do not call the tool.
safety:
  requires_approval: false
  risk_level: medium
  max_retries: 1
  timeout: 30
mcp_servers:
  - robot
tools:
  - mcp_robot_send_message
---

# Robot Messaging

This optional skill exposes a robot messaging MCP tool to the agent.
The tool can send text to the active NoneBot/NapCat conversation, to a QQ conversation resolved from visible chat context, or to an explicit QQ group/private target supplied by the user.
