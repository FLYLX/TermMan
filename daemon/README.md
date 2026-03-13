# TermMan Daemon

TermMan Daemon是一个终端管理守护进程，负责管理和运行终端进程，并通过HTTP和Socket.IO与后端进行通信。

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
│   │   └── file_storage.py   # 文件存储
│   ├── service/              # 业务服务
│   │   ├── __init__.py
│   │   ├── terminal_manager.py # 终端进程管理
│   │   ├── socket_service.py   # Socket.IO服务
│   │   └── auth_service.py     # 鉴权服务
│   ├── api/                  # API接口
│   │   ├── __init__.py
│   │   ├── http_routes.py    # HTTP路由
│   │   └── socket_routes.py  # Socket.IO路由
│   ├── utils/                # 工具模块
│   │   ├── __init__.py
│   │   └── logger.py         # 日志工具
│   ├── data/                 # 数据目录
│   │   ├── __init__.py
│   │   ├── config.json       # 配置文件
│   │   ├── terminals/        # 终端配置
│   │   └── logs/             # 业务日志
│   ├── workdir/              # 终端工作目录
│   └── main.py               # 入口文件
└── log/                      # 应用日志目录
```

## 模块说明

### core 模块

#### Config
```python
class Config:
    def load_env():
        """加载环境变量"""
    
    def load_config_file():
        """加载配置文件"""
    
    def save_config_file():
        """保存配置到文件"""
    
    def get(key: str, default: Any = None) -> Any:
        """获取配置值"""
    
    def set(key: str, value: Any):
        """设置配置值"""
    
    def ensure_directories():
        """确保必要的目录存在"""
```

#### MemoryStore
```python
class MemoryStore:
    def set(key: str, value: Any, ttl_minutes: Optional[int] = None):
        """设置存储项"""
    
    def get(key: str) -> Optional[Any]:
        """获取存储项"""
    
    def delete(key: str) -> bool:
        """删除存储项"""
    
    def exists(key: str) -> bool:
        """检查键是否存在"""
    
    def cleanup_expired():
        """清理过期的存储项"""
```

#### FileStorage
```python
class FileStorage:
    def write_json(filename: str, data: Any, indent: int = 2):
        """写入JSON文件"""
    
    def read_json(filename: str) -> Optional[Dict[str, Any]]:
        """读取JSON文件"""
    
    def write_file(filename: str, content: str):
        """写入文件"""
    
    def append_file(filename: str, content: str):
        """追加写入文件"""
    
    def read_file(filename: str) -> Optional[str]:
        """读取文件"""
    
    def exists(filename: str) -> bool:
        """检查文件是否存在"""
```

### service 模块

#### TerminalManager
```python
class TerminalManager:
    def create_terminal(user_uuid: str, token: str) -> str:
        """创建新终端"""
    
    def get_terminal(item_uuid: str) -> Optional[TerminalProcess]:
        """获取终端"""
    
    def start_terminal(item_uuid: str) -> bool:
        """启动终端"""
    
    def stop_terminal(item_uuid: str) -> bool:
        """停止终端"""
    
    def write_to_terminal(item_uuid: str, data: str) -> bool:
        """向终端写入数据"""
    
    def get_terminal_status(item_uuid: str) -> Optional[Dict[str, Any]]:
        """获取终端状态"""
    
    def get_user_terminals(user_uuid: str) -> list:
        """获取用户的所有终端"""
```

#### TerminalProcess
```python
class TerminalProcess:
    def start() -> bool:
        """启动终端进程"""
    
    def write(data: str) -> bool:
        """向终端写入数据"""
    
    def stop() -> bool:
        """停止终端进程"""
    
    def get_status() -> Dict[str, Any]:
        """获取终端状态"""
```

#### SocketService
```python
class SocketService:
    def setup_event_handlers():
        """设置Socket.IO事件处理器"""
    
    async def broadcast_to_terminal(item_uuid: str, event: str, data: Any):
        """向终端的所有连接广播事件"""
    
    async def send_to_terminal(item_uuid: str, event: str, data: Any):
        """向终端的第一个连接发送事件（用于控制指令）"""
    
    async def close_terminal_connections(item_uuid: str):
        """关闭终端的所有连接"""
    
    def get_terminal_connections(item_uuid: str) -> List[str]:
        """获取终端的所有连接"""
    
    def get_all_connections() -> Dict[str, List[str]]:
        """获取所有连接"""
    
    def get_connection_count() -> int:
        """获取总连接数"""
    
    def get_terminal_count() -> int:
        """获取终端数"""
    
    def get_connection_tables() -> Dict[str, Any]:
        """获取所有连接表（用户-项目映射、项目-用户连接映射）"""
    
    async def disconnect_user_from_item(item_uuid: str, user_uuid: str) -> bool:
        """断开特定用户与特定项目的Socket连接"""
