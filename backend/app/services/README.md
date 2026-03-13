# TermMan Backend Services

TermMan后端服务模块，实现了终端管理的核心业务逻辑，包括连接池管理、终端连接、多用户共享和日志记录等功能。

## 核心业务逻辑

### 1. 连接管理架构

TermMan采用**双层连接池架构**来管理终端连接：

#### 第一层：Daemon连接池（ConnectionPool）
- **功能**：管理与Daemon服务的HTTP连接
- **核心组件**：`ConnectionManager`类
- **工作流程**：
  1. 根据Daemon配置创建或获取连接
  2. 维护活跃连接池，定期清理断开的连接
  3. 提供HTTP接口与Daemon通信（启动终端、停止终端等）

#### 第二层：Item Socket池（SocketPool）
- **功能**：管理用户与终端的实时Socket连接
- **核心组件**：`SocketManager`类
- **工作流程**：
  1. 为每个用户-终端组合创建Socket连接
  2. 维护连接状态和用户权限
  3. 处理实时终端数据传输

### 2. 连接逻辑表

系统维护三种核心逻辑表来管理连接关系：

| 逻辑表名 | 功能 | 数据结构 |
|---------|------|---------|
| **user_item_map** | 记录用户可访问的终端列表 | `{user_uuid: [item_uuid1, item_uuid2, ...]}` |
| **item_user_conn_map** | 记录终端的所有连接用户 | `{item_uuid: {user_uuid1: socket1, user_uuid2: socket2, ...}}` |
| **item_token_map** | 记录终端的访问令牌 | `{item_uuid: token}` |

### 3. 终端连接流程

#### 终端启动流程
1. 用户请求启动终端
2. `TerminalService`通过`ConnectionManager`获取Daemon连接
3. 生成终端访问令牌
4. 通过HTTP接口向Daemon发送终端启动请求
5. Daemon返回终端UUID和工作目录
6. 记录终端信息到逻辑表

#### 用户连接终端流程
1. 用户请求连接终端
2. `TerminalService`验证用户权限
3. 通过`SocketManager`创建或获取Socket连接
4. 注册终端输出回调（自动启用日志记录）
5. 连接成功后加入到逻辑表中
6. 用户可以实时接收终端输出和发送命令

### 4. 日志记录机制

日志记录采用**用户-终端隔离**机制：

1. **自动关联**：用户连接终端时自动注册日志回调
2. **实时记录**：终端输出通过Socket.IO的`stream`事件实时捕获
3. **结构化存储**：日志文件按`user_uuid/item_uuid.log`结构存储
4. **大小限制**：日志文件超过3MB时自动清空
5. **访问控制**：用户只能访问自己的终端日志

### 5. 多用户共享终端

支持多用户同时连接和共享同一个终端：

1. 第一个用户启动终端并获得访问权限
2. 其他用户通过权限验证后可以连接到同一终端
3. 所有用户实时同步接收终端输出
4. 任何用户都可以向终端发送命令
5. 每个用户都有独立的日志文件记录

### 6. 命令执行流程

1. 用户通过`TerminalService`发送命令
2. 系统查找该终端的活跃Socket连接
3. 通过Socket.IO的`write`事件发送命令到终端
4. 终端执行命令并返回输出
5. 输出通过`stream`事件广播给所有连接用户
6. 自动记录到每个用户的日志文件中


## 模块结构

```
services/
├── __init__.py              # 模块导出
├── connection_pool/         # Daemon连接池管理
│   ├── __init__.py
│   ├── connection_manager.py # 连接管理器
│   ├── daemon_connection.py  # Daemon连接类
│   └── connection_models.py  # 连接数据模型
├── socket_pool/             # Item Socket池管理
│   ├── __init__.py
│   ├── socket_manager.py    # Socket管理器
│   ├── item_socket.py       # Item Socket类
│   └── socket_models.py     # Socket数据模型
├── connection_handler.py    # 统一连接处理器
├── terminal_service.py      # 终端核心业务逻辑
├── auth_service.py          # 鉴权服务
└── protocol/                # MCSM协议适配层
    ├── __init__.py
    ├── events.py            # 事件枚举
    └── codec.py             # 数据编解码
```

