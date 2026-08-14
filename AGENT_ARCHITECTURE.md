# TermPaws Agent 架构

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

## 核心原则

1. **用户意图只由 LLM 判定**——代码里禁止用正则/关键词猜测用户意图（取消？发送？查状态？）。结构化信号（触发路径、显式目的地、ticket 状态）可以做判定；消息文本的内容不行
2. **route 入队绑死**——每个输入的回复路由（ticket）由来源适配器在入队时创建绑定，合并层只保管不猜测
3. **来源可插拔**——新出入口 = 实现 `AgentIntegration` + 入队时绑 ticket，核心零改动

## Backend 启动流程（`main.py` lifespan）

1. `plugin_manager.startup(app)` — 启动插件（robot embedded bridge / terminal_ws）
2. `initialize_daemon_connections()` — 重连 daemon、恢复终端会话
3. `mcp_server_manager.start_all()` — 启动 MCP servers（内建 `local` + 插件提供的 `robot`）
4. `restore_agent_state()` — 从 SQLite 恢复 reply tickets
5. `agent_task_watchdog.start()` + `scheduled_task_manager.start()` — 后台维护循环

## 统一合并队列（系统级消息入口）

**所有来源的输入汇入 per-item 的 session 输入队列，单消费者线程合并成批次轮次：**

```
QQ 直接消息 ──→ robot dispatch 快路径（立即开轮次）
QQ 后续消息 ──→ pending 缓冲 ──→ drain 时建 QQ ticket ──→ ┐
Web 聊天 ────→ /chat/{id}/stream 建 web ticket ────────→ ├─→ session 输入队列
Terminal ──→ daemon 输出 ─────────────────────────────→ ┤      │ 单消费者
定时任务 ──→ scheduled_tasks ──────────────────────────→ ┘      ▼
                                              _merge_input_batch：按 source_label 分段、
                                              保留全部 ticket（merged_ticket_ids）
                                                       ▼
                                              合并轮次（prompt 分源标注）
                                                       ▼
                                              分源投递（每张 ticket 走自己的 route）
```

**关键行为**：
- 轮次忙时，任何来源的消息都进队列合并——不会一条条单独开轮次
- 批次放行时才认领会话代际（drain 时刻），在飞轮次的投递权不被抢
- 连发 10 条 = 第 1 条一轮 + 后 9 条合并一轮

**接入新来源（插件）**：

```python
ticket = reply_ticket_manager.create_for_agent(...)  # 填齐 source_type/reply_target/conversation_key
agent_session.process_input(InputMessage(
    input_type=InputType.CHAT,
    content=..., reply_ticket_id=ticket.ticket_id,
    source_label="我的来源",
))
```

## Reply Ticket —— 回复路由与 plan 载体

每轮对话创建一张 `ReplyTicket`，贯穿：**路由 + plan 草稿本 + 投递追踪**。

### 生命周期

```
pending → running → sending → delivered / failed
                     └─ 用户取消 → cancelled（系统直接终止 plan，不等 LLM）
TTL 6h；SQLite 持久化，重启恢复；QQ 同会话旧 ticket 被新消息 supersede
```

### 关键字段

| 字段 | 用途 |
|---|---|
| `source_type` | qq / web / terminal —— 投递路由 |
| `reply_target` / `conversation_key` | QQ 目标会话（轮次内可由此重建 robot 上下文） |
| `plan` | `[{step, status}]`，status ∈ pending/in_progress/completed/cancelled |
| `extra_targets` | 用户消息里显式点名的 QQ 目标（结构化授权） |
| `external_report_sent` | agent 已用 send 工具投递过 → 后续 deliver 静默收尾防重复 |

### plan 生命周期（系统保证，不依赖 LLM 自觉）

- 全步骤 terminal（completed/cancelled）→ **系统自动清空**，不再喂给后续轮次
- job 被用户取消 → **系统直接把剩余步骤标 cancelled 并清空**
- `_plan_reminder` 在 job 结果回调时附带当前 plan；全 terminal 的 plan 不再附带
- 任何超过一步的任务都要求建 plan（工具描述明确"只有单步问答才可跳过"）

## 投递层（插件注册表驱动）

```python
# reply_ticket._deliver_ticket_content
if deliver_integration_ticket(ticket, text):   # 遍历 integration 注册表
    ...
if ticket.source_type == SOURCE_WEB:           # web 是唯一内建兜底
    ...
```

新来源插件实现 `AgentIntegration.deliver_ticket(ticket, text)`（匹配自家 source_type 则投递），注册后扇出自动生效。

### 发送守卫（纯结构，无意图判定）

| 守卫 | 规则 |
|---|---|
| QQ 轮次 | robot MCP server 锁当前会话（跨会话须显式 target） |
| 非 QQ 轮次 | `robot_send_has_explicit_destination(tool_args)`——调用必须带显式目的地（target/targets/reply_to），裸发被拒 |
| 轮次提前结束 | 仅当"裸发回当前会话"成功（回复完毕）；带显式目标的发送继续轮次直到 agent 发完所有目标 |

## MCP 工具体系

全部能力是 MCP 工具（`mcp_<server>_<tool>`），内建 server 进程内直连：

- **`local`**（内建）：`update_plan`、`execute_command`（前台交互）、`run_job`（后台异步）、`list_jobs`、`cancel_job`、`interrupt_command`、`read_terminal_log`、记忆 CRUD、`prepare_capabilities`（按需加载工具）、定时任务/过滤规则 CRUD
- **`robot`**（插件注册内建）：`send_message`、会话记忆、`sleep_conversation`
- **外部**：`mcp_servers.json` 配置的 stdio server

工具渐进暴露：每轮只给 9 个核心工具全量 schema，其余以目录形式出现、按需 `prepare_capabilities` 加载。

## 日志通道（写入侧分流）

daemon stream 事件带 `source` 标签，backend 订阅落盘时分流：

```
无 source（前台 PTY）   → {item}.log       → agent read_terminal_log / 命令反馈 / 前端
source="job"（后台 job）→ {item}.jobs.log  → 归档；agent 走结构化 job 结果回调（daemon 已过滤噪音）
```

agent 读到的终端日志永远是前台真实内容；job 结果不经日志打捞。

## 终端输入恢复

`input_center` 是 handler 注册的唯一事实来源。socket 上缓存的 handler id 会在注销后变陈旧——恢复路径（`create_backend_socket` / `restore_terminal_session`）一律向 `input_center` 验活后才决定是否重注册，杜绝"看着已注册实际没有"。

## 轮次串行与看护

- `AgentTurnCoordinator`：per-handler FIFO 租约，串行化共享 Agent 实例的所有轮次（异步获取带 230s 超时）
- 会话控制器（robot service）：代际计数 + 休眠/处理中闸口 + 超时收割
- `task_watchdog`：周期清理孤儿 ticket、卡死 dispatch、滞留会话

## 前端

- web 聊天输入框**不锁定**——处理中可继续发，消息入队合并；多条流各自接收事件，前端按"相邻同内容"去重渲染
- plan 面板经 `plan_updated` SSE 实时刷新
