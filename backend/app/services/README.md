# TermMan Backend Services

TermMan 后端服务模块，实现了终端管理的核心业务逻辑。

## 真实架构

```
浏览器  <----直连 Socket.IO---->  Daemon
   ↑                               ↑
   │                               │
   └-------- HTTP API ------------ Backend
```

**重点：**
- 浏览器 ↔ Daemon = 直连 WebSocket（终端、日志、输出流）
- 浏览器 ↔ Backend = HTTP（登录、获取实例列表、权限）
- Backend ↔ Daemon = WebSocket（控制、状态同步）

## 目录结构

```
services/
├── connection_pool/             # Daemon连接池管理
│   ├── connection_manager.py    # 连接管理器（单例）
│   ├── daemon_connection.py     # Daemon连接类
│   └── connection_models.py     # 连接数据模型
├── socket_pool/                 # Item Socket池管理
│   ├── socket_manager.py        # Socket管理器（单例）
│   ├── item_socket.py           # Item Socket类
│   └── socket_models.py         # Socket数据模型
├── protocol/                    # 协议定义
│   ├── events.py                # 事件枚举
│   └── codec.py                 # 数据编解码
├── daemon_initializer.py        # Daemon连接初始化
└── terminal_service.py          # 终端核心业务逻辑
```

## 核心连接表结构

### 1. Daemon连接池表

**管理者**: `ConnectionManager`

```python
connections: Dict[str, DaemonConnection]
# Key: daemon_id = "{ip}:{port}:{api_key}"
# Value: DaemonConnection 对象
```

**说明**:
- 管理与所有Daemon的主控制连接
- 用于发送终端控制命令（start/stop/status）
- 接收Daemon推送的连接池更新

### 2. Item-Token映射表

**管理者**: `SocketManager`

```python
item_tokens: dict[str, dict[str, str]]
# Key: daemon_id
# Value: {item_uuid: token}
```

**说明**:
- 记录每个终端实例的访问令牌
- 用于Backend创建socket连接

### 3. Item-连接映射表

**管理者**: `SocketManager`

```python
connections: dict[str, dict[str, dict[str, str]]]
# Key: item_uuid
# Value: {sid -> {user_uuid, ip}}
```

**说明**:
- 记录每个终端实例的所有连接用户
- 从Daemon同步获取，用于状态展示

## 浏览器直连 Daemon 认证流程

### 1. 浏览器先登录 Backend（HTTP）

```
POST /api/v1/login
→ 获取用户 token
```

### 2. 浏览器请求打开终端

```
GET /api/v1/items/{id}/terminal-token
→ Backend 检查权限
→ Backend 签发临时 access_token（有效期 5 分钟）
```

返回：
```json
{
  "success": true,
  "access_token": "item_uuid:user_uuid:timestamp:expires_in:signature",
  "token_type": "Bearer",
  "expires_in": 300,
  "item_uuid": "xxx",
  "user_uuid": "xxx",
  "daemon_url": "http://daemon:9000"
}
```

### 3. 浏览器使用 access_token 直连 Daemon

```javascript
const socket = io(daemon_url, {
  auth: {
    access_token: access_token
  }
});

socket.emit("terminal/connect", {
  item_uuid: item_uuid,
  access_token: access_token
});
```

### 4. Daemon 验证 access_token

Daemon 直接验证 access_token（无需向 Backend 询问）：
- 解析 token 格式
- 验证时间戳是否过期
- 验证签名是否正确
- 验证 item_uuid 是否匹配

## 连接池同步流程

### 1. Backend 认证成功时

```
Backend --auth--> Daemon
Daemon --connection_update(full_sync)--> Backend
Backend 更新所有 item 的连接池表
```

### 2. 浏览器连接终端时

```
Browser --terminal/connect--> Daemon
Daemon 验证 access_token
Daemon 更新连接池表
Daemon --connection_update(item_update)--> Backend
Backend 更新对应 item 的连接池表
```

### 3. 连接断开时

```
Browser/Backend --disconnect--> Daemon
Daemon 更新连接池表
Daemon --connection_update(item_update)--> Backend
Backend 更新对应 item 的连接池表
```

### 4. Item 启动/停止时

```
Backend --terminal/start--> Daemon
Daemon 创建终端进程
Daemon 生成 token
Daemon --response(token)--> Backend
Backend 保存 token
Backend 创建 backend socket 连接
```

## 核心类

### ConnectionManager

管理Daemon连接池，只维护一张表。

