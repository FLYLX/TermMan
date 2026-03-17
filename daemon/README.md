# TermMan Daemon

TermMan Daemon是一个终端管理守护进程，负责管理和运行终端进程，并通过WebSocket与Backend进行通信。

## 目录结构

```
daemon/
├── pyproject.toml            # 项目配置
├── .env                      # 环境变量配置
├── .env.example              # 环境变量示例
├── src/
│   ├── __init__.py           # Python包标记
│   ├── core/                 # 核心模块
│   │   ├── __init__.py
│   │   ├── config.py         # 配置管理
│   │   ├── memory_store.py   # 内存存储
│   │   ├── file_storage.py   # 文件存储
│   │   └── global_instances.py # 全局实例管理
│   ├── service/              # 业务服务
│   │   ├── __init__.py
│   │   ├── terminal_manager.py # 终端进程管理
│   │   └── socket_service.py   # Socket.IO连接池管理
│   ├── api/                  # API接口
│   │   ├── __init__.py
│   │   ├── http_routes.py    # HTTP路由（健康检查、文件操作）
│   │   └── socket_routes.py  # WebSocket路由（主要通信方式）
│   ├── utils/                # 工具模块
│   │   ├── __init__.py
│   │   └── logger.py         # 日志工具
│   ├── data/                 # 数据目录
│   │   ├── config.json       # 配置文件
│   │   └── terminals/        # 终端配置
│   ├── workdir/              # 终端工作目录
│   └── main.py               # 入口文件
└── log/                      # 应用日志目录
```

## 连接池表结构

Daemon维护三张核心连接表，用于管理Backend连接和终端连接：

### 1. Backend连接表
```
[sid -> {backend_id, ip, connected_at}]
```
- 记录所有已认证的Backend WebSocket连接
- `sid`: Socket.IO会话ID
- `backend_id`: Backend标识（格式：`{ip}:{apikey前8位}`）
- `ip`: Backend的IP地址
- `connected_at`: 连接时间

### 2. Item-Token映射表
```
{item_uuid: token}
```
- 记录每个终端实例的访问Token
- `item_uuid`: 终端实例UUID
- `token`: 访问Token（UUID格式）

### 3. Item-连接映射表
```
[item_uuid -> {sid -> {user_uuid, ip}}]
```
- 记录每个终端实例的所有WebSocket连接
- `item_uuid`: 终端实例UUID
- `sid`: Socket.IO会话ID
- `user_uuid`: 用户UUID（backend连接标记为"backend"）
- `ip`: 用户IP地址

## HTTP API路由

| 路径 | 方法 | 认证 | 描述 |
|------|------|------|------|
| `/` | GET | 无 | Daemon健康检查 |
| `/api/status` | GET | 无 | 获取Daemon状态 |
| `/api/health` | GET | 无 | 健康检查 |
| `/api/file/upload` | POST | X-API-Key | 文件上传（预留） |
| `/api/file/download` | GET | X-API-Key | 文件下载（预留） |

### 示例

**获取Daemon状态**
```bash
curl http://localhost:9000/api/status
# 响应: {"success": true, "version": "0.1.0", "status": "running", "terminal_count": 2}
```

**健康检查**
```bash
curl http://localhost:9000/api/health
# 响应: {"status": "ok"}
```

## WebSocket路由

### 连接认证

**连接时认证**
```javascript
socket = io("http://localhost:9000", {
  auth: { api_key: "your_api_key" }
});
```

**连接后认证**
```javascript
socket.emit("auth", { backend_id: "backend-identifier" });
// 响应: { success: true, message: "Authentication successful" }
```

### 终端管理路由

#### terminal/start - 启动终端

**请求**
```javascript
socket.emit("terminal/start", {
  user_uuid: "user-uuid",
  item_uuid: "item-uuid",
  working_directory: "/path/to/workdir",  // 可选
  command: "npm start"                    // 可选
});
```

**响应**
```javascript
{
  success: true,
  item_uuid: "item-uuid",
  token: "generated-token",
  message: "启动成功"
}
```

**错误响应**
```javascript
{
  success: false,
  error: "Missing user_uuid or item_uuid"
}
```

