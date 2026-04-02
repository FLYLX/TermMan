# Socket Pool 结构说明

## 这层负责什么

`socket_pool/` 是 item 级别的终端运行时层，负责：

- backend 监听 daemon room
- browser 查看 item 终端
- 终端输出分发
- 终端命令写入
- 订阅 SDK / 输入 SDK

## 关键文件

- `item_socket.py`
  单个 item 的 socket 封装。负责接 daemon room 的事件，再转给订阅中心。
- `socket_manager.py`
  管理 socket 实例表和 item token 表。
- `service_facade.py`
  socket_pool 的窄接口门面。给上层 service / route 用，避免直接操作 `SocketManager` 和 `ItemSubscriberSDK`。
- `event_bus.py`
  纯事件总线。只做 subscribe / unsubscribe / publish。
- `terminal_stream_pipeline.py`
  终端 stream 管线。把 daemon 的 stream 事件发布进事件总线。
- `agent_bridge.py`
  agent 输入桥接器。把终端输出转成 agent 可消费的 raw / filtered 输入。
- `subscription_center.py`
  对外兼容层，组合 `event_bus + pipeline + bridge`。
- `subscriber_sdk.py`
  对订阅中心的轻量封装。
- `input_center.py`
  item 命令输入中心。
- `input_sdk.py`
  对 `input_center` 的轻量封装。

## 两条主链路

### 输出链路

`ItemSocket`
-> `subscription_center.publish_stream(...)`
-> `TerminalStreamPipeline`
-> `ItemEventBus`
-> 日志订阅器 / 前端订阅器 / 其他 subscriber
-> `AgentInputBridge`
-> `agent.stream_manager`

### 输入链路

调用方
-> `InputSDK` / `InputCenter`
-> backend socket handler
-> daemon room socket write

## 关键运行时状态

- socket 表
  `(user_uuid, item_uuid, subscriber_type) -> ItemSocket`
- token 表
  `daemon_id -> {item_uuid: token}`
- subscriber 表
  `item_uuid -> callbacks`

## 排障建议

- 前端没看到终端输出：先看 `event_bus.py` / `terminal_stream_pipeline.py`
- 日志没写进去：先看 `subscriber_sdk.py`
- Agent 没处理终端输出：先看 `agent_bridge.py`
- 命令发不进终端：先看 `input_center.py` / `socket_manager.py`
