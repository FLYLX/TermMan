# TermMan Backend Services

TermMan后端服务模块，实现了终端管理的核心业务逻辑，包括Daemon连接池管理、Item Socket池管理、终端操作和日志记录等功能。

## 目录结构

```
services/
├── connection_pool/             # Daemon连接池管理
│   ├── __init__.py
│   ├── connection_manager.py    # 连接管理器
│   ├── daemon_connection.py     # Daemon连接类
│   └── connection_models.py     # 连接数据模型
├── socket_pool/                 # Item Socket池管理
│   ├── __init__.py
│   ├── socket_manager.py        # Socket管理器
│   ├── item_socket.py           # Item Socket类
│   └── socket_models.py         # Socket数据模型
├── protocol/                    # 协议定义
│   ├── __init__.py
│   ├── events.py                # 事件枚举
│   └── codec.py                 # 数据编解码
├── __init__.py
├── connection_handler.py        # 统一连接处理器
├── daemon_initializer.py        # Daemon连接初始化
├── log_manager.py               # 日志管理
└── terminal_service.py          # 终端核心业务逻辑
```

---

## 核心连接表结构

系统维护三张核心内存表来管理连接关系：

### 1. Daemon连接池表

**管理者**: `ConnectionManager`

**数据结构**:
```python
connections: Dict[str, DaemonConnection]
# Key: daemon_id = "{ip}:{port}:{api_key}"
# Value: DaemonConnection 对象
```

**说明**:
- 有连接的daemon放进去，没有连接的就拿出来
- 每个daemon_id是唯一的，由 `ip:port:api_key` 组合生成

**示例**:
```
Daemon连接池表 [daemon ip:port:apikey]
--------------------------------------------------------------------------------
Daemon ID                                         | Status
--------------------------------------------------------------------------------
192.168.1.100:9000:abc123...                      | connected
192.168.1.101:9000:xyz789...                      | connected
```

---

### 2. Item-Token映射表

**管理者**: `SocketManager`

**数据结构**:
```python
item_tokens: dict[str, dict[str, str]]
# Key: daemon_id
# Value: {item_uuid: token}
```

**说明**:
- 记录每个终端实例的访问令牌
- 按daemon_id分组存储，支持多个daemon
- 用于验证用户对终端的访问权限

**示例**:
```
Item-Token映射表 [daemon_id -> {item_uuid: token}]
----------------------------------------------------------------------------------------------------
Daemon ID                               | Item UUID                              | Token
----------------------------------------------------------------------------------------------------
192.168.1.100:9000:abc123...            | 550e8400-e29b-41d4-a716-446655440000   | tk_abc123xyz789
192.168.1.100:9000:abc123...            | 660e8400-e29b-41d4-a716-446655440001   | tk_def456uvw012
192.168.1.101:9000:xyz789...            | 770e8400-e29b-41d4-a716-446655440002   | tk_ghi789rst345
```

---

### 3. Item-连接映射表

**管理者**: `SocketManager`

**数据结构**:
```python
connections: dict[str, dict[str, dict[str, str]]]
# Key: item_uuid
# Value: {sid -> {user_uuid, ip}}
```

**说明**:
- 记录每个终端实例的所有连接用户
- `sid`: 每个连接的唯一标识符
- `user_uuid`: 用户UUID
- `ip`: 用户IP地址
- 广播是对所有 `{sid: user_uuid, ip_address}` 发送
- 单播根据 `ip_address` 来查找对应的socket连接

**示例**:
```
Item-连接映射表 [item_uuid -> {sid -> {user_uuid, ip}}]
----------------------------------------------------------------------------------------------------
Item UUID                              | SID                                   | User UUID                             | IP
----------------------------------------------------------------------------------------------------
550e8400-e29b-41d4-a716-446655440000   | conn_001                              | user_123                              | 192.168.1.50
550e8400-e29b-41d4-a716-446655440000   | conn_002                              | user_456                              | 192.168.1.51
```

---

