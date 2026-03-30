# 终端输出双流架构

## 架构概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Terminal Output                                    │
│                               (原始输出)                                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        SubscriptionCenter                                    │
│                    publish_stream(item_id, data)                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
        ┌─────────────────────┐         ┌─────────────────────┐
        │    InputFilter      │         │    LogManager       │
        │   (过滤处理)         │         │   (写入日志)         │
        └─────────────────────┘         └─────────────────────┘
                    │                               │
                    │ filtered_output               │ raw_output (完整日志)
                    │                               │
                    └───────────────┬───────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       TerminalStreamManager                                  │
│                process_stream(item_id, raw, filtered, handler_id)            │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
            ┌───────▼───────┐               ┌───────▼───────┐
            │ Agent Window? │               │               │
            │  时间窗口判断   │               │               │
            └───────┬───────┘               │               │
                    │                       │               │
            ┌───────┴───────┐               │               │
            │               │               │               │
            ▼               ▼               ▼               ▼
    ┌───────────────┐ ┌───────────────┐
    │  Agent Stream │ │   MCP Stream  │
    │  (过滤输出)    │ │  (过滤输出)    │
    │               │ │               │
    │  → LLM 分析   │ │  → MCP 回调   │
    │  (节省 token) │ │               │
    └───────┬───────┘ └───────────────┘
            │
            │ 需要详细日志?
            ▼
    ┌───────────────────────────────────────────┐
    │           read_terminal_log 工具          │
    │         读取 log/{item_id}.log            │
    │            (原始完整输出)                   │
    └───────────────────────────────────────────┘
```

## 核心设计原则

### 1. Agent 获取过滤输出（节省 Token）

```
终端原始输出
    │
    ▼ InputFilter 过滤
    │
    ├─ 移除无关信息
    ├─ 精简输出内容
    └─ 提取关键信息
    │
    ▼
Agent 收到过滤后的输出
    │
    ├─ 输出为空? → 不处理，不回复（省 token）
    └─ 有内容? → 分析处理
```

### 2. 日志文件保存原始输出

```
终端原始输出
    │
    ▼ LogManager.write_to_log()
    │
    └─ log/{item_id}.log (完整原始输出)
```

**用途：**
- 修复 Bug 时查看完整错误信息
- 查看命令执行反馈
- 分析被过滤掉的内容

### 3. MCP 工具读取日志

```python
# Agent 可以调用 read_terminal_log 工具
{
    "name": "read_terminal_log",
    "arguments": {
        "item_id": "xxx-xxx-xxx",
        "lines": 64  # 读取最后 64 行
    }
}
```

## 数据流详解

### Agent Stream

```
Agent 发送命令
    │
    ▼
open_agent_window(item_id, query)
    │
    ▼
终端输出到达
    │
    ├─ InputFilter 过滤 → filtered_output
    │
    ▼
_handle_agent_stream(item_id, filtered_output, handler_id)
    │
    ├─ filtered_output 为空? → 跳过处理（省 token）
    │
    └─ 有内容? → 调用 LLM
            │
            ├─ System Prompt 告知 Agent:
            │   - 输出是过滤后的精简版本
            │   - 需要详细信息时调用 read_terminal_log
            │   - 不需要处理时回复"无需处理"
            │
            └─ LLM 决定是否需要读取日志
```

### System Prompt

```
你是服务器运维助手。

重要说明：
1. 你收到的终端输出是经过过滤的精简版本，用于节省 token
2. 如果输出被 input_filter 过滤，你可能只看到部分信息或空输出
3. 如果需要查看完整的原始输出，使用 read_terminal_log 工具读取日志文件
4. 如果需要修复错误，先使用 read_terminal_log 查看完整错误信息
5. 如果当前输出不需要任何处理，直接回复"无需处理"，不要浪费 token

可用工具：
- mcp_local_execute_command: 执行终端命令
- read_terminal_log: 读取终端日志（原始输出）
- read_file: 读取文件内容
- write_file: 写入文件内容
```

## MCP 工具

### read_terminal_log

**描述：** 读取终端日志文件（原始输出），用于查看完整的错误信息或命令执行结果。

**参数：**
```json
{
    "item_id": "终端 ID",
    "lines": 64  // 可选，默认 64 行
}
```

**返回：**
```
=== 终端日志 (最后 64 行) ===
[原始完整输出内容]
```

### execute_command

**描述：** 在终端执行 shell 命令

**参数：**
```json
{
    "command": "要执行的命令",
    "item_id": "终端 ID"
}
```

## 文件结构

```
backend/
├── skills/
│   ├── terminal/
│   │   └── SYSTEM_PROMPT.md   # 终端智能助手 system prompt
│   └── mc/
│       └── SKILL.md           # MC服务器管理技能
└── app/services/
    ├── agent/
    │   ├── stream_manager.py  # 双流管理器
    │   └── mcp/
    │       └── local_server.py # MCP 工具（含 read_terminal_log）
    ├── filters/
    │   └── input_filter.py    # 输入过滤器
    ├── log/
    │   └── {item_id}.log      # 终端日志文件
    ├── log_manager.py         # 日志管理器
    └── socket_pool/
        └── subscription_center.py # 订阅发布中心
