# Agent、短期记忆、长期记忆系统重设计

## 目标

这份设计解决 6 件事：

1. Agent 不再把“当前终端现场”和“历史长期记忆”混在一起，减少幻觉。
2. 前端、后端、终端共享同一条 `item` 时间线，刷新后仍能从 SQLite 恢复。
3. 短期记忆不再等于“把全部历史原样塞进 prompt”，而是分层裁剪。
4. 长期记忆只保存稳定、可复用、已验证的信息，不保存原生日志垃圾。
5. 命令发送后的反馈读取只看原生日志，不靠过滤输出猜。
6. Agent 能实时工作、可中断、可恢复，并且不容易陷入重复读日志 / 重复发命令。

---

## 一句话架构

按 `item` 维度，把记忆拆成三层：

1. `运行态工作记忆`
   只存在内存里，服务当前回合。
2. `共享短期记忆`
   落在 SQLite 的 `ItemChatSession.messages`，是刷新恢复和多端同步的真相源。
3. `长期记忆`
   落在向量库，只保存稳定事实、偏好、任务摘要、错误经验。

核心原则：

`Agent 当前要做的判断，优先依赖当前 item 的短期记忆和实时终端反馈；长期记忆只能辅助，不能主导当前终端判断。`

---

## 一、当前问题

结合现有实现，问题本质不是“没有记忆”，而是“记忆边界不清楚”：

1. `session.py` 里的 terminal turn 之前会做向量检索，容易把旧上下文带进当前终端判断。
2. `ItemChatSession.messages` 现在更像事件日志，但还缺少明确的“短期记忆语义”。
3. 向量库里什么都可能进，容易把一次性的日志、错误猜测、命令回显也当成长期知识。
4. 命令已经发出后，Agent 还可能根据旧记忆或旧模式重新发送同一条命令。
5. 前端看到的是聊天和状态混在一起，用户会误以为 Agent 已经确认了某件事，但其实它只是“等待反馈”。

所以这次设计的重点不是“再多存一点”，而是：

`什么该存在 SQLite，什么该进向量库，什么只该活在当前回合里。`

---

## 二、总体模型

### 2.1 共享单位

所有记忆都以 `item` 为主作用域：

- 一个 `item` 只有一个共享 `AgentSession`
- 一个 `item` 只有一条共享短期时间线
- 一个 `item` 有一组长期记忆
- 同时打开这个 `item` 的所有浏览器看到同一份状态和历史

当前版本不再把“每个浏览器 tab 的会话”当成独立记忆源。

### 2.2 三层记忆

#### A. 运行态工作记忆

只存在 `AgentSession` 内存里，不持久化：

- 当前 turn 的 `turn_id`
- 当前状态 `idle / collecting / running / waiting_terminal / interrupting`
- 当前待确认命令 `pending_command`
- 当前轮最近几步动作
- 当前轮最近一次进展指纹
- 当前轮日志读取指纹
- 当前轮队列和中断标记

这是 Agent 的“工作台”，不是历史档案。

#### B. 共享短期记忆

落在 SQLite 的 `ItemChatSession.messages`：

- 用户输入
- 过滤后的终端输出事件
- Agent 最终回复
- warning / error
- 轻量 action 摘要
- 必要时的工具结果摘要

它既是：

- 刷新恢复源
- 多 viewer 共享时间线
- 后续 turn 的最近上下文来源

#### C. 长期记忆

落在 `vector_store.py` 对应的向量库里：

- 稳定事实 `fact`
- 用户偏好 `preference`
- 中长期任务上下文 `task`
- 已验证的错误经验 `error`
- 项目结构或组件关系 `context`

长期记忆不应该直接等于聊天记录，也不应该自动把所有 terminal 输出都吸进去。

---

## 三、短期记忆设计

短期记忆不是一层，而是三段。

### 3.1 S0：原始共享时间线

继续复用 `models.py` 里的：

- `ItemChatSession.messages: List[dict]`

不做 SQL schema 迁移，只统一消息语义。

建议事件形状：

```json
{
  "role": "user | assistant | terminal",
  "type": "chat_user | terminal_output | agent_action | agent_tool_result | agent_response | agent_warning | agent_error | session_summary",
  "content": "string",
  "timestamp": "ISO8601",
  "turn_id": "optional",
  "tool_name": "optional",
  "command_id": "optional",
  "terminal_source": "filtered_output | raw_feedback",
  "meta": {}
}
```

其中：

- `terminal_output` 永远表示前端可见的终端块
- `agent_status` 这类状态事件默认不入库
- `session_summary` 是后面短期压缩用的摘要事件

