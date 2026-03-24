# Agent 模块使用指南

## 概述

Agent 模块提供智能终端代理功能，能够自动监控终端输出、分析事件、生成并执行命令。

## 架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Agent 数据流                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   终端输出 (stdout/stderr)                                                   │
│         │                                                                   │
│         ▼                                                                   │
│   ┌─────────────────┐                                                       │
│   │  InputFilter    │  过滤噪音，识别重要事件                                │
│   └────────┬────────┘                                                       │
│            │                                                                │
│            ▼                                                                │
│   ┌─────────────────┐                                                       │
│   │   AgentEngine   │  分析事件，调用 LLM                                    │
│   │                 │                                                       │
│   │  ┌───────────┐  │                                                       │
│   │  │ LLMClient │  │  使用 litellm 统一接口                                │
│   │  └───────────┘  │                                                       │
│   │  ┌───────────┐  │                                                       │
│   │  │  Memory   │  │  短期记忆 + 上下文管理                                 │
│   │  └───────────┘  │                                                       │
│   └────────┬────────┘                                                       │
│            │                                                                │
│            ▼                                                                │
│   ┌─────────────────┐                                                       │
│   │  OutputFilter   │  安全检查，命令过滤                                    │
│   └────────┬────────┘                                                       │
│            │                                                                │
│            ▼                                                                │
│   ┌─────────────────┐                                                       │
│   │  InputCenter    │  发送命令到终端                                        │
│   └─────────────────┘                                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 目录结构

```
agent/
├── __init__.py              # 模块导出
├── engine.py                # Agent 主引擎
├── handler_manager.py       # Handler 管理器 (单例)
│
├── filters/
│   ├── __init__.py
│   ├── input_filter.py      # 输入过滤器 (终端输出 → Agent)
│   └── output_filter.py     # 输出过滤器 (Agent → 终端)
│
├── llm/
│   ├── __init__.py
│   ├── llm_client.py        # LLM 客户端 (litellm)
│   └── prompt_templates.py  # Prompt 模板
│
└── memory/
    ├── __init__.py
    ├── memory_manager.py    # 记忆管理器
    ├── short_term_memory.py # 短期记忆
    └── item_context.py      # Item 上下文
```

## 快速开始

### 1. 初始化 HandlerManager

```python
from app.services.agent import HandlerManager, handler_manager
from app.services.socket_pool import socket_manager

# 设置 socket 管理器
handler_manager.set_socket_manager(socket_manager)
```

### 2. 创建 Agent 实例

```python
# 从数据库获取 handler 和 item
handler = await session.get(ItemHandler, handler_id)
item = await session.get(Item, item_id)

# 创建并绑定 Agent
engine = handler_manager.create_engine(handler, item)
```

### 3. 与 Agent 交互

```python
# 发送消息给 Agent
response = handler_manager.chat(
    handler_id=str(handler.id),
    item_uuid=str(item.id),
    message="分析当前终端状态"
)

# 手动执行命令
success = handler_manager.execute_command(
    handler_id=str(handler.id),
    item_uuid=str(item.id),
    command="ls -la\n"
)

# 批准待执行的命令
command = handler_manager.approve_command(
    handler_id=str(handler.id),
    item_uuid=str(item.id)
)
```

## 核心组件

### InputFilter (输入过滤器)

从终端输出中提取有价值信息，过滤噪音。

**配置来源**: Item 模型字段
- `input_filter_enabled`: 是否启用
- `input_filter_mode`: 过滤模式
- `input_noise_patterns`: 噪音模式列表
- `input_event_patterns`: 事件模式字典

**事件类型**:
| 类型 | 说明 |
|------|------|
| `NEEDS_ACTION` | 需要 Agent 响应 |
| `INFORMATIONAL` | 信息性，可记录 |
| `NOISE` | 噪音，忽略 |

```python
from app.services.agent import InputFilter, InputFilterConfig

config = InputFilterConfig.from_item(item)
input_filter = InputFilter(config)

event = input_filter.filter({
    "stdout": "error: connection failed",
    "stderr": ""
})

if event and event.event_type == EventType.NEEDS_ACTION:
    print(f"需要处理: {event.raw_content}")
```

### OutputFilter (输出过滤器)

安全检查 Agent 生成的命令。

**配置来源**: Item 模型字段
- `output_filter_enabled`: 是否启用
- `output_filter_mode`: 过滤模式 (blacklist/whitelist)
- `output_command_list`: 命令列表
- `output_sensitive_patterns`: 敏感模式列表
- `output_rate_limit`: 频率限制 (次/分钟)

**过滤结果**:
| 动作 | 说明 |
|------|------|
| `ALLOWED` | 允许执行 |
| `BLOCKED` | 阻止执行 |
| `MODIFIED` | 修改后执行 |
| `NEEDS_APPROVAL` | 需要人工审批 |

```python
from app.services.agent import OutputFilter, OutputFilterConfig

config = OutputFilterConfig.from_item(item)
output_filter = OutputFilter(config)

result = output_filter.filter("rm -rf /", item_uuid)

if result.is_blocked:
    print(f"命令被阻止: {result.reason}")
elif result.needs_approval:
    print(f"需要审批: {result.reason}")
```

### LLMClient (LLM 客户端)

使用 litellm 统一接口调用各种 LLM。

**支持的模型**:
- OpenAI: `gpt-3.5-turbo`, `gpt-4`, etc.
- Anthropic: `claude-2`, `claude-instant-1`
- Azure: `azure/gpt-35-turbo`
- 本地: `ollama/llama2`, etc.

