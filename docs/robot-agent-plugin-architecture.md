# Robot 与 Agent 插件化重构说明

记录日期：2026-06-12

## 目标

这次重构的目标是把 QQ robot 能力从 TermMan 的 agent 核心里拆出去。

重构后的边界是：

- TermMan 的核心功能仍然是自动管理 terminal、item、agent、skill 和 MCP。
- Robot 是可选插件；没有 robot、没有 robot bridge、插件关闭时，agent 核心不应该主动调用 robot bridge。
- 有 robot 时，robot 通过插件注册自己的 prompt、MCP server、内置 skill、群聊记忆、消息发送、回复反思和 fallback。
- 群聊唤醒隔离：一个群 @/回复机器人时，只唤醒这个群对应的 agent turn；其他群不被这次消息唤醒。
- 群聊记忆互通但按会话存储：robot 连接后所有入站消息都会写 `.log`，但 agent 只有被唤醒后才会通过 MCP 选择性读取对应聊天记录。

## 改了什么

### 新增 agent integration 层

新增 `backend/app/services/agent/integrations/`。

这个文件定义了 agent 与插件之间的统一接口：

- `AgentIntegration`：插件协议。
- `NoopAgentIntegration`：默认空实现，避免核心代码写一堆 robot 分支。
- `load_agent_integrations()`：扫描 `app.plugins.*.integration` 并动态注册插件。
- `reload_agent_integrations()`：热重载插件注册表。
- 一组 hook 函数：prompt、history、MCP factory、skill、tool 参数注入、回复反思、fallback、terminal alert 等都通过这里进入插件。

核心 agent 现在只依赖 `integrations/` 这个抽象层，不再直接依赖 robot 实现。

目录职责：

- `contracts.py`：插件协议、空实现、共享类型。
- `registry.py`：插件发现、注册表、热加载。
- `hooks.py`：agent 核心调用的 hook 聚合入口。
- `__init__.py`：对外导出稳定 API。

### 新增 robot integration 插件

新增 `backend/app/plugins/robot/agent/integration.py`。

robot 相关逻辑集中到 `RobotAgentIntegration`，它负责：

- 注册 robot 系统提示词。
- 注册 robot 内置 skill：`robot_messaging`。
- 注册 robot 内置 MCP server：`robot`。
- 给 robot MCP tool 注入运行期上下文，例如 `_robot_context_token`、当前用户、可见 QQ 目标。
- 维护当前 QQ 会话上下文。
- 按 QQ conversation 过滤 agent 历史，避免不同群的回复上下文串在一起。
- 在 agent 给出普通最终回复但没调用 `mcp_robot_send_message` 时，触发一次回复反思。
- 在明确是 QQ 唤醒且模型没有走发送工具时，做最终回复 fallback，把内容发回对应 QQ 会话。
- 写入 assistant 侧群聊 `.log` 记忆。
- 给 terminal alert 场景临时挂载 robot MCP 工具。

### 移动 robot MCP 实现到插件目录

新增：

- `backend/app/plugins/robot/mcp/context.py`
- `backend/app/plugins/robot/mcp/server.py`

旧路径保留为兼容 shim：

- `backend/app/services/agent/mcp/robot_context.py`
- `backend/app/services/agent/mcp/robot_server.py`
- `backend/app/plugins/robot/mcp_context.py`
- `backend/app/plugins/robot/mcp_server.py`
- `backend/app/plugins/robot/integration.py`

也就是说旧 import 不会马上炸，但真实实现已经在 `app.plugins.robot` 下面。

### 重构 MCP server 管理

修改 `backend/app/services/agent/mcp/server_manager.py`。

以前核心 MCP manager 硬编码了 `local` 和 `robot` 两个内置 server。

现在核心只内置 `local`：

```py
BUILTIN_SERVERS = {"local"}
```

`robot` 是否可用由插件注册的 `builtin_mcp_server_factories()` 决定。

`reload_config()` 现在也会调用 `reload_agent_integrations()`，所以 MCP 配置重载时会重新发现插件。

### 重构 skill 加载

修改 `backend/app/services/agent/skills/loader.py`。

以前 robot skill 更像是硬塞进 agent 的能力。

现在 skill loader 会从 integration 层读取插件内置 skill：

```py
get_builtin_skill_definitions()
```

因此 robot 插件启用时会出现 `robot_messaging`，关闭时不会出现。

### 重构 agent 上下文

修改 `backend/app/services/agent/agent.py`。

`AgentContext` 不再把 robot 字段作为核心字段保存，而是统一放进：

```py
integration_contexts: dict[str, dict[str, Any]]
```