### 3.2 S1：当前会话摘要

当一条 `item` 时间线越来越长时，不能每次全量读取最近几百条。

需要增加一个“短期摘要层”，但仍然落在 SQLite，而不是新建表：

- 定期把旧消息压缩成 1 条 `session_summary`
- 该摘要描述最近阶段的任务、关键命令、已知结论、未完成事项
- 被摘要覆盖的原始消息仍可保留，但默认不再进入 prompt 主窗口

推荐摘要触发条件：

- 满 `40 ~ 80` 条正式消息
- 或累计 `8k ~ 12k` 字符
- 或一个明显任务阶段结束时

摘要内容建议只保留：

- 当前目标
- 最近已确认的问题
- 已执行过且确认过结果的关键命令
- 当前未解决阻塞
- 用户明确要求 / 约束

不要把大段原生日志复制进摘要。

### 3.3 S2：当前 turn 工作窗口

真正送给 LLM 的不是完整 SQLite 历史，而是一个裁剪后的工作窗口：

- 最近 6~12 条关键正式事件
- 最新一条 `session_summary`
- 当前输入
- 如果是命令反馈，则加当前 pending command 上下文

这层是 prompt builder 产物，不落库。

---

## 四、长期记忆设计

长期记忆必须是“提炼后的知识”，不是“复制后的历史”。

### 4.1 长期记忆允许保存什么

#### `fact`

稳定事实，例如：

- 某个 item 的工作目录
- 某个脚本真实路径
- 某个服务端口或固定命令
- 某个组件文件的稳定位置

#### `preference`

用户偏好，例如：

- 回复简洁
- 优先中文文档
- 不把状态写进聊天框
- 命令反馈要看 raw log

#### `task`

中长期任务上下文，例如：

- 这个 item 当前在做什么
- 这个修复还剩什么没做
- 某项任务已暂停 / 已完成 / 已放弃

#### `error`

已验证的错误经验，例如：

- 某类报错出现时应优先检查哪个目录
- 某个命令在这个环境下无输出是正常的
- 某个 daemon 重连后状态需要重新探测

前提是“解决方案已经被验证过”，不是 Agent 自己猜的。

#### `context`

项目背景，例如：

- 某 service 的职责
- 某条链路的结构
- 某个 SDK 的调用方式

### 4.2 长期记忆禁止保存什么

以下内容默认不进入向量库：

- 原生日志全文
- 过滤输出原文块
- 命令回显
- “命令已发送，等待反馈”这类状态
- 未验证的推断
- 一次性的 stdout 噪音
- 包含 token / 密钥 / 敏感配置的文本

一句话：

`长期记忆保存知识，不保存现场噪音。`

### 4.3 长期记忆写入策略

长期记忆不要每轮自动写。

建议改成“候选 -> 过滤 -> 去重 -> 入库”的四步：

1. `MemoryCandidateExtractor`
   从当前 turn 最终结果里提取候选记忆。
2. `MemoryPolicy`
   判断是否稳定、是否敏感、是否值得长期保存。
3. `Dedup`
   走现有向量相似度去重，再加一层文本哈希去重。
4. `VectorStore`
   真正写入向量库。

推荐只在以下时机提取长期记忆：

- Agent 最终回复结束后
- 用户明确确认“这个结论是对的”
- 某个错误已经被验证解决
- 某条偏好被用户重复表达

### 4.4 长期记忆 TTL 建议

虽然现在实现里默认 TTL 是 30 天，但设计上建议分类型：

- `preference`: 180 天
- `fact`: 90 天
- `task`: 14 天或任务完成即删除
- `error`: 30~60 天
- `context`: 30 天

这样能减少旧记忆长期污染当前判断。

---

## 五、记忆读取策略

真正重要的是“什么时候允许读长期记忆，什么时候禁止读”。

### 5.1 手动聊天 turn

用户主动聊天时，允许读取：

- 最新 `session_summary`
- 最近几条短期正式事件
- 相关长期记忆

适合的场景：

- 问项目结构
- 追问之前做了什么
- 要求继续某个任务

### 5.2 普通过滤终端 turn

终端过滤输出触发分析时，默认只读取：

- 最新 `session_summary`
- 最近相关的短期正式事件

长期记忆默认关闭，或只允许极少量 `error/context` 辅助。

原因很简单：

终端现场判断应该优先依赖当前现场，不应被旧向量记忆带偏。

### 5.3 命令反馈 turn

命令已经发出后，反馈读取必须最严格：

- 只读取 pending command 上下文
- 只读取 raw log delta / tail
- 不读长期记忆
- 不重新发同一条命令

