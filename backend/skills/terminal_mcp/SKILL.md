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

    使用规则（通用任务工作流、后台 Job、命令反馈、日志过滤等规则已在系统提示中定义，此处只列终端专属规则）：
    - 用户询问"终端开了吗 / 终端是否连接 / 控制台能不能用"时，必须先调用 `mcp_local_get_terminal_status`。只有工具明确返回 active=true 才能回答终端已开启；历史日志、Item 的运行状态、旧聊天和缓存 handler 都不能作为在线证据。
    - 终端命令和后台 Job 都必须通过实时 Socket Room 校验。工具返回"终端未启动或未连接"时，直接如实告知，不能说命令正在执行、正在等待输出或终端只是暂时没回显。
    - 只有任务确实需要终端、文件、日志或记忆状态时才调用 MCP。
    - 先判断命令性质，再选工具：需要持续 stdin、需要保留控制台、需要后续输入或用户要继续接管的进程，使用 `mcp_local_execute_command` 在主终端前台运行；能无交互跑完、只需要最终结果的长任务，使用 `mcp_local_run_job`。
    - Minecraft/Forge/Paper/Fabric/类 Minecraft 服务端启动、`./run.sh`、`bash run.sh`、`start.sh`、`java -jar ... nogui`、`java @.../unix_args.txt` 都属于前台交互任务。不要用 `mcp_local_run_job` 启动它们；启动后用同一个主终端继续发送 `op`、`say`、`tell`、`stop` 等控制台命令。
    - 尽量不要拼接 shell 命令；不要默认使用 `&&`、`;`、`||`、管道 `|` 把多个动作塞进一次 `mcp_local_execute_command`。多步操作优先分多次发送单一命令，每一步都根据终端反馈决定下一步。
    - 当前台主终端已经是 Minecraft/Java server、REPL、watch/dev server 等交互式控制台时，查看目录、读文件、查版本、看进程等一次性 shell 查询也用 `mcp_local_run_job` 在同一工作目录后台执行，例如 `ls -la`、`pwd`、`find . -maxdepth 2 -type f`、`cat server.properties`、`java -version`；不要把这些 shell 查询发进主控制台。
    - 对容易卡住或需要明确完成信号的命令，调用 `mcp_local_execute_command` 时尽量带 `expected_output` 或 `expected_regex` 和 `timeout_seconds`；预期输出超时未出现时会自动 Ctrl+C。
    - 不要为了普通闲聊调用终端工具。
safety:
  requires_approval: false
  risk_level: medium
  max_retries: 1
  timeout: 30
mcp_servers:
  - local
tools:
  - mcp_local_get_terminal_status
  - mcp_local_read_terminal_log
  - mcp_local_read_chat_history
  - mcp_local_execute_command
  - mcp_local_run_job
  - mcp_local_add_terminal_input_filter_rule
  - mcp_local_list_terminal_filter_rules
  - mcp_local_list_terminal_input_filter_rules
  - mcp_local_delete_terminal_input_filter_rule
  - mcp_local_clear_terminal_input_filter_rules
  - mcp_local_interrupt_command
  - mcp_local_save_memory
  - mcp_local_recall_memory
  - mcp_local_list_memories
  - mcp_local_delete_memory
---

# 终端 MCP

热加载 MCP 能力 skill。只提供终端和记忆工具能力，不提供人格。