为了兼容旧代码，`robot_id`、`robot_sender_key`、`robot_context_token` 等还保留成 property，但实际读写的是：

```py
integration_contexts["robot"]
```

旧方法也保留为委托：

- `set_robot_context()`
- `ensure_robot_context_tools()`
- `ensure_robot_messaging_tools()`
- `clear_robot_context()`
- `clear_transient_robot_messaging_tools()`

这些方法内部已经转向 integration 层。

### 重构 chat runtime 和 routes

修改：

- `backend/app/services/agent/chat_runtime.py`
- `backend/app/api/routes/chat.py`

chat runtime 现在使用通用的 `integration_contexts`，robot 只是其中一个 context。

chat route 里原本硬编码的 robot 反思、robot fallback、robot 发送判定，改成调用 integration hook：

- `get_delivery_retry_decision()`
- `record_integration_delivery_correction()`
- `integration_message_sent()`
- `send_integration_final_response_fallback()`
- `integration_fallback_response_content()`
- `record_integration_no_final_response()`

核心 route 不再关心“QQ 怎么发消息”，只关心“插件有没有需要处理的投递语义”。

### 重构 prompt 和 history builder

修改：

- `backend/app/services/agent/prompts/system.py`
- `backend/app/services/agent/prompts/builder.py`

系统提示词现在通过：

```py
build_integration_system_prompt(agent)
```

历史提示词和历史过滤现在通过：

```py
build_integration_history_prompt(...)
annotate_integration_history_events(...)
integration_history_event_matches_scopes(...)
```

robot 插件自己给 QQ 消息打 conversation scope，核心 history builder 只使用统一接口过滤。

### 重构 terminal session 的 robot 挂载

修改 `backend/app/services/agent/session.py`。

terminal alert 场景以前会直接判断 robot skill/MCP。

现在改成 integration hook：

- `should_enable_terminal_alert_integrations()`
- `ensure_terminal_alert_integration_tools()`
- `clear_terminal_alert_integration_tools()`

这样 terminal 管理功能不再直接依赖 robot。

### 调整 robot MCP 默认配置

修改 `backend/mcp_servers.json`。

`robot` MCP server 还保留在配置里，但默认：

```json
"enabled": false
```

原因是 robot 不应该作为 agent 核心默认必启的 MCP。QQ 唤醒或显式需要 robot 能力时，由 robot integration 临时挂载和启动。

### 更新测试

修改 `backend/tests/services/test_agent_runtime_guards.py`。

测试从“核心里有 robot 逻辑”的假设改成“robot 通过 integration 工作”的假设。

## 架构前后区别

### 重构前

简化结构如下：

```text
Agent Core
  ├─ chat_runtime.py
  │   └─ 直接处理 robot_id / robot_reply_target / robot_message_sent
  ├─ chat.py
  │   └─ 直接判断 QQ 是否需要补发、是否需要反思
  ├─ agent.py
  │   └─ 直接保存 robot_* 状态，直接给 robot MCP 注入参数
  ├─ prompts/
  │   └─ 直接拼 robot prompt 和 robot history 规则
  ├─ session.py
  │   └─ 直接处理 robot terminal alert 工具
  └─ mcp/server_manager.py
      └─ 直接内置 local + robot
```

问题：

- agent 核心知道太多 QQ robot 细节。
- 没有 robot bridge 时，核心里仍然存在 robot 路径，容易出现“想发 QQ 但 bridge 不存在”的错觉。
- `robot` MCP 默认启用，和核心能力绑得太紧。
- 群聊上下文、回复反思、fallback、MCP 参数注入散在多个核心文件里。
- 后续再接别的聊天平台时，只能继续往核心里加特殊分支。

### 重构后

简化结构如下：

```text
Agent Core
  ├─ integrations/
  │   ├─ contracts.py  # 插件协议
  │   ├─ registry.py   # 插件发现和热加载
  │   └─ hooks.py      # 核心调用入口
  ├─ chat_runtime.py
  │   └─ 只维护 integration_contexts
  ├─ chat.py
  │   └─ 只调用 delivery / fallback hook
  ├─ agent.py
  │   └─ 只调用 tool arg injection hook
  ├─ prompts/
  │   └─ 只聚合 integration prompt/history hook
  ├─ session.py
  │   └─ 只调用 terminal alert hook
  └─ mcp/server_manager.py
      └─ 核心只内置 local，其他 builtin server 来自插件

app.plugins.robot
  ├─ integration.py
  │   └─ 插件发现入口，只转发到 agent.integration
  ├─ agent/
  │   └─ integration.py  # robot 的 prompt / skill / MCP / 反思 / fallback / 历史隔离
  ├─ mcp/
  │   ├─ server.py       # robot MCP tools，例如 send_message、read_conversation_memory
  │   └─ context.py      # 当前 QQ 唤醒 turn 的上下文 token
  ├─ conversation_memory.py
  │   └─ 每个 QQ 会话独立 .log 记忆
  └─ service.py
      └─ robot bridge 入站消息、唤醒判定、队列调度
```

