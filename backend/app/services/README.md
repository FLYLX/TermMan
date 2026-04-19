# Services 总览

`backend/app/services/` 是 TermMan 后端的业务层。

这里不再按子目录散落很多说明文档，统一只保留这一份总览，后面看结构直接看这个文件。

## 目录职责

- `agent/`
  Agent 运行时本体。负责会话、提示词组装、技能、MCP、知识检索、记忆访问和流式输出编排。
- `robot/`
  外部聊天平台接入层。负责机器人配置、`robot -> item` 绑定、消息路由、最近会话记忆，以及过滤后终端输出回推。
- `socket_pool/`
  终端流分发层。负责 item socket、订阅关系、输出过滤后的 fan-out，以及 daemon 输出到上层服务的桥接。
- `connection_pool/`
  Daemon 连接管理层。负责 daemon 连接模型、连接生命周期、认证和重连。
- `filters/`
  终端输入/输出过滤规则。
- `protocol/`
  终端通信里共用的事件/协议定义。
- 顶层 service 模块
  负责认证、终端调度、daemon 初始化、LLM 健康检查、文本生成、文件传输、日志等横切能力。

## Robot 结构

机器人接入现在拆成两层：

### 1. Backend 路由与业务层

文件：

- `robot/service.py`
- `robot/contracts.py`
- `robot/bridge_client.py`
- `api/routes/robots.py`

职责：

- 存机器人配置和绑定关系
- 决定一条机器人消息该交给哪个 item
- 复用现有 item agent 对话链路
- 记住最近会话路由和输出受众
- 把待发送文本交给 bridge

### 2. NoneBot2 Bridge 进程

文件：

- `robot/bridge/__main__.py`

职责：

- 用 `nonebot2 + nonebot-adapter-qq` 连接 QQ 官方机器人
- 接 QQ 消息
- 把 QQ 事件转成内部统一结构
- 调 backend 内部 dispatch 接口
- 把 backend 返回的内容发回 QQ

## Robot 消息链路

### 入站

1. QQ 官方机器人通过 NoneBot2 bridge 连入。
2. Bridge 收到 QQ 消息事件。
3. Bridge 转成 `RobotInboundMessage`。
4. Bridge 调用 `POST /api/v1/robots/{robot_id}/dispatch`。
5. Backend 根据绑定关系选中目标 item。
6. Backend 复用现有 agent 对话流程生成回复。
7. Backend 返回 reply chunks。
8. Bridge 再把这些 chunks 发回 QQ。

### 过滤后终端输出回推

1. Daemon 输出进入 `socket_pool/agent_bridge.py`。
2. 调用 `robot_service.dispatch_filtered_output(...)`。
3. Backend 找出 `receive_filtered_output=true` 的 robot 绑定。
4. Backend 找出这个 item 最近记住的受众。
5. Backend 把文本发给 bridge。
6. Bridge 用当前在线的 QQ bot 连接回推到目标会话。

## Agent 结构

`agent/` 目录现在按能力拆分：

- `agent.py`
  Agent 主运行时编排。
- `session.py`
  单个 item 的 agent 会话状态。
- `stream_manager.py`
  流式响应管理。
- `knowledge/`
  知识检索和启用知识文件装配。
- `memory/`
  向量记忆访问。
- `mcp/`
  MCP 客户端、服务端和管理逻辑。
- `prompts/`
  Prompt 构建和策略拼装。
- `skills/`
  Skill 定义、发现和加载。
- `history/`
  聊天历史辅助逻辑。

## 终端与 Daemon

- `terminal_service.py`
  面向 item 的终端编排服务。
- `daemon_initializer.py`
  Daemon 初始化和配置同步。
- `item_file_service.py`
  item 文件和知识文件的上传、下载、删除。
- `connection_pool/`
  长连接 daemon 通道、重连、认证。

## 流分发

- `socket_pool/item_socket.py`
  单个 item 的 socket 通道。
- `socket_pool/socket_manager.py`
  socket 生命周期管理。
- `socket_pool/subscription_center.py`
  订阅者注册和 fan-out。
- `socket_pool/terminal_stream_pipeline.py`
  daemon 输出处理流水线。
- `socket_pool/agent_bridge.py`
  从过滤后输出桥接到 agent/robot 等上层消费方。

## Filters

- `filters/input_filter.py`
  终端输入过滤。
- `filters/output_filter.py`
  终端输出过滤。

## 规则

- 协议适配层尽量薄，不做业务决策。
- item 路由逻辑放在 service，不放在 adapter。
- 复用现有 item agent 流程，不额外复制一套聊天运行时。
- `services/` 目录默认只保留这一份总览文档，避免再堆很多零散 md。
