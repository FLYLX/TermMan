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
    You may use `mcp_robot_send_message` only when a message should be sent to the current NoneBot/NapCat conversation.

    Rules:
    - Send only concise, user-visible updates.
    - Use this tool only for the current robot conversation.
    - Do not ask for or invent robot IDs, group IDs, user IDs, or target IDs.
    - Do not send terminal logs, raw command output, hidden reasoning, tool traces, or long summaries.
    - If the normal final assistant reply is enough, do not call this tool.
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