## 核心类与方法

### ConnectionManager

**文件**: [connection_manager.py](connection_pool/connection_manager.py)

**职责**: 管理Daemon连接池，只维护一张表

```python
class ConnectionManager:
    connections: Dict[str, DaemonConnection]  # daemon连接池表

    def get_connection(daemon_id: str) -> Optional[DaemonConnection]:
        """获取指定Daemon的连接"""

    def create_connection(config: DaemonConfig) -> DaemonConnection:
        """创建新的Daemon连接并建立WebSocket连接"""

    def get_or_create_connection(config: DaemonConfig) -> DaemonConnection:
        """获取或创建Daemon连接，自动重连断开的连接"""

    def remove_connection(daemon_id: str):
        """移除并关闭Daemon连接"""

    def get_all_connections() -> List[DaemonConnection]:
        """获取所有连接"""

    def get_connected_connections() -> List[DaemonConnection]:
        """获取所有已连接的连接"""

    def heartbeat_all():
        """向所有连接发送心跳检测"""

    def cleanup_disconnected():
        """清理断开的连接"""

    def get_connection_pool() -> Dict[str, Any]:
        """获取daemon连接池表，格式为 {daemon_id: {ip, port, status}}"""
```

---

### DaemonConnection

**文件**: [daemon_connection.py](connection_pool/daemon_connection.py)

**职责**: 单个Daemon节点的WebSocket连接封装，使用WebSocket进行所有通信

```python
class DaemonConnection:
    config: DaemonConfig           # Daemon配置
    status: ConnectionStatus       # 连接状态
    sio: socketio.Client           # Socket.IO客户端
    callbacks: Dict[str, Callable] # 事件回调
    pending_requests: Dict[str, asyncio.Future]  # 待处理的请求

    def connect() -> bool:
        """建立与Daemon的WebSocket连接"""

    def disconnect():
        """断开与Daemon的连接"""

    def is_connected() -> bool:
        """检查连接是否活跃"""

    def get_status() -> ConnectionStatus:
        """获取连接状态"""

    def on(event: str, callback: Callable):
        """注册事件回调"""

    def emit(event: str, data: Any) -> bool:
        """发送事件到Daemon"""

    # WebSocket异步方法
    async def terminal_start(user_uuid, item_uuid, working_directory, command) -> Dict:
        """启动终端"""

    async def terminal_stop(item_uuid) -> Dict:
        """停止终端"""

    async def terminal_restart(item_uuid, user_uuid, working_directory, command) -> Dict:
        """重启终端"""

    async def terminal_status(item_uuid) -> Dict:
        """查询终端状态"""

    async def terminal_list() -> Dict:
        """获取终端列表"""

    async def get_connections(item_uuid) -> Dict:
        """获取指定item的连接池"""

    async def get_all_connections() -> Dict:
        """获取所有连接池"""

    async def disconnect_connection(item_uuid, user_uuid, ip_address) -> Dict:
        """断开指定连接"""

    # 同步方法（HTTP风格接口）
    def terminal_start_http(user_uuid, item_uuid, working_directory, command) -> Dict:
        """启动终端 - 同步方法"""

    def terminal_stop_http(item_uuid) -> Dict:
        """停止终端 - 同步方法"""

    def terminal_restart_http(item_uuid, user_uuid, working_directory, command) -> Dict:
        """重启终端 - 同步方法"""

    def terminal_status_http(item_uuid) -> Dict:
        """查询终端状态 - 同步方法"""

    def terminal_list_http() -> Dict:
        """获取终端列表 - 同步方法"""

    def get_connections_http(item_uuid) -> Dict:
        """获取指定item的连接池 - 同步方法"""

    def get_all_connections_http() -> Dict:
        """获取所有连接池 - 同步方法"""

    def disconnect_connection_http(item_uuid, user_uuid, ip_address) -> Dict:
        """断开指定连接 - 同步方法"""
```

---

### SocketManager

**文件**: [socket_manager.py](socket_pool/socket_manager.py)

