---
skill_id: terminal_mcp
name: 终端 MCP
description: 允许助手通过本地 MCP 读取终端日志、发送命令、中断命令和管理长期记忆。
category: mcp
trigger:
  type: manual
  patterns:
    - 终端
    - 命令
    - 日志
    - 报错
    - mcp
    - terminal
    - shell
    - command
action:
  type: llm
  prompt: |
    终端 MCP Skill：

    这个 skill 提供终端相关工具能力，不提供人格。

    可用能力：
    - 读取终端日志和原始反馈。
    - 向当前终端发送命令。
    - 中断当前终端命令。
    - 保存、检索、列出、删除长期记忆。

    使用规则：
    - 只有任务确实需要终端、文件、日志或记忆状态时才调用 MCP。
    - 没有调用工具时，不要说自己检查、运行、读取或验证了。
    - `mcp_local_execute_command` 只代表命令已发送，不代表命令成功。
    - 判断命令是否成功，必须等待终端日志或工具结果。
    - 不要为了普通闲聊调用终端工具。
safety:
  requires_approval: false
  risk_level: medium
  max_retries: 1
  timeout: 30
mcp_servers:
  - local
tools:
  - mcp_local_read_terminal_log
  - mcp_local_execute_command
  - mcp_local_interrupt_command
  - mcp_local_save_memory
  - mcp_local_recall_memory
  - mcp_local_list_memories
  - mcp_local_delete_memory
---

# 终端 MCP

热加载 MCP 能力 skill。只提供终端和记忆工具能力，不提供人格。
