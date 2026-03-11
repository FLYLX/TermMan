# TermMan Backend Services

TermMan后端服务模块，实现了与终端管理相关的核心业务逻辑。

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
    def get_socket(item_uuid: str) -> Optional[ItemSocket]:
        """获取指定Item的Socket连接"""
    
    def create_socket(item_uuid: str, token: str, daemon_url: str) -> ItemSocket:
        """创建新的Item Socket连接"""
    
    def get_or_create_socket(item_uuid: str, token: str, daemon_url: str) -> ItemSocket:
        """获取或创建Item Socket连接"""
    
    def remove_socket(item_uuid: str):
        """移除并关闭Item Socket连接"""
    
    def add_token(item_uuid: str, token: str, expire_minutes: int = 1440) -> TokenInfo:
        """添加Token信息"""
    
    def get_token(item_uuid: str) -> Optional[TokenInfo]:
        """获取Token信息"""
    
    def validate_token(item_uuid: str, token: str) -> bool:
        """验证Token有效性"""
```

#### ItemSocket
```python
class ItemSocket:
    def connect() -> bool:
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
```

### connection_handler 模块

```python
class ConnectionHandler:
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
    def start_terminal(item_uuid: str, user_uuid: str, daemon_config: DaemonConfig) -> Dict[str, Any]:
        """启动终端"""
    
    def stop_terminal(daemon_id: str, item_uuid: str) -> Dict[str, Any]:
        """停止终端"""
    
    def get_terminal_status(daemon_id: str, item_uuid: str) -> Dict[str, Any]:
        """查询终端状态"""
    
    def connect_terminal(item_uuid: str, token: str, daemon_url: str) -> Optional[Dict[str, Any]]:
        """连接到终端"""
    
    def write_to_terminal(item_uuid: str, command: str) -> bool:
        """向终端写入命令"""
    
    def get_terminal_log(user_uuid: str, item_uuid: str) -> Optional[str]:
        """获取终端日志"""
    
    def delete_terminal_log(user_uuid: str, item_uuid: str) -> bool:
        """删除终端日志"""
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
from app.services import AuthService

# 创建Daemon配置
config = DaemonConfig(
    daemon_id="daemon-123",
    ip="127.0.0.1",
    port=24444,
    api_key="termman_daemon_secret_key_2024"
)

# 获取或创建Daemon连接
connection_manager = ConnectionManager()
connection = connection_manager.get_or_create_connection(config)

# 启动终端
auth_service = AuthService()
terminal_service = TerminalService(connection_manager, SocketManager(), ConnectionHandler())
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
        daemon_url=result["daemon_url"]
    )
```