#### terminal/stop - 停止终端

**请求**
```javascript
socket.emit("terminal/stop", {
  item_uuid: "item-uuid"
});
```

**响应**
```javascript
{
  success: true,
  item_uuid: "item-uuid",
  message: "终端已成功停止"
}
```

#### terminal/restart - 重启终端

**请求**
```javascript
socket.emit("terminal/restart", {
  item_uuid: "item-uuid",
  user_uuid: "user-uuid",
  working_directory: "/path/to/workdir",  // 可选
  command: "npm start"                    // 可选
});
```

**响应**
```javascript
{
  success: true,
  item_uuid: "item-uuid",
  token: "new-token",
  message: "终端已成功重启"
}
```

#### terminal/status - 获取终端状态

**请求**
```javascript
socket.emit("terminal/status", {
  item_uuid: "item-uuid"
});
```

**响应**
```javascript
{
  success: true,
  data: {
    item_uuid: "item-uuid",
    status: "running",
    pid: 12345,
    created_at: "2024-01-01T00:00:00"
  }
}
```

#### terminal/list - 获取终端列表

**请求**
```javascript
socket.emit("terminal/list", {});
```

**响应**
```javascript
{
  success: true,
  count: 2,
  data: [
    { item_uuid: "item-1", status: "running" },
    { item_uuid: "item-2", status: "running" }
  ]
}
```

### 连接管理路由

#### connections/get - 获取单个Item连接表

**请求**
```javascript
socket.emit("connections/get", {
  item_uuid: "item-uuid"
});
```

**响应**
```javascript
{
  success: true,
  item_uuid: "item-uuid",
  connections: {
    "sid-1": { user_uuid: "user-1", ip: "192.168.1.1" },
    "sid-2": { user_uuid: "backend", ip: "127.0.0.1" }
  }
}
```

#### connections/get_all - 获取所有Item连接表

**请求**
```javascript
socket.emit("connections/get_all", {});
```

**响应**
```javascript
{
  success: true,
  connections: {
    "item-uuid-1": {
      "sid-1": { user_uuid: "user-1", ip: "192.168.1.1" }
    },
    "item-uuid-2": {
      "sid-2": { user_uuid: "user-2", ip: "192.168.1.2" }
    }
  }
}
```

#### connections/disconnect - 断开用户连接

**请求**
```javascript
socket.emit("connections/disconnect", {
  item_uuid: "item-uuid",
  user_uuid: "user-uuid"  // 或 ip_address: "192.168.1.1"
});
```

**响应**
```javascript
{
  success: true,
  item_uuid: "item-uuid",
  message: "连接已断开",
  connections: { /* 更新后的连接表 */ }
}
```

### 用户终端连接路由

#### terminal/connect - 用户连接终端

**请求**
```javascript
socket.emit("terminal/connect", {
  item_uuid: "item-uuid",
  token: "access-token",
  user_uuid: "user-uuid"
});
```

**响应**
```javascript
// 成功
socket.on("terminal_connected", { item_uuid: "item-uuid" });

// 失败
socket.on("auth_error", { message: "Invalid token" });
```

#### terminal/write - 向终端写入命令

**请求**
```javascript
socket.emit("terminal/write", {
  command: "echo hello"
});
```

### 服务端推送事件

#### connection_update - 连接池更新通知

当有新的用户连接或断开时，Daemon会向所有Backend推送更新：

```javascript
socket.on("connection_update", {
  type: "item_update",  // 或 "full_sync"
  item_uuid: "item-uuid",
  item_connections: {
    "sid-1": { user_uuid: "user-1", ip: "192.168.1.1" }
  }
});
```

#### stream - 终端输出流

```javascript
socket.on("stream", {
  stdout: "terminal output..."
});
```

## 工作流程

### 1. Backend连接Daemon流程

```
Backend                          Daemon
  |                                |
  |-- connect(auth: api_key) ---->|
  |                                |
  |<----- connect success ---------|
  |                                |
  |------ auth(backend_id) ------>|
  |                                |
  |<----- auth success ------------|
  |                                |
  |<-- connection_update(full_sync) --|  # 自动同步所有连接表
  |                                |
```