## 模块说明

### connection_pool 模块

#### ConnectionManager
```python
class ConnectionManager:
    def get_connection(daemon_id: str) -> Optional[DaemonConnection]:
        """获取指定Daemon的连接"""
    
    def create_connection(config: DaemonConfig) -> DaemonConnection:
        """创建新的Daemon连接"""
    
    def get_or_create_connection(config: DaemonConfig) -> DaemonConnection:
        """获取或创建Daemon连接"""
    
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
```

#### DaemonConnection
```python
class DaemonConnection:
    def connect() -> bool:
        """建立与Daemon的连接"""
    
    def disconnect():
        """断开与Daemon的连接"""
    
    def emit(event: str, data: Any) -> bool:
        """发送事件到Daemon"""
    
    def on(event: str, callback: Callable):
        """注册事件回调"""
    
    def is_connected() -> bool:
        """检查连接是否活跃"""
```

### socket_pool 模块

#### SocketManager
```python
class SocketManager:
    def get_socket(item_uuid: str, user_uuid: str) -> Optional[ItemSocket]:
        """获取指定用户和Item的Socket连接"""
    
    def get_sockets_by_item(item_uuid: str) -> List[ItemSocket]:
        """获取指定Item的所有Socket连接"""
    
    def get_user_sockets(user_uuid: str) -> List[ItemSocket]:
        """获取指定用户的所有Socket连接"""
    
    def create_socket(item_uuid: str, token: str, daemon_url: str, user_uuid: str) -> ItemSocket:
        """创建新的Item Socket连接"""
    
    def get_or_create_socket(item_uuid: str, token: str, daemon_url: str, user_uuid: str) -> ItemSocket:
        """获取或创建Item Socket连接"""
    
    def remove_socket(item_uuid: str, user_uuid: str):
        """移除并关闭Item Socket连接"""
    
    def remove_all_sockets_by_item(item_uuid: str):
        """移除并关闭指定Item的所有Socket连接"""
    
    def add_token(item_uuid: str, token: str, expire_minutes: int = 1440) -> TokenInfo:
        """添加Token信息"""
    
    def get_token(item_uuid: str) -> Optional[TokenInfo]:
        """获取Token信息"""
    
    def validate_token(item_uuid: str, token: str) -> bool:
        """验证Token有效性"""
    
    def register_stream_callback(item_uuid: str, user_uuid: str, callback: Callable) -> bool:
        """注册终端输出回调"""
```

#### ItemSocket
```python
class ItemSocket:
    def __init__(self, item_uuid: str, token: str, daemon_url: str, user_uuid: str):
        """初始化ItemSocket连接"""
        
    def connect(api_key: str) -> bool:
        """建立与终端Socket服务器的连接"""
    
    def disconnect():
        """断开与终端Socket服务器的连接"""
    
    def emit(event: str, data: Any) -> bool:
        """发送事件到终端Socket服务器"""
    
    def write(command: str) -> bool:
        """向终端写入命令"""
    
    def on(event: str, callback: Callable):
        """注册事件回调"""
    
    def is_connected() -> bool:
        """检查连接是否活跃"""
    
    def get_status() -> TerminalStatus:
        """获取当前状态"""
```

### connection_handler 模块

```python
class ConnectionHandler:
    def __init__(self, connection_manager: ConnectionManager, socket_manager: SocketManager):
        """初始化ConnectionHandler"""
        
    def handle_command(daemon_id: str, command: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理命令"""
    
    def forward_to_socket(item_uuid: str, event: str, data: Any) -> bool:
        """转发事件到Item Socket"""
    
    def broadcast_to_daemons(event: str, data: Any) -> int:
        """广播事件到所有Daemon"""
    
    def broadcast_to_sockets(event: str, data: Any) -> int:
        """广播事件到所有Item Socket"""
```

### terminal_service 模块