```

#### AuthService
```python
class AuthService:
    def validate_api_key(api_key: str) -> bool:
        """验证API Key"""
    
    def generate_terminal_token(item_uuid: str) -> str:
        """生成终端Token"""
    
    def validate_terminal_token(item_uuid: str, token: str) -> bool:
        """验证终端Token"""
    
    def revoke_terminal_token(item_uuid: str) -> bool:
        """撤销终端Token"""
```

### api 模块

#### HTTP Routes

| 路径 | 方法 | 描述 |
|------|------|------|
| `/api/terminal/start` | POST | 启动终端 |
| `/api/terminal/stop` | POST | 停止终端 |
| `/api/terminal/status/{item_uuid}` | GET | 获取终端状态 |
| `/api/terminal/list` | GET | 获取所有终端列表 |
| `/api/terminal/list/{user_uuid}` | GET | 获取用户的所有终端列表 |
| `/status` | GET | 获取Daemon状态 |
| `/` | GET | Daemon健康检查接口 |

#### Socket.IO Events

| 事件 | 描述 |
|------|------|
| `connect` | 连接事件 |
| `disconnect` | 断开连接事件 |
| `terminal_connect` | 终端连接事件 |
| `terminal_write` | 终端写入事件 |
| `terminal_connected` | 终端连接成功事件 |
| `auth_error` | 认证错误事件 |

### utils 模块

#### Logger
```python
class Logger:
    def debug(message):
        """写入调试日志"""
    
    def info(message):
        """写入信息日志"""
    
    def warning(message):
        """写入警告日志"""
    
    def error(message):
        """写入错误日志"""
    
    def critical(message):
        """写入严重错误日志"""
```

## 环境变量配置

| 变量名 | 描述 | 默认值 |
|--------|------|--------|
| PORT | Daemon服务端口 | 24444 |
| HOST | Daemon服务主机 | 0.0.0.0 |
| API_KEY | API访问密钥 | 无 |
| WORKDIR | 终端工作目录 | ./src/workdir |
| LOG_DIR | 日志目录 | ./log |
| DATA_DIR | 数据目录 | ./src/data |
| TERMINAL_SHELL | 终端Shell | cmd.exe (Windows) |
| TERMINAL_ENCODING | 终端编码 | utf-8 |
| TERMINAL_BUFFER_SIZE | 终端缓冲区大小 | 8192 |

## 启动方式

1. 安装依赖：
   ```bash
   cd daemon
   poetry install
   ```

2. 配置环境变量：
   ```bash
   cp .env.example .env
   # 编辑.env文件设置API_KEY等配置
   ```

3. 启动服务：
   ```bash
   cd daemon
   poetry run python src/main.py
   ```

## 使用示例

### 启动终端（HTTP）

```bash
curl -X POST http://localhost:24444/api/terminal/start \
  -H "X-API-Key: termman_daemon_secret_key_2024" \
  -H "Content-Type: application/json" \
  -d '{"user_uuid": "user-123", "token": "token-456"}'
```

### 停止终端（HTTP）

```bash
curl -X POST http://localhost:24444/api/terminal/stop \
  -H "X-API-Key: termman_daemon_secret_key_2024" \
  -H "Content-Type: application/json" \
  -d '{"item_uuid": "item-789"}'
```

### 连接终端（Socket.IO）

```javascript
const socket = io("http://localhost:24444");

socket.on("connect", () => {
  console.log("Connected to daemon");
  
  // 连接到终端
  socket.emit("terminal_connect", {
    item_uuid: "item-789",
    token: "token-456"
  });
});

socket.on("terminal_connected", (data) => {
  console.log("Connected to terminal", data.item_uuid);
  
  // 向终端发送命令
  socket.emit("terminal_write", {
    command: "echo hello world"
  });
});

socket.on("auth_error", (data) => {
  console.error("Authentication error", data.message);
});
```

## 日志说明

- 应用日志：`./log/daemon.log`
- 终端日志：`./log/{user_uuid}/{item_uuid}.log`
- 日志级别：INFO、WARNING、ERROR、CRITICAL
- 日志格式：`时间戳 - 日志名 - 级别 - 消息`