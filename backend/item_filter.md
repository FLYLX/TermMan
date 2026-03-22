# Item 过滤配置字段设计

## 数据流

```
终端输出 → 【输入过滤层】 → Agent
     ↑                         ↓
     │                    Agent执行
     │                         ↓
     └────【输出过滤层】← 命令
```

---

## 输入过滤层（终端输出 → Agent）

```json
{
  "input_filter_enabled": true,
  "input_filter_mode": "whitelist",
  "input_noise_patterns": [
    "^\\s*$",
    "^\\d+%$",
    "^\\[=*\\s*\\]$",
    "^\\.+$"
  ],
  "input_event_patterns": {
    "error": ["error:", "failed:", "exception:"],
    "warning": ["warning:", "warn:"],
    "prompt": ["\\$\\s*$", "#\\s*$"]
  }
}
```

### 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `input_filter_enabled` | bool | false | 输入过滤总开关 |
| `input_filter_mode` | string | "blacklist" | 模式: blacklist/whitelist |
| `input_noise_patterns` | List[str] | [] | 噪音模式，匹配后过滤 |
| `input_event_patterns` | Dict | {} | 事件模式，匹配关键事件 |

---

## 输出过滤层（Agent → 终端执行）

```json
{
  "output_filter_enabled": true,
  "output_filter_mode": "blacklist",
  "output_command_list": [
    "rm -rf",
    "chmod",
    "chown",
    "shutdown",
    "reboot",
    "dd",
    "mkfs"
  ],
  "output_sensitive_patterns": [
    "password",
    "api_key",
    "secret",
    "token"
  ],
  "output_rate_limit": 10
}
```

### 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `output_filter_enabled` | bool | false | 输出过滤总开关 |
| `output_filter_mode` | string | "blacklist" | 模式: blacklist/whitelist |
| `output_command_list` | List[str] | [] | 过滤命令列表 |
| `output_sensitive_patterns` | List[str] | [] | 敏感词检测 |
| `output_rate_limit` | int | 10 | 每分钟最大命令数 |

---

## 完整配置示例

### 启用所有过滤

```json
{
  "input_filter_enabled": true,
  "input_filter_mode": "whitelist",
  "input_noise_patterns": [
    "^\\s*$",
    "^\\d+%$",
    "^\\[=*\\s*\\]$"
  ],
  "input_event_patterns": {
    "error": ["error:", "failed:", "exception:"],
    "warning": ["warning:", "warn:"],
    "prompt": ["\\$\\s*$", "#\\s*$"]
  },
  
  "output_filter_enabled": true,
  "output_filter_mode": "blacklist",
  "output_command_list": [
    "rm -rf",
    "chmod 777",
    "chown",
    "shutdown",
    "reboot",
    "dd",
    "mkfs"
  ],
  "output_sensitive_patterns": [
    "password",
    "api_key",
    "secret",
    "token"
  ],
  "output_rate_limit": 10
}
```

### 禁用所有过滤

```json
{
  "input_filter_enabled": false,
  "output_filter_enabled": false
}
```

### 白名单模式

```json
{
  "input_filter_enabled": false,
  
  "output_filter_enabled": true,
  "output_filter_mode": "whitelist",
  "output_command_list": [
    "^ls",
    "^cat",
    "^grep",
    "^tail",
    "^head",
    "^pwd",
    "^git status",
    "^git log"
  ],
  "output_rate_limit": 20
}
```

---

## Item 模型字段定义

```python
# 在 ItemBase 中添加

# 输入过滤
input_filter_enabled: bool = Field(default=False)
input_filter_mode: str = Field(default="blacklist")
input_noise_patterns: Optional[List[str]] = Field(default=None, sa_type=JSON)
input_event_patterns: Optional[dict] = Field(default=None, sa_type=JSON)

# 输出过滤
output_filter_enabled: bool = Field(default=False)
output_filter_mode: str = Field(default="blacklist")
output_command_list: Optional[List[str]] = Field(default=None, sa_type=JSON)
output_sensitive_patterns: Optional[List[str]] = Field(default=None, sa_type=JSON)
output_rate_limit: int = Field(default=10)
```

---

## 需要添加的字段（共10个）

| 层级 | 字段名 | 类型 | 默认值 |
|------|--------|------|--------|
| 输入 | `input_filter_enabled` | bool | false |
| 输入 | `input_filter_mode` | string | "blacklist" |
| 输入 | `input_noise_patterns` | List[str] | null |
| 输入 | `input_event_patterns` | dict | null |
| 输出 | `output_filter_enabled` | bool | false |
| 输出 | `output_filter_mode` | string | "blacklist" |
| 输出 | `output_command_list` | List[str] | null |
| 输出 | `output_sensitive_patterns` | List[str] | null |
| 输出 | `output_rate_limit` | int | 10 |
