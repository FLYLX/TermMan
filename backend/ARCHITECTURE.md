# Backend 架构文档

## 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              Daemon (终端进程)                                    │
│                                  ↓ 输出流                                        │
└─────────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ↓
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              Backend Socket层                                    │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  ItemSocket (socket_pool/item_socket.py)                                  │   │
│  │  - 接收 ProtocolEvents.STREAM 事件                                        │   │
│  │  - 回调: on_stream(data) → stdout/stderr/stdin                           │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ↓
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           Agent Layer                                            │
│  ┌─────────────────────┐    ┌─────────────────────┐    ┌───────────────────┐  │
│  │   Input Filter      │    │   Agent Core        │    │  Output Filter    │  │
│  │   (输入过滤层)       │───→│   (Agent核心)        │───→│  (输出过滤层)      │  │
│  │                     │    │                     │    │                   │  │
│  │  - PatternMatcher   │    │  - LLMClient        │    │  - CommandFilter  │  │
│  │  - EventClassifier  │    │  - ContextManager   │    │  - SafetyChecker  │  │
│  │  - NoiseReducer     │    │  - ActionPlanner    │    │  - RateLimiter    │  │
│  └─────────────────────┘    └─────────────────────┘    └───────────────────┘  │
│           │                          │                          │              │
│           ↓                          ↓                          ↓              │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                        Memory System (记忆系统)                          │   │
│  │  - ShortTermMemory: 会话级记忆 (SQLite)                                  │   │
│  │  - LongTermMemory: 持久化记忆 (ChromaDB 向量存储)                        │   │
│  │  - ItemContext: Item特定上下文                                          │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## 目录结构

```
backend/
├── app/
│   ├── main.py              # 应用入口
│   ├── models.py            # 数据库模型
│   ├── crud.py              # 数据库操作
│   ├── core/
│   │   ├── config.py        # 配置管理
│   │   ├── db.py            # 数据库连接
│   │   └── security.py      # 安全工具
│   ├── api/
│   │   ├── main.py          # API路由汇总
│   │   ├── deps.py          # 依赖注入
│   │   └── routes/
│   │       ├── login.py     # 登录认证
│   │       ├── users.py     # 用户管理
│   │       ├── items.py     # Item管理
│   │       ├── item_handlers.py  # ItemHandler管理
│   │       ├── chat.py      # 对话接口
│   │       ├── knowledge.py # 知识库
│   │       ├── skills.py    # 技能
│   │       ├── memory.py    # 记忆
│   │       └── mcp.py       # MCP协议
│   ├── services/
│   │   ├── agent/           # Agent核心
│   │   ├── robot/           # 机器人接入
│   │   ├── socket_pool/     # 终端流分发
│   │   ├── connection_pool/ # Daemon连接管理
│   │   ├── filters/         # 输入/输出过滤
│   │   └── protocol/        # 通信协议
│   └── alembic/             # 数据库迁移
├── skills/                  # Skill存储目录
├── tests/                   # 测试
└── pyproject.toml           # 项目配置
```

## 核心模块

### 1. Agent 系统

Agent 系统采用混合存储架构，结合短期记忆和长期记忆。

#### Agent 类 (`services/agent/agent.py`)

- 一个 ItemHandler 对应一个 Agent 实例
- 自动加载 ItemHandler 配置的 Skills
- 管理记忆（短期 + 长期）
- 处理对话请求

#### 会话管理 (`services/agent/session.py`)

- 单个 Item 的 Agent 会话状态
- 会话生命周期管理

#### 流式输出 (`services/agent/stream_manager.py`)

- 流式响应管理
- SSE 事件推送

### 2. Memory 系统

```
┌─────────────────────────────────────────────────────────────────┐
│                        Memory System                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────┐    ┌─────────────────────┐            │
│  │   Short-Term        │    │   Long-Term         │            │
│  │   (SQLite)          │    │   (ChromaDB)        │            │
│  │                     │    │                     │            │
│  │  - 会话历史          │    │  - 向量嵌入          │            │
│  │  - 最近N条交互       │    │  - 语义检索          │            │
│  │  - 临时上下文        │    │  - 持久化存储        │            │
│  └─────────────────────┘    └─────────────────────┘            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### 记忆类型

| 类型 | 说明 |
|------|------|
| `fact` | 事实信息：用户名、路径、配置值等 |
| `preference` | 用户偏好：代码风格、工具选择等 |
| `task` | 任务相关：待办事项、计划等 |
| `error` | 错误记录：已知问题和解决方案 |
| `context` | 上下文：项目结构、依赖关系等 |

### 3. Skill 系统

#### 目录结构

```
backend/skills/
├── my_skill_1/
│   ├── SKILL.md          # 核心定义文件（必须）
│   ├── scripts/          # 脚本文件
│   ├── templates/        # 模板文件
│   └── examples/         # 示例文件
└── my_skill_2/
    └── SKILL.md
