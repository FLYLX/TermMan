# TermMan MCP 工具清单

> 所有工具在 Agent 调用时自动加前缀 `mcp_local_` 或 `mcp_robot_`。

---

## 一、终端与命令执行（mcp_local_*）

### 1. get_terminal_status
- **用途**：读取终端的实时状态（是否打开、是否连接、是否可用）
- **参数**：无
- **场景**：用户问"终端开了没""连上了吗"时调用，不要从聊天记录猜

### 2. execute_command
- **用途**：在主终端前台执行命令，Agent 拥有该进程的管理权
- **参数**：`command`（必填）、`expected_output`、`expected_regex`、`timeout_seconds`（默认20）、`auto_interrupt_on_timeout`
- **场景**：需要与进程持续交互（服务器、REPL、控制台）、需要观察实时输出、需要后续发指令
- **判断标准**：命令执行后会不会进入等待你输入的状态？会 → execute_command，不会 → run_job

### 3. run_job
- **用途**：后台一次性执行命令（fire-and-forget），stdin 关闭，完成后自动回传结果
- **参数**：`command`（必填）、`timeout_seconds`（默认600）、`tail_lines`（默认80）
- **场景**：下载、装包（-y）、apt update、编译、测试、解压、查文件（ls/cat/find/grep）、java -version
- **特性**：多个不同 job 可并行；完全相同的命令会被拦截；启动时立即注册到 workflow（状态变 waiting_job）

### 4. list_jobs
- **用途**：列出当前正在运行的后台 job（含已用时间、最近输出）
- **参数**：无
- **场景**：用户问"装到哪了""下载进度"时先调这个，不要开新 job

### 5. cancel_job
- **用途**：按 job_id 取消一个正在运行的后台 job
- **参数**：`job_id`（必填）
- **场景**：用户要求停止某个后台任务；先 list_jobs 确认 job_id 再取消

### 6. interrupt_command
- **用途**：向主终端发送 Ctrl+C，中断当前前台进程
- **参数**：无
- **场景**：命令跑错了、进程卡住了、需要中断当前操作

### 7. read_terminal_log
- **用途**：读取终端的历史输出日志
- **参数**：`lines`（行数）、`search`（搜索关键词）
- **场景**：需要查看之前的命令输出、排查错误

---

## 二、终端过滤规则（mcp_local_*）

### 8. add_terminal_input_filter_rule
- **用途**：添加终端输入过滤规则（正则匹配，命中后触发 Agent 处理）
- **参数**：`pattern`（正则）、`label`（标签）、`source`（来源）
- **场景**：需要监听终端特定输出（如报错、特定提示）时自动触发 Agent

### 9. list_terminal_input_filter_rules
- **用途**：列出当前生效的终端输入过滤规则
- **参数**：无

### 10. list_terminal_filter_rules
- **用途**：列出终端过滤规则（含输出过滤）
- **参数**：无

### 11. delete_terminal_input_filter_rule
- **用途**：删除指定的终端输入过滤规则
- **参数**：`rule_id`

### 12. clear_terminal_input_filter_rules
- **用途**：清除所有终端输入过滤规则
- **参数**：无

---

## 三、定时任务（mcp_local_*）

### 13. list_scheduled_tasks
- **用途**：列出所有定时任务
- **参数**：无

### 14. write_scheduled_task
- **用途**：创建或更新一个定时任务（cron 表达式）
- **参数**：`name`（必填）、`cron`（必填）、`command`（必填）、`timezone`（默认 Asia/Shanghai）
- **场景**：用户要求定时执行某个命令

### 15. delete_scheduled_task
- **用途**：删除一个定时任务
- **参数**：`task_id`（必填）、`reason`

---

## 四、长期记忆（mcp_local_*）

### 16. save_memory
- **用途**：保存稳定、可复用、已验证的重要信息到长期记忆
- **参数**：`content`（必填）、`memory_type`（fact/preference/error/context）、`ttl_days`
- **注意**：执行中的任务状态放任务队列，不放记忆

### 17. recall_memory
- **用途**：语义搜索长期记忆
- **参数**：`query`（必填）、`n_results`、`memory_type`

### 18. list_memories
- **用途**：列出所有记忆，可按类型过滤
- **参数**：`memory_type`（可选）

### 19. delete_memory
- **用途**：删除指定记忆
- **参数**：`memory_id`（必填）

### 20. compress_memories
- **用途**：将多条重复/冗余/过时的记忆压缩合并成一条精炼记忆
- **参数**：`memory_ids`（必填，≥2）、`content`（必填）、`memory_type`、`ttl_days`
- **场景**：recall 或 list 结果里有重复内容、同一事实的旧版本

---

## 五、聊天历史（mcp_local_*）

### 21. read_chat_history
- **用途**：读取 Web 端聊天历史
- **参数**：`limit`（条数）
- **场景**：需要回顾之前的对话内容

---

## 六、QQ 机器人（mcp_robot_*）

> 以下工具仅在 QQ 会话上下文中可用（由 robot 插件动态注入）。

### 22. mcp_robot_send_message
- **用途**：向 QQ 会话发送消息（回复用户）
- **参数**：`text` 或 `messages`（必填）、`target`（可选，指定发送目标）
- **场景**：任务完成后汇报结果、回答用户问题
- **注意**：只在完成/失败/方向变更时发，不要发中间进度

### 23. mcp_robot_sleep_conversation
- **用途**：让当前 QQ 会话进入休眠（不再主动回复）
- **参数**：无
- **场景**：用户说"别回了""安静"时调用

### 24. mcp_robot_save_memory
- **用途**：保存 QQ 相关的长期记忆
- **参数**：同 save_memory
- **场景**：记住用户的 QQ 偏好、群规等

### 25. mcp_robot_list_memories
- **用途**：列出 QQ 相关的长期记忆
- **参数**：同 list_memories

### 26. mcp_robot_recall_memory
- **用途**：语义搜索 QQ 相关的长期记忆
- **参数**：同 recall_memory

### 27. mcp_robot_read_conversation_memory
- **用途**：读取 QQ 对话的原始近期消息记录
- **参数**：`target`（可选）
- **场景**：需要查看最近的 QQ 聊天原文（不是长期记忆，是原始消息）

### 28. mcp_robot_compress_memories
- **用途**：压缩合并 QQ 相关的长期记忆
- **参数**：同 compress_memories

---

## 工具选择速查

| 我要做什么 | 用哪个工具 |
|-----------|-----------|
| 跑一个命令看结果（装包、下载、查文件） | `run_job` |
| 启动一个需要持续管理的进程（服务器、REPL） | `execute_command` |
| 查看后台任务进度 | `list_jobs` |
| 停止一个后台任务 | `cancel_job` |
| 中断当前终端命令 | `interrupt_command` |
| 给 QQ 发结果 | `mcp_robot_send_message` |
| 记住一个信息 | `save_memory` / `mcp_robot_save_memory` |
| 想起一个信息 | `recall_memory` / `mcp_robot_recall_memory` |
| 定时执行命令 | `write_scheduled_task` |
| 监听终端特定输出 | `add_terminal_input_filter_rule` |
