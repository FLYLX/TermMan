# TermPaws Memory 方案

本文档记录 TermPaws 当前采用的 Agent 记忆方案。目标不是把所有历史都塞给模型，而是让 Agent 在 QQ、后台聊天、终端事件和工具调用场景里稳定记住真正可复用的信息，同时降低旧记忆污染和幻觉。

## 选型

当前方案采用 **Mem0-like 轻量长期记忆 + MemoryOS 分层思想**。

不直接采用 MemOS、MemTree、Zep 这类重方案，原因是 TermPaws 的核心问题不是大规模关系推理，而是：

- 记住用户偏好、项目事实、当前任务和已知错误。
- 在 QQ/Robot 上下文中知道该调用发送工具。
- 在终端报错时能找回相关历史处理经验。
- 不让过期、已完成、已解决的旧信息误导 Agent。

因此当前最合适的是轻量可控方案：短期上下文 + 会话摘要 + 向量长期记忆 + 知识库 RAG + Skill/tool policy。

## 记忆分层

### 短期记忆

来源：

- 最近聊天消息
- 终端过滤输出
- Agent 工具执行结果
- QQ 消息上下文戳

用途：

- 保持当前回合和近期对话连贯。
- 让 Agent 知道这次 QQ 消息来自哪个 conversation。
- 让工具调用结果回填给 LLM 继续判断。

实现位置：

- `backend/app/services/agent/history/chat.py`
- `backend/app/services/agent/prompts/builder.py`

### 会话摘要

来源：

- timeline / chat history 中生成的 session summary。

用途：

- 压缩长对话。
- 避免每次塞入大量历史消息。

实现位置：

- `backend/app/services/agent/history/chat.py`
- `SESSION_SUMMARY_TYPE`

### 长期记忆

存储：

- embedding：`sentence-transformers/all-MiniLM-L6-v2`
- 向量库：ChromaDB
- collection：`item_memories`
- 持久化目录：`CHROMA_PERSIST_DIR`

类型：

- `fact`：稳定事实，例如路径、端口、部署方式。
- `preference`：用户偏好，例如回复语言、简洁程度。
- `task`：当前任务，带 `active/completed` 状态。
- `error`：已知错误，带 `active/resolved` 状态。
- `context`：项目结构、运行环境、系统关系。

实现位置：

- `backend/app/services/agent/memory/vector_store.py`
- `backend/app/services/agent/prompts/policy.py`
- `backend/app/services/agent/prompts/builder.py`

### 知识库

存储：

- ChromaDB collection：`shared_knowledge`
- 支持文件：`.md`、`.markdown`、`.txt`

用途：

- 存放共享文档、部署说明、操作手册。
- 只读取当前 ItemHandler 已启用的知识文件。

实现位置：

- `backend/app/services/agent/knowledge/service.py`

## 写入策略

长期记忆不是自动保存所有对话，而是按规则保存稳定信息。

会写入的情况：

- 用户明确说“记住/保存/remember/save”。
- 用户确认上一条 assistant 结论是正确事实。
- 用户说任务已完成，更新 `task` 状态。
- 用户说错误已解决，更新 `error` 状态。
- 手动通过记忆面板新增。
- Agent 调用 local MCP 的 `save_memory`。

会拒绝的内容：

- 原始日志、命令回显、stack trace。
- 等待状态，例如“命令已发送，等待反馈”。
- 敏感信息，例如 token、password、secret、api key。
- 太长、太泛、不可复用的信息。

## 读取策略

默认读取长期记忆：

- 后台聊天 / QQ 聊天：最多 5 条。
- 终端过滤输出：最多 3 条。
- 终端 raw feedback：关闭长期记忆。

raw feedback 关闭的原因：

命令刚发送后的原生日志确认必须只看当前终端反馈。否则 Agent 容易用旧记忆脑补“命令成功/失败”。

### 召回过滤

`vector_store.search_memories()` 默认会过滤：

- 已过期记忆。
- `task.status == completed`。
- `error.status == resolved`。

管理页面搜索会显式允许查全量，避免用户找不到已完成/已过期记录。

### 召回排序

prompt builder 不再只按向量距离截断，而是综合排序：

- 向量相关性。
- 记忆类型权重。
- `verified` 可信度。
- `updated_at / created_at` 新鲜度。

类型优先级：

- `preference`：用户偏好优先。
- `task`：当前活动任务优先。
- `error`：当前活动错误优先。
- `context`：项目/运行上下文。
- `fact`：普通事实。

注入 prompt 时会带标签：

```text
- [preference, verified] 用户偏好：以后回复简洁中文
- [task, active] 当前任务：修复 robot bridge 卡顿
- [context] Robot bridge 通过 OneBot V11 WebSocket 接入 NapCat
```

这样 LLM 能区分这是偏好、任务、错误还是背景事实。

## QQ / Robot 场景

QQ 消息进入 Agent 时会带上下文戳，例如：

```text
[Robot message; conversation=private:2537134688; sender=FLY (2537134688)]
```

Agent 不应该直接把普通文本当作 QQ 回复发出，而是：

1. 从当前上下文判断是否需要回复 QQ。
2. 需要回复时调用 `mcp_robot_send_message`。
3. MCP 根据当前 QQ 上下文或 LLM 指定的 conversation 发送。

这部分主要靠：

- `robot_messaging` skill
- robot MCP tool 描述
- Agent tool calling / ReAct-like loop
- QQ 上下文目标解析

工具策略不建议全部放进普通长期记忆。长期记忆可以记录稳定经验，但“什么时候必须调用哪个工具”优先放在 skill / system prompt / MCP tool schema。

## 知识库和长期记忆的区别

长期记忆：

- 和 Item 绑定。
- 存用户偏好、任务状态、历史错误、项目事实。
- 内容短、强筛选、可更新状态。

知识库：

- 和 ItemHandler 绑定。
- 存文档、手册、部署说明。
- 内容较长，按文件切块检索。

两者都会进 prompt，但来源和用途不同。

## 当前已实现

- 长期记忆默认开启读取。
- 向量库默认过滤过期/已完成/已解决记忆。
- prompt 召回按相关性、类型、verified、新鲜度排序。
- prompt 注入长期记忆标签。
- 知识库读取只同步必要文件，避免每次对话全库扫描。
- 知识库失败时跳过，不阻断 Agent 回合。
- 终端 raw feedback 关闭长期记忆和知识库，降低命令结果幻觉。

## 后续可做

- 为 QQ 记忆增加 `robot_id / conversation / sender` metadata 范围过滤。
- 增加工具调用成功/失败案例的专门记录，但仍由 skill/tool policy 主导工具选择。
- 增加 memory reranker，在候选很多时用轻量 rerank 再注入。
- 后续如果记忆规模变大，可以抽象 `MemoryBackend`，从 Chroma 切到 Qdrant 或 Mem0 OSS。