### 2. 启动终端流程

```
Backend                          Daemon
  |                                |
  |-- terminal/start(item_uuid) ->|
  |                                |
  |                  创建终端进程   |
  |                  生成Token      |
  |                  更新Token表    |
  |                                |
  |<-- terminal/start(success) ----|
  |    {token, message}            |
```

### 3. 用户连接终端流程

```
User                             Daemon
  |                                |
  |-- terminal/connect(token) ---->|
  |                                |
  |                  验证Token      |
  |                  更新连接表      |
  |                                |
  |<-- terminal_connected ---------|
  |                                |
  |                --通知Backend-->|
  |                connection_update|
```

### 4. 终端输出广播流程

```
Terminal Process                  Daemon                    User/Backend
  |                                |                           |
  |---- stdout ------------------->|                           |
  |                                |                           |
  |                  broadcast_to_terminal("stream")          |
  |                                |                           |
  |                                |-- stream(stdout) -------->|
```

## 环境变量配置

| 变量名 | 描述 | 默认值 |
|--------|------|--------|
| PORT | Daemon服务端口 | 9000 |
| HOST | Daemon服务主机 | 0.0.0.0 |
| API_KEY | API访问密钥 | 无（必须设置） |
| WORKDIR | 终端工作目录 | ./src/workdir |
| LOG_DIR | 日志目录 | ./log |
| DATA_DIR | 数据目录 | ./src/data |
| TERMINAL_SHELL | 终端Shell | cmd.exe (Windows) / bash (Linux) |
| TERMINAL_ENCODING | 终端编码 | utf-8 |
| TERMINAL_BUFFER_SIZE | 终端缓冲区大小 | 8192 |

## 启动方式

### 使用Poetry

```bash
cd daemon
poetry install
poetry run python src/main.py
```

### 使用Docker

```bash
docker build -t termman-daemon .
docker run -p 9000:9000 -e API_KEY=your_secret_key termman-daemon
```

## 核心类说明

### SocketService

```python
class SocketService:
    """Socket.IO连接池管理"""
    
    # 连接表
    connections: Dict[str, Dict[str, Dict[str, str]]]  # Item-连接映射表
    backend_connections: Dict[str, Dict[str, str]]      # Backend连接表
    item_tokens: Dict[str, str]                         # Item-Token映射表
    
    # 核心方法
    async def handle_disconnect(sid: str)              # 处理断开连接
    async def broadcast_to_terminal(item_uuid, event, data)  # 广播到终端
    async def notify_connection_update(item_uuid)      # 通知Backend连接更新
    async def close_terminal_connections(item_uuid)    # 关闭终端所有连接
    def get_item_connections(item_uuid)                # 获取终端连接
    def get_all_connections()                          # 获取所有连接
```

### TerminalManager

```python
class TerminalManager:
    """终端进程管理"""
    
    def create_terminal(user_uuid, token, workdir, command, item_uuid)  # 创建终端
    def get_terminal(item_uuid) -> TerminalProcess                       # 获取终端
    def start_terminal(item_uuid) -> bool                                # 启动终端
    def stop_terminal(item_uuid) -> bool                                 # 停止终端
    def get_all_terminals() -> list                                      # 获取所有终端
```

### TerminalProcess

```python
class TerminalProcess:
    """终端进程实例"""
    
    def start() -> bool              # 启动进程
    def write(data: str) -> bool     # 写入数据
    def stop() -> bool               # 停止进程
    def get_status() -> dict         # 获取状态
```

## 日志说明

- **应用日志**: `./log/daemon.log`
- **终端日志**: `./log/{user_uuid}/{item_uuid}.log`
- **日志级别**: INFO、WARNING、ERROR、CRITICAL
- **日志格式**: `时间戳 - 日志名 - 级别 - 消息`

## 安全说明

1. **API Key认证**: 所有WebSocket连接必须提供有效的API Key
2. **Token验证**: 用户连接终端时需要验证Token
3. **Backend保护**: backend连接不能被disconnect接口断开
4. **CORS配置**: 默认允许所有来源（生产环境应限制）
