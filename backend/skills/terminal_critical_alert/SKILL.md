---
skill_id: terminal_critical_alert
name: Terminal Critical Alert
description: Broadcast severe terminal failures to QQ through the robot MCP when a clear QQ target exists.
category: integration
trigger:
  type: auto
  patterns:
    - fatal
    - critical
    - panic
    - traceback
    - segmentation fault
    - out of memory
    - unhandled exception
    - uncaught exception
    - process exited
    - service failed
    - startup failed
action:
  type: llm
  prompt: |
    Terminal Critical Alert Skill:

    You are analyzing terminal output. If the current terminal output indicates a severe service-impacting failure, notify QQ by calling `mcp_robot_send_message`.

    Treat these as severe:
    - service crash, repeated restart failure, startup failure, or process exit caused by an error
    - fatal/panic/critical errors
    - traceback or unhandled/uncaught exception in a running service
    - segmentation fault, out-of-memory, OOM kill, disk full, permission failure that prevents startup
    - database/network/listener failure that makes the service unavailable

    Do not alert for:
    - normal command echo, prompts, heartbeat logs, warnings without impact
    - expected "file not found" during investigation unless it prevents service startup
    - noisy stack traces from tests that are already handled or explicitly expected

    QQ delivery rules:
    - Use `mcp_robot_send_message` only when a QQ target is visible in context or explicitly configured by the user.
    - For severe terminal failures, prefer `{"broadcast": true, "text": "..."}` so the backend sends the same alert to every QQ conversation visible in the current item context.
    - If only one QQ conversation is visible, sending with only `text` is also acceptable.
    - If there is no visible QQ target, do not invent a group/private target; return a concise internal note instead.
    - The QQ alert must be short: service/item name if known, severity, what failed, and one next action. Do not include raw logs, secrets, tokens, stack traces, or tool traces.
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

# Terminal Critical Alert

This skill lets the agent broadcast concise QQ alerts for severe terminal failures when the current item already has a known QQ robot target.