```python
class ConnectionManager:
    connections: Dict[str, DaemonConnection]  # daemon连接池表

    def get_connection(daemon_id: str) -> Optional[DaemonConnection]
    def get_or_create_connection(config: DaemonConfig) -> DaemonConnection
    def remove_connection(daemon_id: str)
    def get_all_connections() -> List[DaemonConnection]
```

### DaemonConnection

单个Daemon节点的WebSocket连接封装。

```python
class DaemonConnection:
    config: DaemonConfig
    status: ConnectionStatus
    sio: socketio.Client

    # 终端控制方法
    async def terminal_start(user_uuid, item_uuid, working_directory, command) -> Dict
    async def terminal_stop(item_uuid) -> Dict
    async def terminal_restart(item_uuid, user_uuid, working_directory, command) -> Dict
    async def terminal_status(item_uuid) -> Dict

    # 连接管理方法
    async def get_connections(item_uuid) -> Dict
    async def get_all_connections() -> Dict
    async def disconnect_connection(item_uuid, user_uuid, ip_address) -> Dict
    
    # 事件回调
    def on(event: str, callback: Callable)
```

### SocketManager

Item Socket池管理，维护两张表。

```python
class SocketManager:
    sockets: dict[tuple, ItemSocket]           # (user_uuid, item_uuid) -> ItemSocket
    item_tokens: dict[str, dict[str, str]]     # daemon_id -> {item_uuid: token}
    connections: dict[str, dict[str, dict]]    # item_uuid -> {sid -> {user_uuid, ip}}

    # Socket连接管理
    def get_socket(item_uuid, user_uuid) -> ItemSocket | None
    def create_socket(item_uuid, token, daemon_url, user_uuid, api_key, ip_address) -> ItemSocket
    def remove_socket(item_uuid, user_uuid)

    # Token管理
    def add_token(daemon_id, item_uuid, token)
    def get_token(daemon_id, item_uuid) -> str | None
    def get_token_by_item(item_uuid) -> tuple[str | None, str | None]

    # 连接表操作
    def get_connection_tables() -> dict
    def update_connections_from_daemon(item_uuid, connections) -> bool
```

## API 端点

### Backend HTTP API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/items/{id}/terminal-token` | GET | 获取临时 access_token |
| `/items/{id}/start` | POST | 启动终端 |
| `/items/{id}/stop` | POST | 停止终端 |
| `/items/{id}/disconnect-user` | POST | 断开用户连接 |

## 协议事件

```python
class ProtocolEvents(str, Enum):
    # 数据流事件
    STREAM = "stream"                    # 终端输出流
    WRITE = "terminal/write"             # 写入命令

    # 终端控制事件
    TERMINAL_START = "terminal/start"    # 启动终端
    TERMINAL_STOP = "terminal/stop"      # 停止终端
    TERMINAL_STATUS = "terminal/status"  # 终端状态

    # 终端Socket事件
    TERMINAL_CONNECT = "terminal/connect"  # 终端连接
```

## 安全机制

1. **API Key 认证**: Backend ↔ Daemon 使用 api_key 认证
2. **临时 Token**: 浏览器获取的 access_token 有效期 5 分钟
3. **签名验证**: access_token 使用 HMAC-SHA256 签名
4. **权限检查**: Backend 签发 token 前检查用户权限
5. **Backend 保护**: backend 连接不能被 disconnect 接口断开

## 环境变量

### Backend

```
SECRET_KEY=your-secret-key-for-jwt-and-access-token
```

### Daemon

```
API_KEY=your-api-key-for-backend-auth
SECRET_KEY=your-secret-key-for-access-token-verification
```

**注意**: Backend 和 Daemon 必须使用相同的 SECRET_KEY 才能正确验证 access_token。

## 使用示例

### 启动终端

```python
from app.services import connection_manager, socket_manager

# 获取或创建Daemon连接
config = DaemonConfig(ip="192.168.1.100", port=9000, api_key="secret")
connection = connection_manager.get_or_create_connection(config)

# 启动终端
result = connection.terminal_start_http(
    user_uuid="user-123",
    item_uuid="item-456",
    working_directory="/home/user/project",
    command="npm start"
)

token = result.get("token")

# 保存token
socket_manager.add_token(connection.config.daemon_id, "item-456", token)
```

### 获取终端连接token

```python
# 在API路由中
@router.get("/{id}/terminal-token")
def get_terminal_token(session: SessionDep, current_user: CurrentUser, id: uuid.UUID):
    # 检查权限
    # 签发临时access_token
    # 返回给浏览器
```
