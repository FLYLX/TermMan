# TermMan Agent 架构

## 部署拓扑

```
┌─────────────┐   OneBot V11 WS   ┌──────────────┐
│ QQ / NapCat │ ◄───────────────► │ robot-bridge │ (NoneBot2, :7000)
└─────────────┘                   └──────┬───────┘
                                         │ POST /robots/{id}/dispatch
                                         ▼
┌─────────────┐   SSE/REST        ┌──────────────┐
│   frontend  │ ◄───────────────► │   backend    │ (FastAPI, :8000)
│  (Web UI)   │                   │  agent 核心   │
└─────────────┘                   └──────┬───────┘
                                         │ HTTP / Socket.IO
                                         ▼
                                  ┌──────────────┐
                                  │    daemon    │ (FastAPI+SocketIO, :9000)
                                  │ 终端/任务执行 │
                                  └──────────────┘
```

| 容器 | 职责 |
|---|---|
| `backend` | REST API、agent 运行时、MCP host、插件 host |
| `robot-bridge` | QQ 协议桥（OneBot V11），转发消息到 backend |
| `daemon` | PTY 终端、后台 job 执行、文件操作沙箱 |
| `frontend` | Web UI |

`ROBOT_BRIDGE_EMBEDDED=true` 时 bridge 可内嵌进 backend 进程。

## Backend 启动流程（`main.py` lifespan）

1. `plugin_manager.startup(app)` — 启动插件（robot embedded bridge / terminal_ws）
2. `initialize_daemon_connections()` — 重连 daemon、恢复终端会话
3. `mcp_server_manager.start_all()` — 启动 MCP servers（内建 `local` + 插件提供的 `robot`）
4. `restore_agent_state()` — 从 SQLite 恢复 reply tickets
5. `agent_task_watchdog.start()` + `scheduled_task_manager.start()` — 后台维护循环

## Agent 核心（`app/services/agent/`）

```
                     ┌────────────────────────────────────┐
                     │           Agent (agent.py)          │
                     │ per-handler 单例，持有 AgentContext │
                     │ model 配置 / skills / MCP tools    │
                     └───────┬───────────────────┬────────┘
                             │                   │
              ┌──────────────▼──────┐   ┌────────▼─────────────┐
              │ turn_coordinator.py │   │  chat_runtime.py     │
              │ FIFO lease 串行化   │   │ collect_chat_response│
              │ 同一 handler 的轮次 │   │ QQ/定时任务入口      │
              └─────────────────────┘   └────────┬─────────────┘
                                                 │
                              ┌──────────────────▼──────────────────┐
                              │  generate_stream (api/routes/chat.py)│
                              │  agent 主循环：LLM stream → 工具调用 │
                              │  → MCP 执行 → 最多 6 轮迭代          │
                              └──────────────────┬──────────────────┘
                                                 │
        ┌────────────────┬───────────────────────┼───────────────────────┬────────────────┐
        ▼                ▼                       ▼                       ▼                ▼
┌───────────────┐ ┌─────────────┐   ┌───────────────────┐   ┌────────────────┐ ┌─────────────┐
│ reply_ticket  │ │ prompts/    │   │ mcp/local_server  │   │ robot MCP      │ │ memory/     │
│ 回执票据系统   │ │ builder.py  │   │ 内建工具集(双手)   │   │ QQ发送/记忆    │ │ vector_store│
│ 来源路由+plan │ │ 组装prompt  │   │ 终端/job/计划     │   │                │ │ 长期记忆RAG │
└───────────────┘ └─────────────┘   └───────────────────┘   └────────────────┘ └─────────────┘
```

### 关键模块

| 模块 | 职责 |
|---|---|
| `agent.py` | Agent 单例管理、工具分发 `mcp_<server>_<tool>`、handler 热重载 |
| `chat_runtime.py` | 非流式入口（QQ 轮次/定时任务），权限检查、robot context 注入 |
| `turn_coordinator.py` | per-handler FIFO 租约，防止并发轮次破坏共享 Agent context |
| `session.py` | per-item 有状态会话，终端驱动的轮次（MC 服务器聊天等） |
| `stream_manager.py` | Web SSE 事件广播 |
| `state_store.py` | SQLite 持久化 tickets，启动时恢复 |
| `task_watchdog.py` | 周期清理：孤儿 ticket、卡死 dispatch、滞留会话 |
| `scheduled_tasks.py` | cron 式定时任务，以独立 ticket 跑 agent 轮次 |

## Reply Ticket —— 核心设计模式

每轮对话创建一张 `ReplyTicket`，是**投递追踪 + plan 草稿本**的载体：

```
ticket 生命周期: pending → running → sending → delivered / failed
                                         ↘ cancelled（用户取消）
```

- `source_type`：qq / web / terminal，决定回复路由
- `plan`：`[{step, status}]` 列表（pending/in_progress/completed/cancelled），由 `mcp_local_update_plan` 写入
- plan 全 terminal 时**系统自动清空**，不再喂给后续轮次
- 用户取消 job → 系统直接把 plan 标 cancelled 并清空（不依赖 LLM）
- `_plan_reminder`：job 结果回调时附带当前 plan 提醒（全 terminal 则跳过）
- QQ 同会话旧 ticket 被新消息 supersede；有 plan 的 ticket 视为在飞任务不被取代
- TTL 6h，启动时从 SQLite 恢复

## MCP 工具体系