核心变化：

- agent 核心不 import robot 实现。
- robot 变成 `app.plugins.robot` 插件。
- robot MCP server 通过插件 factory 暴露，不再是核心内置。
- robot skill 通过插件暴露，不再是核心默认 skill。
- robot prompt/history/reply reflection/fallback 都由插件负责。
- 未来新增别的聊天平台时，可以新增 `app.plugins.xxx.integration`，不用继续污染 agent 核心。

## 当前 QQ 消息运行流程

### 1. Robot bridge 入站

`robot-bridge` 收到 QQ 消息后转给 backend 的 robot API。

`RobotService.handle_inbound_message()` 会先做两件事：

1. 计算 conversation key，例如 `group:770362397`。
2. 无论是否唤醒 agent，都写入对应 `.log` 记忆。

群聊日志路径由 `ROBOT_CONVERSATION_MEMORY_DIR` 控制，默认在：

```text
.runtime/robot_conversation_memory/<robot_id>/<群号>.log
```

私聊和频道会带类型前缀，例如：

```text
private-<user_id>.log
channel-<channel_id>.log
```

### 2. 唤醒判定

robot service 会按机器人配置判断消息类型：

- @ 机器人。
- 回复机器人。
- 已打开的 reply context window。
- 显式命令模式。

未命中的消息只写 `.log`，不会启动 agent turn。

命中的消息会带着 `robot_id`、`sender_key`、`reply_target`、`conversation_key` 进入 chat runtime。

### 3. Agent turn 建立插件上下文

chat runtime 组装：

```py
integration_contexts = {
    "robot": {
        "robot_id": "...",
        "sender_key": "...",
        "reply_target": ...,
    }
}
```

然后 integration 层调用 robot 插件：

- 注册当前 turn 的 `RobotMCPContext`。
- 生成 `_robot_context_token`。
- 记录当前 conversation key。
- 临时挂载 robot MCP server。

### 4. Agent 决定是否读取群聊记忆

robot 接上后所有消息都会写 `.log`，但不会自动把整份日志塞进 prompt。

agent 被唤醒后，如果需要上下文，可以调用 robot MCP：

```text
mcp_robot_read_conversation_memory
```

在 QQ 唤醒 turn 内，这个工具默认只能读当前 QQ 会话的 `.log`。这样可以避免 A 群唤醒后读到 B 群的日志。

### 5. Agent 回复反思

如果 agent 生成了普通最终回复，但没有调用：

```text
mcp_robot_send_message
```

并且当前 turn 存在 QQ 投递上下文，robot integration 会插入一次反思消息，让 agent 重新判断：

- 这段内容是否应该发到 QQ。
- 如果应该发，就调用 `mcp_robot_send_message`。
- 如果不应该发，就输出内部说明，不往 QQ 发。

这就是“回复前多一层反思”的位置。

### 6. Fallback 发回 QQ

如果是明确 QQ 唤醒，且 agent 最终还是没有调用发送工具，robot integration 还有最终 fallback：

- 内容非空。
- 当前 turn 有 `reply_target`。
- 是 @/回复机器人这类直接唤醒。
- 没有检测到 robot send tool 已经成功发送。

满足条件时，fallback 会通过 robot bridge 把最终回复发回当前 QQ 会话，并把 assistant 消息写入当前 `.log`。

## 无 robot 模式

当 `ROBOT_PLUGIN_ENABLED=false`，或者插件无法注册时：

- `app.plugins.robot.integration` 不会注册 `RobotAgentIntegration`。
- agent integration 注册表里没有 `robot`。
- `robot_messaging` 内置 skill 不会出现。
- `robot` builtin MCP factory 不存在。
- `mcp_server_manager.is_builtin_server_available("robot")` 返回 false。
- agent 核心不会通过 integration 层调用 robot bridge。
- terminal、普通 chat、local MCP、skill 加载仍然可用。

这就是现在的解耦点：没有 robot 时核心能力不依赖 robot。

## 有 robot 模式

当 `ROBOT_PLUGIN_ENABLED=true` 且 robot bridge 正常运行时：