这里要贯彻一条硬规则：

`命令反馈阶段，Agent 只能解释日志，不能凭历史记忆脑补结果。`

### 5.4 显式记忆类工具

当用户明确要求：

- 列记忆
- 查记忆
- 保存记忆
- 删除记忆

这类 turn 才直接走长期记忆层。

---

## 六、Prompt 组装规则

### 6.1 Terminal turn

Terminal turn 的 prompt 建议分三种。

#### A. 普通过滤终端分析

输入：

- system prompt
- 最新 `session_summary`
- 最近相关短期事件
- 当前过滤后的 terminal batch

不默认加长期记忆。

#### B. 命令原生日志反馈

输入：

- system prompt
- pending command 描述
- 当前 raw log delta / raw tail
- 必要的上一条 agent action

禁止注入长期记忆。

system prompt 里要明确：

- 不要重复发送同一命令
- 不要根据旧记忆假设命令执行成功
- 没有日志证据就不能下结论

#### C. 空输出 / 纯回显 / prompt 返回

这类应尽量由后端状态机直接收口：

- 纯回显且无新输出：继续等待或进入静默确认
- prompt 返回且无输出：生成“命令无输出”结果
- 超时仍无新反馈：生成 warning

这类结果不值得再交给 LLM 做自由推理。

### 6.2 Chat turn

Chat turn 可以更宽松：

- system prompt
- 最新 session summary
- 最近几条用户 / assistant 正式消息
- 相关长期记忆

但也不要把整条 SQLite 全塞进去。

---

## 七、短期记忆写入规则

### 7.1 必写入 SQLite 的正式事件

这些应该继续走 `chat_history.py`：

- `chat_user`
- `terminal_output`
- `agent_response`
- `agent_warning`
- `agent_error`
- 轻量 `agent_action`
- 必要时的摘要型 `agent_tool_result`
- `session_summary`

### 7.2 不建议写入 SQLite 的事件

这些只走 SSE 状态更合适：

- `collecting`
- `running`
- `waiting_terminal`
- `interrupting`
- `idle`
- 细粒度“思考中”

因为这些不是历史知识，而是瞬时 UI 状态。

### 7.3 工具结果写入策略

工具结果不要原样全写：

- 长结果先裁剪
- 原生日志不写入 `agent_tool_result`
- 只保存用户未来还需要知道的摘要

例如：

- 保存 `已读取最近 80 行日志，发现 cron_job.py 路径为 /app/src/cron_job.py`
- 不保存整段日志原文

---

## 八、长期记忆提取规则

建议把长期记忆提取做成一个独立策略层，不要散在 session 里。

### 8.1 候选来源

候选长期记忆只从这些地方来：

- 最终 `agent_response`
- 用户明确确认的结论
- 经过验证的 `agent_tool_result` 摘要
- 用户偏好类输入

### 8.2 提取条件

满足以下至少一条才考虑入长期记忆：

- 对未来明显可复用
- 在当前 item 下具有稳定性
- 用户明确重复提过
- 已经被工具结果或日志验证过

### 8.3 过滤条件

满足以下任一条则拒绝入库：

- 只是一次性日志
- 只是等待态 / 排队态
- 只是命令回显
- 只是模型推测，没有证据
- 内容太长且未压缩
- 涉及敏感信息

### 8.4 更新策略

长期记忆不是只增不改。

建议：

- `task` 记忆可更新状态
- `error` 记忆可被新解法覆盖
- `fact` 记忆若新旧冲突，以最新已验证结果替换
- `preference` 记忆以用户最近明确表达为准

---

## 九、反幻觉与防死循环规则

记忆系统必须和执行系统一起设计，否则会把旧错误固化。

### 9.1 不允许的行为

- 命令已发送但未见反馈，又重新发同一命令
- 看到纯回显，就脑补命令结果
- 把旧长期记忆当成当前终端证据
- 连续重复读相同日志却仍继续循环
- 把“等待反馈”当成正式回复写进聊天框

### 9.2 必须的保护

- pending command 存在时，禁止再次发同类命令
- raw feedback turn 不读取长期记忆
- 相同日志指纹重复出现时停止本轮
- 纯状态事件不进入长期记忆
- session summary 只能基于正式事件生成，不能基于状态噪音生成

### 9.3 后端优先收口的场景

以下场景优先由后端状态机收口，不交给 LLM自由发挥：

- 命令超时
- 命令只有回显
- prompt 返回但无输出
- 连续相同日志读取
- 当前轮被用户中断

---

## 十、组件职责重分配

### `session.py`

负责：