**职责**: Item Socket池管理，维护两张表

```python
class SocketManager:
    sockets: dict[tuple, ItemSocket]           # (user_uuid, item_uuid) -> ItemSocket
    item_tokens: dict[str, dict[str, str]]     # daemon_id -> {item_uuid: token}
    connections: dict[str, dict[str, dict]]    # item_uuid -> {sid -> {user_uuid, ip}}
    lock: threading.RLock                      # 线程锁

    # Socket连接管理
    def get_socket(item_uuid: str, user_uuid: str) -> ItemSocket | None:
        """获取指定用户和Item的Socket连接"""

    def get_sockets_by_item(item_uuid: str) -> list[ItemSocket]:
        """获取指定Item的所有Socket连接"""

    def get_user_sockets(user_uuid: str) -> list[ItemSocket]:
        """获取指定用户的所有Socket连接"""

    def create_socket(item_uuid, token, daemon_url, user_uuid, api_key, ip_address, sid) -> ItemSocket:
        """创建新的Item Socket连接"""

    def get_or_create_socket(...) -> ItemSocket:
        """获取或创建Item Socket连接"""

    def remove_socket(item_uuid: str, user_uuid: str):
        """移除并关闭Item Socket连接"""

    def remove_all_sockets_by_item(item_uuid: str):
        """移除并关闭指定Item的所有Socket连接"""

    # Token管理
    def add_token(daemon_id: str, item_uuid: str, token: str) -> dict[str, str]:
        """添加Token信息"""

    def get_token(daemon_id: str, item_uuid: str) -> str | None:
        """获取Token信息"""

    def get_token_by_item(item_uuid: str) -> tuple[str | None, str | None]:
        """根据item_uuid获取daemon_id和token"""

    def remove_token(daemon_id: str, item_uuid: str) -> bool:
        """移除Token"""

    def validate_token(daemon_id: str, item_uuid: str, token: str) -> bool:
        """验证Token有效性"""

    # 连接表操作
    def get_connection_tables() -> dict[str, Any]:
        """获取所有连接表"""

    def get_connections_by_ip(item_uuid: str, ip_address: str) -> list[dict]:
        """根据IP地址获取连接信息（用于单播）"""

    def get_all_connections_for_broadcast(item_uuid: str) -> list[dict]:
        """获取项目的所有连接信息（用于广播）"""

    def update_connections_from_daemon(item_uuid: str, connections: dict) -> bool:
        """从daemon返回的连接池更新本地连接表"""

    def import_socket_connections(item_uuid, connections, daemon_url, api_key, daemon_id) -> bool:
        """从daemon导入socket连接表"""

    # 回调注册
    def register_stream_callback(item_uuid: str, user_uuid: str, callback: Callable) -> bool:
        """注册终端输出回调"""
```

---

### ItemSocket

**文件**: [item_socket.py](socket_pool/item_socket.py)

**职责**: 代表单个终端的Socket连接

```python
class ItemSocket:
    item_uuid: str              # 终端UUID
    token: str                  # 访问令牌
    daemon_url: str             # Daemon URL
    user_uuid: str              # 用户UUID（每个socket连接只对应一个用户）
    status: TerminalStatus      # 终端状态
    sio: socketio.Client        # Socket.IO客户端
    callbacks: dict             # 事件回调

    def connect(api_key: str) -> bool:
        """建立与终端Socket服务器的连接"""

    def disconnect():
        """断开与终端Socket服务器的连接"""

    def is_connected() -> bool:
        """检查连接是否活跃"""

    def get_status() -> TerminalStatus:
        """获取当前状态"""

    def emit(event: str, data: Any) -> bool:
        """发送事件到终端Socket服务器"""

    def write(command: str) -> bool:
        """向终端写入命令"""

    def on(event: str, callback: Callable):
        """注册事件回调"""
```

---

### TerminalService

**文件**: [terminal_service.py](terminal_service.py)

**职责**: 终端核心业务逻辑