```

#### SKILL.md 格式

```markdown
---
skill_id: npm_fixer
name: NPM 修复器
description: 自动修复 npm 依赖问题
category: devtools
trigger:
  type: auto
  patterns:
    - "npm ERR!"
action:
  type: llm
  prompt: "分析以下 npm 错误并提供修复方案"
safety:
  requires_approval: false
  risk_level: low
---
```

### 4. Knowledge 系统

知识库采用 RAG (检索增强生成) 架构：

```
文件入库 → 增量索引 → 切块 → 向量化 → 相似度检索 → 注入 Prompt → 生成回答
```

#### 核心特点

- 知识文件统一进入共享知识库
- 每个 ItemHandler 只保存启用的知识文件引用
- 回答问题时只检索当前 ItemHandler 启用的知识文件

### 5. 过滤器系统

#### 输入过滤层（终端输出 → Agent）

```json
{
  "input_filter_enabled": true,
  "input_filter_mode": "whitelist",
  "input_noise_patterns": ["^\\s*$", "^\\d+%$"],
  "input_event_patterns": {
    "error": ["error:", "failed:"],
    "warning": ["warning:", "warn:"]
  }
}
```

#### 输出过滤层（Agent → 终端执行）

```json
{
  "output_filter_enabled": true,
  "output_filter_mode": "blacklist",
  "output_command_list": ["rm -rf", "chmod", "shutdown"],
  "output_sensitive_patterns": ["password", "api_key", "secret"],
  "output_rate_limit": 10
}
```

### 6. Robot 系统

机器人接入拆成两层：

#### Backend 路由与业务层

- 存储机器人配置和绑定关系
- 决定消息路由到哪个 Item
- 复用现有 Agent 对话链路

#### NoneBot2 Bridge 进程

- 连接 QQ 官方机器人
- 接收 QQ 消息并转换为统一结构
- 调用 Backend dispatch 接口
- 发送回复到 QQ

## 数据模型

### 核心实体关系

```
User ──┬── owns ──► Item (终端)
       │
       └── owns ──► ItemHandler (Agent配置)
                         │
                         ├── binds ──► Item (多对多)
                         │
                         ├── enables ──► KnowledgeFile
                         │
                         └── loads ──► Skill
```

### 主要模型

| 模型 | 说明 |
|------|------|
| `User` | 用户 |
| `Item` | 终端实例 |
| `ItemHandler` | Agent 配置 |
| `ItemHandlerItem` | ItemHandler-Item 关联 |
| `ItemHandlerUser` | ItemHandler-User 权限关联 |
| `Robot` | 机器人配置 |
| `RobotItem` | Robot-Item 绑定 |

## 凭证体系

Backend 是所有凭证的唯一签发中心：

| 凭证类型 | 签发方 | 验证方 | 格式 | 有效期 |
|---------|--------|--------|------|--------|
| 用户 Token | Backend | Backend | JWT | 数小时/天 |
| 终端临时 Token | Backend | Daemon | 签名字符串 | 10分钟 |
| Daemon 认证 Token | Backend | Backend | 随机字符串 | 30分钟 |
| API Key | 预配置 | Daemon | 预配置字符串 | 永久 |

## 配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `SQLITE_DATABASE_URL` | `sqlite:///./sql_app.db` | SQLite 数据库路径 |
| `CHROMA_PERSIST_DIR` | `./chroma_data` | ChromaDB 持久化目录 |
| `KNOWLEDGE_BASE_DIR` | `./knowledge` | 知识文件目录 |
| `ROBOT_PLUGIN_ENABLED` | `true` | 是否启动机器人插件 |
| `ROBOT_BRIDGE_EMBEDDED` | `false` | 是否内嵌 Bridge 进程 |
