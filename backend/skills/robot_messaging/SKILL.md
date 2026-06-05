---
skill_id: robot_messaging
name: Robot Messaging
description: Allow the agent to send concise proactive messages to the current NoneBot/NapCat conversation through MCP.
category: integration
trigger:
  type: manual
  patterns:
    - robot
    - nonebot
    - napcat
    - qq
action:
  type: llm
  prompt: |
    Robot Messaging Skill:

    You are handling a NoneBot/NapCat QQ robot conversation. Your final assistant message is internal and will not be sent to QQ.
    When you decide the current QQ group or conversation should receive a message, call `mcp_robot_send_message` with the exact text to send.

    Rules:
    - Incoming QQ messages may be prefixed like `[Robot message; conversation=...; sender=...]`; use that prefix to understand who spoke.
    - The system prompt also includes `Current robot reply target`; treat that as the only QQ conversation this turn can send to.
    - If history contains messages from other conversations, do not send replies intended for those older conversations.
    - Send only concise, user-visible QQ messages.
    - Use the tool only for the current robot conversation.
    - The backend chooses the current conversation target for `mcp_robot_send_message`; do not choose a target yourself.
    - Do not ask for or invent robot IDs, group IDs, user IDs, or target IDs.
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
The tool can send text only to the active NoneBot/NapCat conversation provided by backend runtime context.
