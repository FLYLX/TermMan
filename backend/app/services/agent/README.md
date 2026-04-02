# Agent 结构说明

## 这层负责什么

`agent/` 是 Agent 编排层。
它把两类输入统一成一条共享时间线：

- 手动聊天输入
- 终端过滤输出

然后负责：

- 组装 prompt
- 调 LLM
- 调 MCP 工具
- 保存会话历史到 SQLite
- 把可见事件通过 SSE 广播给前端

## 关键文件

- `agent.py`
  `ItemHandler` 对应的长生命周期 Agent。
  负责加载技能、MCP server、工具，并注入 item 上下文。

- `prompting.py`
  统一从 `backend/skills/system/SYSTEM_PROMPT.md` 读取 system prompt。
  这样 prompt 规则不再写死在路由或 session 里。

- `session.py`
  每个 item 一个 `AgentSession`。
  负责串行处理 chat/terminal 输入、LLM 循环、工具执行、事件落库。
  这里也负责隐藏静默工具的中间过程，比如 `mcp_local_read_terminal_log`。

- `stream_manager.py`
  终端输入侧的缓冲和分发层。
  当 agent 还没开始本轮处理时，持续累积 terminal 输出；
  一旦开始处理，后续输出进入下一轮队列。

- `chat_history.py`
  `ItemChatSession.messages` 的统一追加层。
  负责标准化消息结构，避免 JSON 原地修改导致 SQLite 不更新。

## 子目录

- `mcp/`
  MCP client/server 接入与工具执行。

- `memory/`
  长期记忆读写。

- `skills/`
  技能定义加载和管理。

- `tools/`
  内置工具。

## 共享时间线的数据流

1. 终端输出进入 `stream_manager.process_stream()`
2. 批量 flush 后进入 `AgentSession`
3. `session.py` 写入 `terminal_output / agent_response / agent_action ...`
4. 同时通过 `/chat/{item_id}/agent-events` 推给所有前端 viewer
5. 前端刷新时再从 `/memory/{item_id}/session` 还原整条时间线

## 你现在最常会改的地方

- 改 prompt 规则：
  `backend/skills/system/SYSTEM_PROMPT.md`

- 改手动 chat 路由：
  `backend/app/api/routes/chat.py`

- 改终端批处理或 session 队列：
  `stream_manager.py` / `session.py`

- 改 SQLite 时间线结构：
  `chat_history.py`