```python
class TerminalService:
    connection_manager: ConnectionManager
    socket_manager: SocketManager
    connection_handler: ConnectionHandler
    log_manager: LogManager
    terminal_users: dict  # item_uuid -> [user_uuid, ...]

    def start_terminal(item_uuid: str, user_uuid: str, daemon_config: DaemonConfig) -> dict[str, Any]:
        """
        启动终端
        流程：
        1. 确保与daemon的连接
        2. 发送start请求到daemon
        3. 获取daemon返回的token和连接池
        4. 更新后端的连接池表
        5. 创建backend socket连接
        """

    def stop_terminal(daemon_id: str, item_uuid: str) -> dict[str, Any]:
        """
        停止终端
        流程：
        1. 发送stop请求到daemon
        2. 获取daemon返回的空连接池
        3. 更新后端的连接池表（清空）
        4. 移除token
        """

    def get_terminal_status(daemon_id: str, item_uuid: str) -> dict[str, Any]:
        """查询终端状态"""

    def connect_terminal(item_uuid, token, daemon_url, user_uuid, api_key, daemon_id) -> dict | None:
        """连接到终端"""

    def write_to_terminal(item_uuid: str, command: str) -> bool:
        """向终端写入命令"""

    def disconnect_connection(daemon_id: str, item_uuid: str, ip_address: str) -> dict[str, Any]:
        """断开特定连接"""

    def get_item_connections(daemon_id: str, item_uuid: str) -> dict[str, Any]:
        """获取item的连接池"""

    # 日志相关
    def register_stream_callback(item_uuid: str, user_uuid: str, callback: Callable) -> bool:
        """注册终端输出回调（自动记录日志）"""

    def get_terminal_log(user_uuid: str, item_uuid: str) -> str | None:
        """获取终端日志"""

    def delete_terminal_log(user_uuid: str, item_uuid: str) -> bool:
        """删除终端日志"""

    def list_user_terminals(user_uuid: str) -> dict[str, Any]:
        """列出用户的所有终端"""
```

---

### ConnectionHandler

**文件**: [connection_handler.py](connection_handler.py)

**职责**: 统一连接处理器，处理命令转发

```python
class ConnectionHandler:
    connection_manager: ConnectionManager
    socket_manager: SocketManager
    command_handlers: dict[str, Callable]

    def handle_command(daemon_id: str, command: str, data: dict) -> dict[str, Any]:
        """处理命令"""

    def handle_terminal_start(daemon_id: str, data: dict) -> dict[str, Any]:
        """处理终端启动命令"""

    def handle_terminal_stop(daemon_id: str, data: dict) -> dict[str, Any]:
        """处理终端停止命令"""

    def handle_terminal_status(daemon_id: str, data: dict) -> dict[str, Any]:
        """处理终端状态查询命令"""

    def forward_to_socket(item_uuid: str, event: str, data: Any) -> bool:
        """转发事件到Item Socket"""

    def broadcast_to_daemons(event: str, data: Any) -> int:
        """广播事件到所有Daemon"""

    def broadcast_to_sockets(event: str, data: Any) -> int:
        """广播事件到所有Item Socket"""
```

---

### LogManager

**文件**: [log_manager.py](log_manager.py)

**职责**: 日志管理，保存终端输出到文件

```python
class LogManager:
    base_dir: str           # 日志基础目录
    max_log_size: int       # 最大日志文件大小（默认3MB）

    def get_log_path(user_uuid: str, item_uuid: str) -> str:
        """获取日志文件路径，格式: {base_dir}/{user_uuid}/{item_uuid}.log"""

    def write_to_log(user_uuid: str, item_uuid: str, content: str) -> bool:
        """写入日志到文件，超过最大大小时自动清空"""

    def get_log_content(user_uuid: str, item_uuid: str) -> str | None:
        """获取日志文件内容"""

    def delete_log(user_uuid: str, item_uuid: str) -> bool:
        """删除日志文件"""

    def set_max_log_size(max_size: int):
        """设置最大日志文件大小"""
```