```python
class TerminalService:
    def __init__(self, connection_manager: ConnectionManager, socket_manager: SocketManager, connection_handler: ConnectionHandler):
        """初始化TerminalService"""
        
    def start_terminal(item_uuid: str, user_uuid: str, daemon_config: DaemonConfig) -> Dict[str, Any]:
        """启动终端"""
    
    def stop_terminal(daemon_id: str, item_uuid: str) -> Dict[str, Any]:
        """停止终端"""
    
    def get_terminal_status(daemon_id: str, item_uuid: str) -> Dict[str, Any]:
        """查询终端状态"""
    
    def connect_terminal(item_uuid: str, token: str, daemon_url: str, user_uuid: str, api_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """连接到终端"""
    
    def write_to_terminal(item_uuid: str, command: str) -> bool:
        """向终端写入命令"""
    
    def register_stream_callback(item_uuid: str, user_uuid: str, callback: Callable) -> bool:
        """注册终端输出回调"""
    
    def get_terminal_log(user_uuid: str, item_uuid: str) -> Optional[str]:
        """获取终端日志"""
    
    def delete_terminal_log(user_uuid: str, item_uuid: str) -> bool:
        """删除终端日志"""
    
    def set_log_max_size(max_size: int) -> None:
        """设置日志文件最大大小"""
    
    def list_user_terminals(user_uuid: str) -> Dict[str, Any]:
        """列出用户的所有终端"""
```

### auth_service 模块

```python
class AuthService:
    def generate_api_key(daemon_id: str) -> str:
        """生成API Key"""
    
    def validate_api_key(api_key: str) -> Optional[str]:
        """验证API Key有效性"""
    
    def revoke_api_key(api_key: str) -> bool:
        """撤销API Key"""
    
    def generate_token(item_uuid: str, expire_minutes: int = 1440) -> str:
        """生成访问Token"""
    
    def validate_token(token: str) -> Optional[str]:
        """验证Token有效性"""
    
    def revoke_token(token: str) -> bool:
        """撤销Token"""
    
    def get_mission_passport(daemon_id: str, item_uuid: str) -> Dict[str, Any]:
        """获取任务通行证"""
```

### protocol 模块

#### ProtocolEvents
```python
class ProtocolEvents(str, Enum):
    STREAM = "stream"              # 数据流事件
    WRITE = "write"                # 写入事件
    INSTANCE_STDOUT = "instance/stdout"  # 实例标准输出
    INSTANCE_STDERR = "instance/stderr"  # 实例标准错误
    INSTANCE_EXIT = "instance/exit"      # 实例退出
    TERMINAL_START = "terminal/start"    # 终端启动
    TERMINAL_STOP = "terminal/stop"      # 终端停止
    TERMINAL_STATUS = "terminal/status"  # 终端状态
    TERMINAL_CONNECT = "terminal_connect"  # 终端连接
```

#### ProtocolCodec
```python
class ProtocolCodec:
    @staticmethod
    def encode(data: Any) -> str:
        """编码数据为JSON字符串"""
    
    @staticmethod
    def decode(data: str) -> Dict[str, Any]:
        """解码JSON字符串为数据"""
    
    @staticmethod
    def wrap_data(event: str, data: Any) -> Dict[str, Any]:
        """包装数据为MCSM协议格式"""
```

## 使用示例

```python
from app.services import TerminalService, ConnectionManager, DaemonConfig
from app.services import SocketManager, ConnectionHandler

# 创建Daemon配置
config = DaemonConfig(
    daemon_id="daemon-123",
    ip="127.0.0.1",
    port=24444,
    api_key="termman_daemon_secret_key_2024"
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
    item_uuid="item-456",
    user_uuid="user-789",
    daemon_config=config
)

# 连接到终端
if result["success"]:
    terminal_service.connect_terminal(
        item_uuid=result["item_uuid"], 
        token=result["token"],
        daemon_url=result["daemon_url"],
        user_uuid="user-789",
        api_key="termman_daemon_secret_key_2024"
    )

# 注册终端输出回调
def terminal_output_callback(data):
    print(f"终端输出: {data.get('stdout', '')}")

terminal_service.register_stream_callback(
    item_uuid=result["item_uuid"],
    user_uuid="user-789",
    callback=terminal_output_callback
)

# 执行命令
terminal_service.write_to_terminal(result["item_uuid"], "echo 'Hello, World!'")
```
