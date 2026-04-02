# Subscription Center 说明

## 现在的结构

`subscription_center.py` 不再自己承担所有逻辑，而是一个兼容外壳，内部拆成了 3 层：

- `event_bus.py`
  纯事件总线，只负责订阅、退订、按 item 分发事件。
- `terminal_stream_pipeline.py`
  终端 stream 管线，只负责把 daemon 推来的 `stdout/stderr/...` 变成结构化事件并发布到事件总线。
- `agent_bridge.py`
  Agent 输入桥接器，负责：
  - 找到 item 对应的 handler
  - 读取 item 的 input filter 配置
  - 组装 raw / filtered 输出
  - 调用 `agent.stream_manager.process_stream(...)`

## 当前处理顺序

`ItemSocket` 收到 daemon stream 之后：

1. 调 `subscription_center.publish_stream(item_uuid, data)`
2. `TerminalStreamPipeline` 先把事件发布到 `ItemEventBus`
3. 已订阅的日志写入器、前端订阅器、其他 subscriber 先收到事件
4. `subscription_center` 再调用 `AgentInputBridge`
5. `AgentInputBridge` 做过滤并把数据送进 agent 会话流

这个顺序保证：

- 日志/前端看到的是原始终端事件
- Agent 处理拿到的是 raw + filtered 双轨输入
- “先订阅者，后 agent” 的行为保持不变

## 为什么这样拆

之前 `subscription_center.py` 同时做了：

- 订阅表管理
- stream 分发
- 数据库查 handler
- input filter
- agent 触发

这会导致它既像事件总线，又像业务编排器，边界太糊。

现在拆开后：

- 事件问题先看 `event_bus.py`
- stream 顺序问题先看 `terminal_stream_pipeline.py`
- Agent 没接到、过滤异常、handler 没找到，先看 `agent_bridge.py`

## 对外兼容

外部调用面保持不变，现有代码仍然可以继续使用：

- `subscription_center.subscribe(...)`
- `subscription_center.unsubscribe(...)`
- `subscription_center.publish_stream(...)`
- `subscription_center.publish_connected(...)`
- `subscription_center.publish_disconnected(...)`
- `subscription_center.publish_auth_error(...)`