---

### daemon_initializer 模块

**文件**: [daemon_initializer.py](daemon_initializer.py)

**职责**: 在应用启动时初始化所有daemon连接

```python
connection_manager: ConnectionManager  # 全局连接管理器
socket_manager: SocketManager          # 全局Socket管理器

def handle_connection_update(data):
    """
    处理来自daemon的连接池更新
    - type: "full_sync" 或 "item_update"
    - connections: 连接池数据
    """

def initialize_daemon_connections():
    """
    初始化daemon连接的主要函数：
    1. 检索所有item
    2. 提取不重复的ip:port:api_key组合
    3. 为每个daemon创建WebSocket连接
    4. 将连接添加到连接池
    5. 设置连接更新回调
    """

def start_daemon_initialization():
    """启动daemon初始化"""
```

---

## 数据模型

### ConnectionStatus

**文件**: [connection_models.py](connection_pool/connection_models.py)

```python
class ConnectionStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    ERROR = "error"
```

### DaemonConfig

**文件**: [connection_models.py](connection_pool/connection_models.py)

```python
class DaemonConfig:
    ip: str           # Daemon IP地址
    port: int         # Daemon端口
    api_key: str      # API密钥
    daemon_id: str    # 唯一标识符，格式: "{ip}:{port}:{api_key}"
    base_url: str     # 基础URL，格式: "http://{ip}:{port}"
```

### TerminalStatus

**文件**: [socket_models.py](socket_pool/socket_models.py)

```python
class TerminalStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    STARTING = "starting"
    ERROR = "error"
```

---

## 协议事件

**文件**: [events.py](protocol/events.py)

```python
class ProtocolEvents(str, Enum):
    # 数据流事件
    STREAM = "stream"                    # 终端输出流
    WRITE = "terminal_write"             # 写入命令

    # 实例事件
    INSTANCE_STDOUT = "instance/stdout"  # 标准输出
    INSTANCE_STDERR = "instance/stderr"  # 标准错误
    INSTANCE_EXIT = "instance/exit"      # 实例退出

    # 终端控制事件
    TERMINAL_START = "terminal/start"    # 启动终端
    TERMINAL_STOP = "terminal/stop"      # 停止终端
    TERMINAL_STATUS = "terminal/status"  # 终端状态

    # 终端Socket事件
    TERMINAL_CONNECT = "terminal_connect"  # 终端连接

    # 管理事件
    HEARTBEAT = "heartbeat"              # 心跳
    HEARTBEAT_ACK = "heartbeat_ack"      # 心跳响应
    AUTH = "auth"                        # 认证
    AUTH_ACK = "auth_ack"                # 认证响应
```

---

## 通信流程

### Daemon WebSocket路由对接

Backend通过WebSocket与Daemon通信，主要路由如下：

| 路由 | 方法 | 说明 |
|------|------|------|
| `terminal/start` | emit | 启动终端 |
| `terminal/stop` | emit | 停止终端 |
| `terminal/restart` | emit | 重启终端 |
| `terminal/status` | emit | 查询终端状态 |
| `terminal/list` | emit | 获取终端列表 |
| `connections/get` | emit | 获取指定item连接池 |
| `connections/get_all` | emit | 获取所有连接池 |
| `connections/disconnect` | emit | 断开指定连接 |
| `connection_update` | on | 接收连接池更新通知 |
| `stream` | on | 接收终端输出流 |
| `auth` | emit | 认证请求 |

### 终端启动流程

```
用户 -> Backend API -> TerminalService.start_terminal()
                          |
                          v
                    ConnectionManager.get_or_create_connection()
                          |
                          v
                    DaemonConnection.terminal_start() [WebSocket]
                          |
                          v
                    Daemon -> 启动终端进程 -> 返回 {item_uuid, token, connections}
                          |
                          v
                    SocketManager.add_token()
                    SocketManager.update_connections_from_daemon()
                    SocketManager.create_socket()
```