- turn 生命周期
- pending command 状态
- 当前轮工作记忆
- prompt 组装调度
- 反循环和中断

不负责：

- 原始长期记忆直接决策
- 无边界地拼全部历史

### `chat_history.py`

负责：

- SQLite 正式事件落库
- 批量追加
- 读取共享短期时间线
- 后续 session summary 落库

不负责：

- 长期知识提取
- 向量检索

### `vector_store.py`

负责：

- 长期记忆存储
- 向量检索
- 去重
- TTL / 压缩

不负责：

- 直接承载一整条会话历史

### `stream_manager.py`

负责：

- 过滤终端输出聚合
- collecting / running 边界
- 命令反馈时 raw / filtered 双轨切换

### 建议新增 `memory_policy.py`

负责：

- 长期记忆候选提取
- 入库策略
- 类型判定
- 敏感信息过滤
- TTL 选择

### 建议新增 `prompt_builder.py`

负责：

- 根据 turn 类型构造真正送给 LLM 的消息窗口
- 不再由 `session.py` 自己拼全部细节

---

## 十一、推荐数据结构

### 11.1 AgentSession 运行态

建议至少维护：

- `state`
- `active_turn_id`
- `current_collecting_batch`
- `pending_command`
- `pending_terminal_batches`
- `pending_chat_inputs`
- `recent_step_fingerprints`
- `last_progress_fingerprint`
- `last_session_summary_id`

### 11.2 SessionSummary

虽然不新建 SQL 表，但逻辑上应有这个对象：

- `summary_id`
- `item_id`
- `covers_message_range`
- `content`
- `created_at`

落库时表现为一条 `type=session_summary` 的消息。

### 11.3 LongTermMemoryCandidate

建议逻辑对象：

- `content`
- `memory_type`
- `source_turn_id`
- `stability_score`
- `confidence_score`
- `verified`
- `ttl_days`

---

## 十二、推荐流程

### 12.1 用户聊天

1. 前端发送消息
2. 立刻写入 SQLite：`chat_user`
3. session 创建一个 chat turn
4. prompt builder 取：
   - 最新 session summary
   - 最近正式消息
   - 相关长期记忆
5. 生成最终回复
6. 写入 SQLite：`agent_response`
7. 如有稳定知识，再走长期记忆候选提取

### 12.2 普通过滤终端输出

1. daemon 输出经过 filter
2. `stream_manager` 聚合成 batch
3. 写入 SQLite：`terminal_output`
4. session 创建 terminal turn
5. prompt builder 只取短期窗口，不默认取长期记忆
6. 如果需要发命令，则进入 pending command 状态

### 12.3 命令反馈

1. 工具发送命令成功
2. 只发状态：等待终端反馈
3. 后端监听 raw log delta / tail
4. 若读到真实反馈，则创建 raw feedback turn
5. 该 turn 只看：
   - pending command
   - raw log
   - 最近一条相关 action
6. 若结果已明确，直接生成最终回复或 warning
7. 不得重新发同一命令

---

## 十三、实施顺序

建议按下面顺序落地。

### 第一阶段

先把边界定住：

- terminal turn 默认不读长期记忆
- pending command turn 完全不读长期记忆
- “等待终端反馈”只做状态，不入聊天框

### 第二阶段

再补短期摘要层：

- `session_summary` 生成
- prompt 只读摘要 + 最近窗口

### 第三阶段

再补长期记忆策略层：

- 候选提取
- 入库过滤
- 类型化 TTL

### 第四阶段

最后补管理能力：

- 记忆审查
- 记忆删除 / 合并
- 任务记忆更新

---

## 十四、验收标准

这套系统落地后，至少要满足：

1. 用户刷新前端后，能从 SQLite 恢复共享时间线。
2. 普通 terminal 分析不会被旧长期记忆带偏。
3. 命令发送后，反馈判断只依赖 raw log，不会凭空脑补结果。
4. 相同命令在 pending 状态下不会重复发送。
5. 长期记忆库里看不到大段原生日志和等待态垃圾。
6. 会话越长，prompt 仍可控，不会因为全量历史失控。
7. 用户能实时看到状态，但聊天框只看到正式内容。

---

## 结论

这套系统的核心不是“让 Agent 记住更多”，而是：

- `当前现场` 用短期记忆和实时反馈解决
- `稳定知识` 才进长期记忆
- `工作判断` 必须服从当前 item 的真实状态

最关键的三条规则：

1. `共享时间线是短期记忆基座，SQLite 是刷新后的真相源。`
2. `长期记忆只存稳定知识，不存日志噪音。`
3. `命令反馈阶段只看 raw log，不看长期记忆，不重复发命令。`
