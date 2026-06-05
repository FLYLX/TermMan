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
    - Decide which QQ conversation should receive the message from the user's request and the QQ message history.
    - When a suitable QQ conversation appears in the current context, call `mcp_robot_send_message` with `text` and, if more than one QQ conversation appears, a short `reply_to` reference such as the sender name or the conversation label. The backend resolves that context reference to the actual QQ target.
    - If the system prompt includes `Current robot reply target`, you are handling an incoming QQ robot conversation. Your final assistant message is internal and will not be sent to QQ; call the tool when QQ should receive a message. If the target should be the current QQ conversation, you may omit `reply_to`, `target_type`, and `target_id`.
    - If you are chatting in the TermMan backend, choose the target from the QQ context history. If the target is not present or ambiguous, ask which group/private chat to use.

    Rules:
    - Use `target_type` and `target_id` only when the target is outside the visible QQ context and the user explicitly supplied the group number or QQ number.
    - If multiple robots are available and the user specified which robot to use, pass `robot_id`; otherwise the backend can use the only accessible enabled robot.
    - If the target group/private conversation or robot identity is missing or ambiguous, ask for that value instead of saying you cannot send because there is no robot context.
    - If history contains messages from multiple QQ conversations, choose the one the user refers to; if unclear, ask which conversation to use.
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