### 终端停止流程

```
用户 -> Backend API -> TerminalService.stop_terminal()
                          |
                          v
                    DaemonConnection.terminal_stop() [WebSocket]
                          |
                          v
                    Daemon -> 停止终端进程 -> 返回 {success, connections: {}}
                          |
                          v
                    SocketManager.update_connections_from_daemon() [清空]
                    SocketManager.remove_all_tokens_by_item()
                    SocketManager.remove_all_sockets_by_item()
```

### 连接池同步流程

```
Daemon -> connection_update事件 -> handle_connection_update()
                                        |
                                        v
                                   SocketManager.connections 更新
                                        |
                                        v
                                   _print_connection_tables() [日志输出]
```

---

## 使用示例

```python
from app.services import TerminalService, ConnectionManager, SocketManager, ConnectionHandler
from app.services.connection_pool import DaemonConfig

# 创建Daemon配置
config = DaemonConfig(
    ip="192.168.1.100",
    port=9000,
    api_key="your_api_key"
)

# 初始化服务
connection_manager = ConnectionManager()
socket_manager = SocketManager()
connection_handler = ConnectionHandler(connection_manager, socket_manager)
terminal_service = TerminalService(connection_manager, socket_manager, connection_handler)

# 获取或创建Daemon连接
connection = connection_manager.get_or_create_connection(config)

# 启动终端
result = terminal_service.start_terminal(
    item_uuid="item-123",
    user_uuid="user-456",
    daemon_config=config
)

# 连接到终端
if result["success"]:
    terminal_service.connect_terminal(
        item_uuid=result["item_uuid"],
        token=result["token"],
        daemon_url=result["daemon_url"],
        user_uuid="user-456",
        api_key=config.api_key,
        daemon_id=result["daemon_id"]
    )

# 注册终端输出回调
def on_output(data):
    print(f"终端输出: {data.get('stdout', '')}")

terminal_service.register_stream_callback(
    item_uuid=result["item_uuid"],
    user_uuid="user-456",
    callback=on_output
)

# 执行命令
terminal_service.write_to_terminal(result["item_uuid"], "ls -la\n")

# 停止终端
terminal_service.stop_terminal(config.daemon_id, result["item_uuid"])
```

---

## 与Daemon的接口对应关系

### Backend -> Daemon 请求

| Backend方法 | Daemon路由 | 请求参数 | 响应格式 |
|-------------|-----------|----------|----------|
| `terminal_start_http` | `terminal/start` | `{user_uuid, item_uuid, working_directory?, command?}` | `{success, item_uuid, token, message}` |
| `terminal_stop_http` | `terminal/stop` | `{item_uuid}` | `{success, item_uuid, message}` |
| `terminal_restart_http` | `terminal/restart` | `{item_uuid, user_uuid?, working_directory?, command?}` | `{success, item_uuid, token, message}` |
| `terminal_status_http` | `terminal/status` | `{item_uuid}` | `{success, data: {item_uuid, status, pid, created_at}}` |
| `terminal_list_http` | `terminal/list` | `{}` | `{success, count, data}` |
| `get_connections_http` | `connections/get` | `{item_uuid}` | `{success, item_uuid, connections: {sid: {user_uuid, ip}}}` |
| `get_all_connections_http` | `connections/get_all` | `{}` | `{success, connections}` |
| `disconnect_connection_http` | `connections/disconnect` | `{item_uuid, user_uuid?或ip_address?}` | `{success, item_uuid, message, connections}` |

### Daemon -> Backend 推送

| 事件 | 触发时机 | 数据格式 |
|------|----------|----------|
| `connection_update` | 连接池变化时 | `{type: "item_update"或"full_sync", item_uuid?, item_connections?, connections?}` |
| `stream` | 终端输出时 | `{stdout}` |
| `terminal_connected` | 用户连接终端成功时 | `{item_uuid}` |
| `auth_error` | 认证失败时 | `{message}` |
