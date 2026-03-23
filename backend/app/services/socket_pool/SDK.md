# Item 订阅中心 & 输入中心 SDK 使用指南

## 概述

本模块提供两个核心中心：
- **SubscriptionCenter**: 订阅中心，处理终端输出事件分发
- **InputCenter**: 输入中心，处理命令发送到终端

## 架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              完整数据流                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Input (命令输入)                          Output (输出订阅)                │
│   ────────────────                         ────────────────                 │
│                                                                             │
│   Agent/SDK                                LogSubscriber → 写入日志         │
│       │                                         ▲                          │
│       ▼                                         │                          │
│   InputCenter                              SubscriptionCenter               │
│       │                                         ▲                          │
│       ▼                                         │                          │
│   ItemSocket.write()                       ItemSocket                       │
│       │                                         │                          │
│       │         ┌──────────────┐               │                          │
│       └────────►│    Daemon    │───────────────┘                          │
│                 │   (终端)      │                                           │
│                 └──────────────┘                                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

# 一、订阅中心 (SubscriptionCenter)

用于订阅终端输出事件。

## 事件类型

| 事件类型 | 说明 |
|---------|------|
| `STREAM` | 终端输出流 (stdout/stderr/stdin) |
| `TERMINAL_CONNECTED` | 终端连接成功 |
| `TERMINAL_DISCONNECTED` | 终端断开连接 |
| `AUTH_ERROR` | 认证错误 |

## 快速开始

### 1. 订阅日志（写入文件）

```python
from app.services.socket_pool import ItemSubscriberSDK

sdk = ItemSubscriberSDK()

sub_id = sdk.subscribe_log(
    item_uuid="your-item-uuid",
    owner_uuid="owner-uuid",
    log_manager=log_manager
)

sdk.unsubscribe(sub_id)
```

### 2. 订阅原始流数据

```python
from app.services.socket_pool import ItemSubscriberSDK

sdk = ItemSubscriberSDK()

def my_callback(data: dict):
    stdout = data.get("stdout", "")
    print(f"收到输出: {stdout}")

sub_id = sdk.subscribe_stream("your-item-uuid", my_callback)
```

### 3. 订阅所有事件类型

```python
from app.services.socket_pool import ItemSubscriberSDK, SubscriptionEvent

sdk = ItemSubscriberSDK()

def handle_all_events(event: SubscriptionEvent):
    print(f"事件类型: {event.event_type}")
    print(f"数据: {event.data}")

sub_id = sdk.subscribe_all_events("your-item-uuid", handle_all_events)
```

## 便捷函数

```python
from app.services.socket_pool import create_log_subscriber, create_stream_subscriber

sub_id = create_log_subscriber(item_uuid, owner_uuid, log_manager)
sub_id = create_stream_subscriber(item_uuid, my_callback)
```

## 订阅管理

```python
sdk = ItemSubscriberSDK()

sdk.unsubscribe(sub_id)
sdk.unsubscribe_all()
sdk.unsubscribe_item(item_uuid)
count = sdk.get_subscriber_count(item_uuid)
```

---

# 二、输入中心 (InputCenter)

用于向终端发送命令。

## 核心概念

**处理器是持久的**：`register_socket_handler` 注册一次后，可以多次发送命令，不需要每次发送都新建处理器。

```
注册阶段（一次）          发送阶段（多次）
─────────────           ─────────────
register_handler()  →   send() → 处理器执行
                       send() → 处理器执行
                       send() → 处理器执行
                       ...
```

## 快速开始

### 1. 注册输入处理器

```python
from app.services.socket_pool import InputSDK

sdk = InputSDK()

# 注册处理器 - 定义如何将命令写入终端
def write_to_terminal(command: str) -> bool:
    # 这里实现实际的写入逻辑
    return terminal.write(command)

h_id = sdk.register_handler(
    item_uuid="your-item-uuid",
    write_callback=write_to_terminal
)
```

### 2. 注册 Socket 处理器（推荐）

```python
from app.services.socket_pool import InputSDK

sdk = InputSDK()

# 使用 backend socket 连接发送命令
h_id = sdk.register_socket_handler(
    item_uuid="your-item-uuid",
    socket_manager=socket_manager
)
# 注册后可多次调用 send() 发送命令
```

### 3. 发送命令

```python
from app.services.socket_pool import InputSDK

sdk = InputSDK()

# 发送到指定 item
sdk.send("item-uuid", "ls -la\n")

# 发送到所有已注册的 item
results = sdk.send_to_all("echo 'hello'\n")
# results: {"item-uuid-1": True, "item-uuid-2": False, ...}
```

### 4. 便捷函数

