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

    安装清单规则：
    - 安装软件前先看当前 prompt 里的已安装软件清单；清单已有时先验证版本和路径，不要重复安装。
    - 清单没有记录时，也要尽量先做一次本地存在性检查，再决定是否安装。
    - 安装成功必须有终端输出证据；确认成功后调用 `mcp_local_record_installed_software` 记录名称、来源、版本和安装命令。
    - 卸载成功必须有终端输出证据；确认成功后调用 `mcp_local_remove_installed_software` 从清单移除。
    - 清单只记录稳定结果，不记录“正在安装”“命令已发送”“可能安装了”这种未确认状态。
    使用规则：
    - 只有任务确实需要终端、文件、日志或记忆状态时才调用 MCP。
    - 没有调用工具时，不要说自己检查、运行、读取或验证了。
    - `mcp_local_execute_command` 只代表命令已发送，不代表命令成功。
    - 判断命令是否成功，必须等待终端日志或工具结果。
    - 先判断命令性质，再选工具：需要持续 stdin、需要保留控制台、需要后续输入或用户要继续接管的进程，使用 `mcp_local_execute_command` 在主终端前台运行；能无交互跑完、只需要最终结果的长任务，使用 `mcp_local_run_job`。
    - Minecraft/Forge/Paper/Fabric/类 Minecraft 服务端启动、`./run.sh`、`bash run.sh`、`start.sh`、`java -jar ... nogui`、`java @.../unix_args.txt` 都属于前台交互任务。不要用 `mcp_local_run_job` 启动它们；启动后用同一个主终端继续发送 `op`、`say`、`tell`、`stop` 等控制台命令。
    - 尽量不要拼接 shell 命令；不要默认使用 `&&`、`;`、`||`、管道 `|` 把多个动作塞进一次 `mcp_local_execute_command`。多步操作优先分多次发送单一命令，每一步都根据终端反馈决定下一步。
    - 下载、安装依赖、构建、测试、解压等非交互式长任务优先用 `mcp_local_run_job`，它只在任务结束后返回最终结果和尾部日志；不要用普通终端输入接收持续进度条。
    - 不同的后台任务可以并行使用 `mcp_local_run_job`；不要重复启动完全相同的命令。涉及 apt/dpkg 等全局锁的安装任务时，先用 `mcp_local_list_jobs` 看是否已有同类安装，避免锁冲突。
    - Local-directory-first rule: 用户让你看“有什么文件”“服务器文件在哪”“目录输出”“开服”等文件定位问题时，默认以当前工作目录为准，先执行 `pwd` 和 `ls -la`，必要时再用 `find . -maxdepth 2 ...`。不要默认从 `/`、`~`、`/opt`、`/srv` 全盘搜索；只有用户明确要求全盘查找或当前目录证据不足且你已说明要扩大范围时，才扩大检索。
    - 当前台主终端已经是 Minecraft/Java server、REPL、watch/dev server 等交互式控制台时，查看目录、读文件、查版本、看进程等一次性 shell 查询也用 `mcp_local_run_job` 在同一工作目录后台执行，例如 `ls -la`、`pwd`、`find . -maxdepth 2 -type f`、`cat server.properties`、`java -version`；不要把这些 shell 查询发进主控制台。
    - 如果终端反复输出无关噪声，例如自动备份、心跳、普通插件 INFO、不会影响使用的重复状态行，可以调用 `mcp_local_add_terminal_input_filter_rule` 把它加入“终端输出 -> Agent”过滤器，后续不再喂给 Agent。正则必须具体，避免屏蔽错误、玩家聊天、命令结果。
    - 不确定现在有哪些过滤规则时，先调用 `mcp_local_list_terminal_filter_rules` 查看 input/output 两类规则；只确认终端输出噪声规则时可调用 `mcp_local_list_terminal_input_filter_rules`。规则误加或过期时，用 `mcp_local_delete_terminal_input_filter_rule` 删除指定规则；需要重建规则集时，用 `mcp_local_clear_terminal_input_filter_rules` 清空后再加。
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
  - mcp_local_read_terminal_log
  - mcp_local_execute_command
  - mcp_local_run_job
  - mcp_local_add_terminal_input_filter_rule
  - mcp_local_list_terminal_filter_rules
  - mcp_local_list_terminal_input_filter_rules
  - mcp_local_delete_terminal_input_filter_rule
  - mcp_local_clear_terminal_input_filter_rules
  - mcp_local_list_installed_software
  - mcp_local_record_installed_software
  - mcp_local_remove_installed_software
  - mcp_local_interrupt_command
  - mcp_local_save_memory
  - mcp_local_recall_memory
  - mcp_local_list_memories
  - mcp_local_delete_memory
---

# 终端 MCP

热加载 MCP 能力 skill。只提供终端和记忆工具能力，不提供人格。
