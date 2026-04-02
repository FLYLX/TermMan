# Connection Pool 结构说明

## 这层负责什么

`connection_pool/` 管的是 Backend 到 Daemon 的主连接。
这是控制面，不是 item 房间监听面。

它主要服务这些动作：

- `terminal/start`
- `terminal/stop`
- `terminal/restart`
- `terminal/status`
- `terminal/list`
- `connections/get_all`

## 关键文件

- `connection_models.py`
  连接相关状态模型。
  包括：
  - `DaemonConfig`
  - `ConnectionStatus`
  - `RoomListenConnection`
  - `DaemonMainConnState`
  - `BackendConnPool`

- `daemon_connection.py`
  单个 daemon 主 Socket.IO 连接的封装。
  负责鉴权、请求响应、接收 daemon 推送事件，比如 `connection_update`。

- `connection_manager.py`
  主连接注册表。
  按 `daemon_id` 维护 `DaemonConnection`，给 items API 和启动恢复流程使用。

## 和 `socket_pool/` 的边界

- `connection_pool/`
  管主连接，偏控制 RPC。

- `socket_pool/`
  管 item room 连接，偏实时输出和浏览器交互。

## 运行时有两块状态

- `ConnectionManager`
  真正活着的 daemon 主连接对象。

- `BackendConnPool.daemon_main_conn_state`
  daemon 主连接状态镜像。
  `items.py` 里的 `daemon_online` 就是从这里算的。

## Backend 重启后的恢复逻辑

`daemon_initializer.sync_daemon_connection_state()` 会：

1. 重连 daemon 主连接
2. 调 `terminal/list` 拉取 daemon 当前终端快照
3. 把 daemon 里的终端状态映射回 `Item.status`
4. 对 running item 恢复 backend room 监听

所以现在 backend 重启后，不应该再把 daemon 里正在运行的 item 全部写成 `stopped`。