```

## Skills 技能

### terminal - 终端智能助手

**文件：** `skills/terminal/SYSTEM_PROMPT.md`

**触发条件：** agent_window_active（Agent 时间窗口激活时）

**两个核心功能：**

| 工具 | 功能 | 用途 |
|------|------|------|
| `mcp_local_execute_command` | 执行命令 | 向终端发送指令 |
| `mcp_local_read_terminal_log` | 读取日志 | 获取命令响应和错误信息 |

**工作流程：**
```
收到过滤输出
    │
    ├─ 空输出 → 不回复（省 token）
    ├─ 正常输出 → "无需处理"
    └─ 错误迹象
        │
        ▼
    read_terminal_log 查看完整错误
        │
        ▼
    execute_command 执行修复命令
        │
        ▼
    read_terminal_log 确认结果
```

## 关键代码

### stream_manager.py - 流管理（不含 prompt）

```python
def _get_skill_prompt(self, agent: "Agent", query: str = "") -> str:
    """从 Skill 获取 prompt，而不是硬编码"""
    skills = agent.get_skills()
    for skill in skills:
        if skill.action and skill.action.prompt:
            prompt = skill.action.prompt
            if query:
                prompt = f"{prompt}\n\n用户问题: {query}"
            return prompt
    
    return "你是服务器运维助手。分析终端输出，如果发现错误请尝试修复。"

def process_stream(self, item_id: str, filtered_output: str, handler_id: str = None):
    if self.is_in_agent_window(item_id):
        self._handle_agent_stream(item_id, filtered_output, handler_id)
    else:
        self._handle_mcp_stream(item_id, filtered_output)
```

### local_server.py - MCP 工具

```python
def _read_terminal_log(self, args: dict) -> list:
    item_id = args.get("item_id", "")
    lines = args.get("lines", 64)
    
    log_manager = LogManager()
    content = log_manager.get_last_lines(item_id, lines)
    
    return [{"type": "text", "text": f"=== 终端日志 (最后 {lines} 行) ===\n{content}"}]
```

### SYSTEM_PROMPT.md - Skill 定义（存放 prompt）

```yaml
action:
  type: llm
  prompt: |
    ## 核心功能
    
    你有两个工具管理终端：
    
    ### 1. 执行命令
    mcp_local_execute_command(command, item_id)
    
    ### 2. 读取日志
    mcp_local_read_terminal_log(item_id, lines=64)
    
    ## 工作流程
    ...
```

## 优势

1. **节省 Token** - Agent 默认收到过滤后的精简输出
2. **完整信息** - 需要时可读取完整日志
3. **智能判断** - Agent 自主决定是否需要详细信息
4. **灵活过滤** - 不同 Item 可配置不同过滤规则
5. **日志持久化** - 原始输出完整保存，便于排查问题

## 安全保护机制

### 防止死循环和卡死

```
┌─────────────────────────────────────────────────────────────┐
│                     安全限制                                 │
├─────────────────────────────────────────────────────────────┤
│  LLM 请求超时      60s    REQUEST_TIMEOUT                   │
│  命令等待超时      20s    COMMAND_WAIT_TIMEOUT              │
│  单次会话命令数    5      MAX_COMMANDS_PER_SESSION          │
│  会话总时长        120s   SESSION_TIMEOUT                   │
│  Skill 最大重试    2      max_retries                       │
└─────────────────────────────────────────────────────────────┘
```

### 完整闭环

```
发现问题
    │
    ▼
read_terminal_log 查看完整错误
    │
    ▼
分析问题，确定修复方案
    │
    ▼
execute_command 执行修复命令
    │
    ├─ 命令数 < 5 && 时间 < 120s → 继续
    │
    └─ 超限 → 终止会话，告知用户
    │
    ▼
read_terminal_log 确认结果
    │
    ├─ 问题解决 → 结束
    └─ 未解决 → 继续尝试（受限制保护）
```

### 代码实现

```python
def should_stop_session(self, item_id: str) -> tuple[bool, str]:
    window = self._agent_windows.get(item_id)
    
    if window.command_count >= MAX_COMMANDS_PER_SESSION:
        return True, f"已达到最大命令次数限制 ({MAX_COMMANDS_PER_SESSION})"
    
    if window.session_start:
        elapsed = (datetime.now() - window.session_start).total_seconds()
        if elapsed > SESSION_TIMEOUT:
            return True, f"会话超时 ({SESSION_TIMEOUT}s)"
    
    return False, ""

# 执行命令前检查
if tool_name == "mcp_local_execute_command":
    should_stop, reason = self.should_stop_session(item_id)
    if should_stop:
        self._emit_to_chat(item_id, f"会话终止: {reason}", "agent_warning")
        self.reset_session(item_id)
        return
    self.increment_command_count(item_id)
```
