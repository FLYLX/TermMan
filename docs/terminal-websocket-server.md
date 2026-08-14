# Terminal WebSocket Server

记录日期：2026-06-12

## 定位

`terminal_ws` 是内置 backend 插件，用来让用户在 WebUI 的某个终端详情页里按需创建 WebSocket Server。

它不是全局服务，也不会在 backend 启动时自动占用一个固定端口。每个 server 都绑定一个具体 terminal item，外部客户端连接后只能看到这个终端的 stdin/stdout/stderr，也只能向这个终端写入 stdin。

没有创建或启动 WebSocket Server 时，TermPaws 的核心终端管理、agent、skill、MCP、robot 插件都不受影响。

## 配置

```env
TERMINAL_WS_DEFAULT_HOST=0.0.0.0
TERMINAL_WS_DEFAULT_PORT_START=7100
TERMINAL_WS_DEFAULT_PORT_END=7199
TERMINAL_WS_DEFAULT_HEARTBEAT_INTERVAL_SECONDS=30
TERMINAL_WS_HOST_PORT_RANGE=7100-7199
```

字段含义：

- `TERMINAL_WS_DEFAULT_HOST`：WebUI 创建 server 时的默认监听地址。
- `TERMINAL_WS_DEFAULT_PORT_START` / `TERMINAL_WS_DEFAULT_PORT_END`：允许用户创建的端口池。
- `TERMINAL_WS_DEFAULT_HEARTBEAT_INTERVAL_SECONDS`：默认 WebSocket ping 间隔。
- `TERMINAL_WS_HOST_PORT_RANGE`：Docker Compose 映射到宿主机的端口范围。

## WebUI 流程

1. 打开某个终端详情页。
2. 在 `Terminal` tab 顶部的 `WebSocket Server` 区域填写 `Name`、`Host`、`Port`、`Token`、`Heartbeat`。
3. 点击 `Create` 创建这个终端专属的 server。
4. 点击 `Start` 后才会真正监听端口。
5. 使用列表里的 URL 连接，例如：

```text
ws://127.0.0.1:7100/?token=<server-token>
```

如果 server 的 Host 是 `0.0.0.0`，外部客户端连接时要把 `0.0.0.0` 换成宿主机或服务器 IP。

## API

所有接口都在当前用户权限下执行，普通用户只能管理自己的终端和自己的 WebSocket Server。

```text
GET    /api/v1/items/{item_id}/websocket-servers
POST   /api/v1/items/{item_id}/websocket-servers
POST   /api/v1/items/{item_id}/websocket-servers/{server_id}/start
POST   /api/v1/items/{item_id}/websocket-servers/{server_id}/stop
DELETE /api/v1/items/{item_id}/websocket-servers/{server_id}
```

创建请求：

```json
{
  "name": "External Tail",
  "host": "0.0.0.0",
  "port": 7100,
  "token": "optional-token",
  "heartbeat_interval": 30,
  "message_format": "json"
}
```

`port` 为空时 backend 会从端口池里分配一个未占用端口。`token` 为空时 backend 会生成一个随机 token。

## 认证

连接 WebSocket Server 时支持三种 token 传递方式：

```text
ws://127.0.0.1:7100/?token=<server-token>
Authorization: Bearer <server-token>
X-TermPaws-Token: <server-token>
```

## 握手

连接成功后，服务端先发送：

```json
{
  "type": "hello",
  "name": "External Tail",
  "version": 1,
  "client_id": "client id",
  "item_id": "terminal-item-uuid",
  "message_format": "json",
  "heartbeat_interval": 30
}
```

## 写入终端

```json
{
  "type": "write",
  "stdin": "ls\n"
}
```

也可以使用 `command` 字段：

```json
{
  "type": "write",
  "command": "pwd\n"
}
```

返回：

```json
{
  "type": "write_result",
  "item_id": "terminal-item-uuid",
  "success": true
}
```

客户端发送的 `item_id` 会被忽略，实际写入目标永远是创建这个 server 时绑定的终端。

## 终端流事件

每个连接会自动订阅绑定终端的 stream 事件：

```json
{
  "type": "stream",
  "item_id": "terminal-item-uuid",
  "stdout": "output text",
  "stderr": "",
  "stdin": "",
  "stream": "stdout",
  "source": "terminal",
  "ts": "2026-06-12T00:00:00+00:00"
}
```

`stream` 可能是 `stdin`、`stdout`、`stderr`、`mixed`。

`source` 用来区分来源，例如：

- `terminal`：daemon 上报的终端输出。
- `browser`：WebUI 终端页写入。
- `backend`：backend 内部写入。
- `terminal_ws`：外部 WebSocket 客户端写入。
- `sdk`：InputSDK 写入。

`subscribe` / `unsubscribe` 只返回确认帧，不会改变绑定目标：

```json
{
  "type": "subscribe"
}
```

```json
{
  "type": "subscribed",
  "item_id": "terminal-item-uuid"
}
```

## 架构边界

源码位置：

```text
backend/app/plugins/terminal_ws/
  __init__.py
  api.py
  plugin.py
  server.py
```

加载路径：

```text
PluginManager
  -> app.plugins.terminal_ws.plugin
  -> include_router()
  -> WebUI/API create/start/stop/delete server
```

终端流接入点：

```text
ItemSocket.on_stream()
  -> subscription_center.publish_stream()
  -> TerminalWebSocketServer per-client subscription callback
```

终端写入接入点：

```text
TerminalWebSocketServer.write
  -> socket_pool_facade.write_to_item(bound_item_id, ..., source="terminal_ws")
  -> ItemSocket.write()
  -> subscription_center.publish_stream(stdin)
```

这个插件只通过 PluginManager、API router、subscription_center、socket_pool_facade 接入核心链路；未创建 server、未启动 server、或没有外部客户端连接时，不会改变普通终端行为。