```python
from app.services.agent import LLMClient, LLMConfig

config = LLMConfig(
    model="gpt-4",
    api_key="your-api-key",
    api_url="https://api.openai.com/v1"
)

client = LLMClient(config)

# 简单对话
response = client.chat("分析这个错误: connection refused")

# 带上下文的对话
response = client.chat(
    message="如何解决这个问题?",
    system_prompt="你是一个终端助手",
    context="当前目录: /home/user, 最后命令: npm install"
)
```

### MemoryManager (记忆管理)

管理 Agent 的记忆系统。

```python
from app.services.agent import MemoryManager

memory = MemoryManager(handler_id="handler-123")

# 记录交互
memory.record_exchange(
    item_uuid="item-456",
    user_input="检查日志",
    agent_response="正在检查...",
    command="tail -f /var/log/app.log\n"
)

# 获取上下文
context = memory.get_relevant_context("item-456")

# 获取最近交互
recent = memory.get_recent_interactions("item-456", limit=5)
```

### AgentEngine (主引擎)

协调各组件完成智能终端操作。

```python
from app.services.agent import AgentEngine, AgentConfig

config = AgentConfig.from_handler_and_items(handler, item)
engine = AgentEngine(config)

# 设置命令执行回调
def on_command(item_uuid: str, command: str) -> bool:
    # 实际执行命令
    return socket.write(command)

engine.set_command_callback(on_command)

# 处理终端输出
command = engine.process_stream(item_uuid, {
    "stdout": "npm ERR! missing script: build",
    "stderr": ""
})

# 如果返回命令，说明 Agent 决定执行
if command:
    print(f"Agent 执行: {command}")
```

### HandlerManager (管理器)

管理多个 Agent 实例与 Item 的绑定。

```python
from app.services.agent import handler_manager

# 创建并绑定
engine = handler_manager.create_engine(handler, item)

# 获取引擎
engine = handler_manager.get_engine(handler_id, item_uuid)

# 获取 Item 的所有引擎
engines = handler_manager.get_engines_for_item(item_uuid)

# 解绑
handler_manager.unbind_handler(handler_id, item_uuid)

# 清理
handler_manager.cleanup_item(item_uuid)
handler_manager.cleanup_handler(handler_id)
```

## 完整示例

### 自动化监控 Agent

```python
import logging
from app.services.agent import handler_manager
from app.services.socket_pool import socket_manager

logger = logging.getLogger(__name__)

class TerminalAgentService:
    def __init__(self):
        self.handler_manager = handler_manager
        self.handler_manager.set_socket_manager(socket_manager)
    
    async def start_monitoring(self, handler, item):
        engine = self.handler_manager.create_engine(handler, item)
        
        # 设置审批回调
        def on_approval(item_uuid: str, pending) -> bool:
            logger.warning(f"需要审批命令: {pending.command}")
            logger.warning(f"原因: {pending.reason}")
            # 可以在这里实现自动审批逻辑
            return False  # 默认不自动批准高风险命令
        
        engine.set_approval_callback(on_approval)
        
        logger.info(f"Agent started for handler={handler.id}, item={item.id}")
        return engine
    
    async def stop_monitoring(self, handler_id: str, item_uuid: str):
        self.handler_manager.unbind_handler(handler_id, item_uuid)
        logger.info(f"Agent stopped for handler={handler_id}, item={item_uuid}")
    
    async def chat(self, handler_id: str, item_uuid: str, message: str) -> str:
        return self.handler_manager.chat(handler_id, item_uuid, message)
    
    async def approve(self, handler_id: str, item_uuid: str) -> str | None:
        return self.handler_manager.approve_command(handler_id, item_uuid)
    
    async def reject(self, handler_id: str, item_uuid: str) -> bool:
        return self.handler_manager.reject_command(handler_id, item_uuid)
    
    async def get_status(self, handler_id: str, item_uuid: str) -> dict:
        return self.handler_manager.get_stats(handler_id, item_uuid)
```

### 使用示例

```python
service = TerminalAgentService()

# 启动监控
await service.start_monitoring(handler, item)

# 与 Agent 对话
response = await service.chat(
    handler_id=str(handler.id),
    item_uuid=str(item.id),
    message="检查当前目录的文件"
)

# 获取状态
status = await service.get_status(str(handler.id), str(item.id))
print(f"状态: {status['state']}")
print(f"交互次数: {status['memory']['interaction_count']}")

# 停止监控
await service.stop_monitoring(str(handler.id), str(item.id))
```

## Item 模型配置字段

Agent 的行为由 Item 模型中的字段控制:

### 输入过滤配置
```python
input_filter_enabled: bool = False       # 是否启用输入过滤
input_filter_mode: str = "blacklist"     # 模式: blacklist/whitelist
input_noise_patterns: List[str]          # 噪音正则模式
input_event_patterns: dict               # 事件匹配模式
```

### 输出过滤配置
```python
output_filter_enabled: bool = False      # 是否启用输出过滤
output_filter_mode: str = "blacklist"    # 模式: blacklist/whitelist
output_command_list: List[str]           # 命令正则列表
output_sensitive_patterns: List[str]     # 敏感数据模式
output_rate_limit: int = 10              # 频率限制 (次/分钟)
```

## 注意事项

1. **安全性**: OutputFilter 会阻止危险命令，高风险命令需要人工审批
2. **频率限制**: 默认每分钟最多 10 条命令，防止命令风暴
3. **记忆管理**: 短期记忆默认保留最近 100 条交互
4. **线程安全**: HandlerManager 是单例且线程安全的
5. **资源清理**: 不再使用时调用 `unbind_handler` 或 `cleanup_*` 方法