所有能力都是 MCP 工具，命名 `mcp_<server>_<tool>`：

**`local` server（内建，`mcp/local_server.py`）**— agent 的双手：
- 计划：`update_plan`
- 终端：`execute_command`（前台交互）、`run_job`（后台异步）、`list_jobs`、`cancel_job`、`interrupt_command`、`read_terminal_log`、`get_terminal_status`
- 记忆：`save_memory` / `recall_memory` / `list_memories` / `delete_memory` / `compress_memories`
- 其他：`read_chat_history`、`prepare_capabilities`（按需加载能力）、定时任务 CRUD、输出过滤规则 CRUD

**`robot` server（QQ 插件提供）**：`send_message`、会话记忆读写、`sleep_conversation`

**外部 stdio MCP servers**：从 `mcp_servers.json` 加载。

工具经由 daemon HTTP 执行：`run_job_http` / `list_jobs_http` / `cancel_job_http` / `get_job_result_http`。

## 消息流

### QQ 消息 → 回复

```
QQ → NapCat → robot-bridge(NoneBot 事件)
  → 归一化 RobotInboundMessage
  → POST /robots/{id}/dispatch (token 认证)
  → robot_service.handle_inbound_message()
      触发判定(@/回复/私聊/活跃窗口) → 会话控制器(代际/休眠/处理中闸口)
      → 入队 QueuedRobotChatJob（合并 input_merge_buffer 中的待处理输入）
  → dispatch worker(2~8 线程池)
      组装消息(发送者卡片/印象卡片/实况上下文/行动框架/[Current QQ message])
      → collect_chat_response(robot context)
  → turn lease 串行化 → 创建 ReplyTicket
  → generate_stream 主循环
      build_chat_turn_messages(历史+记忆+知识+ticket prompt+挂起终端上下文)
      → LiteLLM → 工具调用 → MCP 执行
  → 回复路径（优先级）：
      ① agent 调 mcp_robot_send_message（ticket 标 external_report_sent）
      ② 最终可见文本 → reply_ticket_manager.deliver() → bridge /send → QQ
      ③ "NRN" 不回复意图 → 静默结束
  → 后台 job 完成 → input_merge_buffer 缓冲
      → 合并为 [后台终端任务结果] 回调轮次送回原会话
```

### Web 消息 → 回复

```
POST /chat/{item}/stream → prepare_chat_agent(权限检查)
  → generate_stream(source_type=web) → 同一 agent 主循环
  → SSE 推送 (agent_response/agent_tool_result/agent_status/done)
  → 历史持久化 ItemChatSession（滚动摘要）
```

### 终端驱动轮次

```
daemon 终端输出 → backend room listener → AgentSession 消费线程
  → build_terminal_turn_messages → agent 轮次
  → MC 玩家聊天 → execute_command 回服务器控制台
```

## 插件 + Integration 双层解耦

```
BackendPlugin (plugins/manager.py)
  │ entrypoints: include_router / startup / register_agent_integration
  ▼
AgentIntegration Protocol (integrations/contracts.py, ~40 方法)
  │ prompt 构建 / 历史作用域 / chat context 装配拆卸
  │ 工具参数注入 / 投递重试回退 / ticket 投递
  ▼
RobotAgentIntegration (plugins/robot/agent/integration.py)
```

核心 agent 循环不含任何 QQ 逻辑；QQ 全在 robot 插件内。

## Robot 插件（`plugins/robot/`）

| 模块 | 职责 |
|---|---|
| `service.py` | QQ 会话大脑：触发分类、会话控制器（代际计数+休眠/处理态）、dispatch 队列+工作线程池+卡死收割、pending 输入合并 |
| `api.py` | `/robots` CRUD、绑定、`POST /robots/{id}/dispatch` 接收入口 |
| `mcp/server.py` | robot MCP 工具（send_message/记忆） |
| `bridge/embedded.py` | 内嵌 NoneBot2 bridge（可选）；`bridge/proxy.py` 外部容器代理 |
| `bridge_client.py` | 到外部 bridge 的 HTTP 客户端 |
| `conversation_memory.py` | 每会话 `.log` 记忆文件 |
| `internal_trace.py` | 可见文本清洗；`reply_intent.py` NRN 不回复意图 |

## Daemon（`daemon/src/`）

- `terminal_manager.py` — PTY 进程 spawn、日志、resize
- `job_runner.py` — 异步后台 job：ActiveJob 追踪、结果轮询、取消
- `socket_service.py` + `room_manager.py` — per-item Socket.IO 房间、订阅者管理
- `file_service.py` — per-user/per-item workdir 沙箱文件操作
- backend 侧对应：`connection_pool/`（DaemonConnection HTTP 客户端）、`socket_pool/`（Socket.IO 事件总线、input center）、`terminal_service.py`

## 其他子系统

- **记忆**：`memory/vector_store.py` Chroma+BGE embedding 长期记忆 + 词法回退；`knowledge/service.py` 知识文件 RAG；会话滚动摘要
- **技能**：`skills/` 文件系统 SKILL.md 包（persona/system/terminal_mcp/minecraft），revision 变更触发 agent 热重载
- **能力渐进加载**：`capability_state.py` 目录式紧凑列表 + `prepare_capabilities` 按需全量加载，避免 prompt 塞满工具 schema
- **persona_guard**：人设身份强制
- **token_usage**：SQLite token 记账