- robot API 和 bridge 相关路由会启用。
- robot service 负责接收 QQ 入站消息。
- robot integration 会注册 `robot_messaging` skill。
- robot integration 会注册 `robot` MCP factory。
- QQ 唤醒 turn 会临时给当前 agent 挂载 robot MCP。
- agent 通过 MCP 读取当前聊天 `.log` 或发送 QQ 消息。

注意：`backend/mcp_servers.json` 里的 `robot.enabled=false` 不代表 robot 不可用。它只表示 robot MCP 不作为全局默认 server 启动。QQ 唤醒时 robot integration 仍然可以按需启动它。

## 热加载边界

现在有三层热加载：

- `reload_agent_integrations()`：重扫插件并注册 integration。
- `SkillLoader.reload()`：重载 skill，同时重载插件内置 skill。
- `MCPServerManager.reload_config()` / `reload_all()`：重载 MCP 配置，同时刷新插件 MCP factory。

插件开关由：

```env
ROBOT_PLUGIN_ENABLED=true
```

控制。改这个环境变量后通常需要重启 backend，或者通过已有 reload 流程让 manager/skill loader 重新加载。

## 群聊记忆隔离

群聊记忆现在按 conversation key 分文件：

```text
group:<群号>     -> <群号>.log
private:<用户号> -> private-<用户号>.log
channel:<频道号> -> channel-<频道号>.log
```

核心原则：

- 写入不需要唤醒 agent：robot 连接后，收到的入站消息都会写入对应 `.log`。
- 唤醒才叫 AI：只有 @/回复/上下文窗口命中时才启动 agent turn。
- 读取由 agent 决定：agent 被唤醒后通过 MCP 读取当前会话日志。
- QQ 唤醒 turn 默认锁定当前会话：当前群不能直接读其他群 `.log`。
- backend API 支持读、导出、导入、删除指定 conversation memory。

相关 API：

- `GET /robots/{id}/conversation-memory/{conversation_key}`
- `GET /robots/{id}/conversation-memory/{conversation_key}/export`
- `POST /robots/{id}/conversation-memory/{conversation_key}/import`
- `DELETE /robots/{id}/conversation-memory/{conversation_key}`

## 主要文件清单

新增：

- `backend/app/services/agent/integrations/__init__.py`
- `backend/app/services/agent/integrations/contracts.py`
- `backend/app/services/agent/integrations/registry.py`
- `backend/app/services/agent/integrations/hooks.py`
- `backend/app/plugins/robot/agent/integration.py`
- `backend/app/plugins/robot/mcp/context.py`
- `backend/app/plugins/robot/mcp/server.py`
- `docs/robot-agent-plugin-architecture.md`

重构：

- `backend/app/api/routes/chat.py`
- `backend/app/services/agent/agent.py`
- `backend/app/services/agent/chat_runtime.py`
- `backend/app/services/agent/mcp/server_manager.py`
- `backend/app/services/agent/prompts/builder.py`
- `backend/app/services/agent/prompts/system.py`
- `backend/app/services/agent/session.py`
- `backend/app/services/agent/skills/loader.py`
- `backend/mcp_servers.json`
- `backend/tests/services/test_agent_runtime_guards.py`

兼容 shim：

- `backend/app/services/agent/mcp/robot_context.py`
- `backend/app/services/agent/mcp/robot_server.py`
- `backend/app/plugins/robot/integration.py`
- `backend/app/plugins/robot/mcp_context.py`
- `backend/app/plugins/robot/mcp_server.py`

## 验证情况

已经跑过的检查：

- `ruff check --no-cache`：通过。
- `python -m compileall`：通过。
- 直接导入和关键函数检查：通过。
- robot MCP server 相关测试主体逻辑：通过。
- agent runtime guard 相关测试主体逻辑：通过。

当前环境限制：

- 这个沙箱下直接跑磁盘 SQLite pytest 会出现 `sqlite3.OperationalError: disk I/O error`。
- 改用内存 SQLite 后，测试逻辑通过，但 pytest 临时目录清理阶段有权限问题，导致少量 teardown 报错。

这些失败点是当前运行环境的文件系统权限问题，不是 robot 插件化逻辑本身的断言失败。

## 现在的架构结论

这次重构后，robot 不再是 agent 核心的一部分，而是一个可选插件。

核心 agent 只暴露 integration hook；robot 插件自己注册 QQ 相关能力。没有 robot 时，TermMan 仍然只做 terminal/agent/MCP/skill 管理；有 robot 时，robot 通过 MCP 和 skill 接入，并且按会话隔离唤醒、日志和回复投递。