```python
from app.services.socket_pool import send_command, send_command_to_all

# 直接发送命令（无需创建 SDK 实例）
send_command("item-uuid", "ls -la\n")

# 发送到所有
send_command_to_all("echo 'hello'\n")
```

## 处理器管理

```python
sdk = InputSDK()

# 取消单个处理器
sdk.unregister(handler_id)

# 取消该 SDK 创建的所有处理器
sdk.unregister_all()

# 取消某个 item 的所有处理器
sdk.unregister_item(item_uuid)

# 检查是否有处理器
has_handler = sdk.has_handler(item_uuid)

# 获取处理器数量
count = sdk.get_handler_count(item_uuid)
```

## InputCommand 结构

```python
@dataclass
class InputCommand:
    item_uuid: str      # 目标 Item UUID
    command: str        # 要执行的命令
    source: str         # 来源标识 (默认 "sdk")
    timestamp: datetime # 创建时间
```

## 典型使用场景

```python
class TerminalService:
    def __init__(self):
        self.input_sdk = InputSDK()
        self.handlers = {}
    
    def on_item_connect(self, item_uuid: str, socket_manager):
        # 连接时注册一次
        h_id = self.input_sdk.register_socket_handler(
            item_uuid, socket_manager
        )
        self.handlers[item_uuid] = h_id
    
    def execute_command(self, item_uuid: str, command: str):
        # 多次发送命令
        return self.input_sdk.send(item_uuid, command)
    
    def on_item_disconnect(self, item_uuid: str):
        # 断开时注销
        if item_uuid in self.handlers:
            self.input_sdk.unregister(self.handlers[item_uuid])
            del self.handlers[item_uuid]
```

---

# 三、完整示例

## Agent 自动化执行

```python
import logging
from app.services.socket_pool import (
    ItemSubscriberSDK,
    InputSDK,
    SubscriptionEvent,
    SubscriptionEventType
)
from app.services.log_manager import LogManager

logger = logging.getLogger(__name__)
log_manager = LogManager()

class TerminalAgent:
    def __init__(self, socket_manager):
        self.sub_sdk = ItemSubscriberSDK()
        self.input_sdk = InputSDK()
        self.socket_manager = socket_manager
        self.monitored_items = {}
    
    def start_agent(self, item_uuid: str, owner_uuid: str):
        # 注册日志订阅
        log_sub_id = self.sub_sdk.subscribe_log(
            item_uuid, owner_uuid, log_manager
        )
        
        # 注册输入处理器
        input_h_id = self.input_sdk.register_socket_handler(
            item_uuid, self.socket_manager
        )
        
        # 订阅断开事件
        def on_disconnect(event: SubscriptionEvent):
            logger.warning(f"终端 {item_uuid} 已断开")
        
        disconnect_sub_id = self.sub_sdk.subscribe(
            item_uuid=item_uuid,
            callback=on_disconnect,
            event_types=[SubscriptionEventType.TERMINAL_DISCONNECTED]
        )
        
        self.monitored_items[item_uuid] = {
            "log_sub": log_sub_id,
            "input_h": input_h_id,
            "disconnect_sub": disconnect_sub_id
        }
    
    def execute_command(self, item_uuid: str, command: str) -> bool:
        return self.input_sdk.send(item_uuid, command)
    
    def execute_on_all(self, command: str) -> dict[str, bool]:
        return self.input_sdk.send_to_all(command)
    
    def stop_agent(self, item_uuid: str):
        if item_uuid in self.monitored_items:
            info = self.monitored_items[item_uuid]
            self.sub_sdk.unsubscribe(info["log_sub"])
            self.sub_sdk.unsubscribe(info["disconnect_sub"])
            self.input_sdk.unregister(info["input_h"])
            del self.monitored_items[item_uuid]
    
    def stop_all(self):
        self.sub_sdk.unsubscribe_all()
        self.input_sdk.unregister_all()
        self.monitored_items.clear()
```

## 使用示例

```python
# 初始化
agent = TerminalAgent(socket_manager)

# 启动监控
agent.start_agent("item-123", "user-456")

# 执行命令
agent.execute_command("item-123", "python script.py\n")

# 批量执行
agent.execute_on_all("date\n")

# 停止
agent.stop_agent("item-123")
```

---

# 四、注意事项

1. **线程安全**: 两个中心都是线程安全的，可在多线程环境使用
2. **单例模式**: `subscription_center` 和 `input_center` 都是全局单例
3. **及时清理**: 不再需要时请取消订阅/注销处理器，避免内存泄漏
4. **命令格式**: 命令需要带换行符 `\n` 才会被终端执行
5. **回调异常**: 回调中的异常会被捕获并记录日志，不影响其他处理
