# Backend 架构文档

## 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────────�?
�?                             Daemon (终端进程)                                    �?
�?                                 �?输出�?                                       �?
└─────────────────────────────────────────────────────────────────────────────────�?
                                         �?
                                         �?
┌─────────────────────────────────────────────────────────────────────────────────�?
�?                             Backend Socket�?                                   �?
�? ┌──────────────────────────────────────────────────────────────────────────�?  �?
�? �? ItemSocket (socket_pool/item_socket.py)                                  �?  �?
�? �? - 接收 ProtocolEvents.STREAM 事件                                        �?  �?
�? �? - 回调: on_stream(data) �?stdout/stderr/stdin                           �?  �?
�? └──────────────────────────────────────────────────────────────────────────�?  �?
└─────────────────────────────────────────────────────────────────────────────────�?
                                         �?
                                         �?
┌─────────────────────────────────────────────────────────────────────────────────�?
�?                          Agent Layer                                            �?
�? ┌─────────────────────�?   ┌─────────────────────�?   ┌───────────────────�? �?
�? �?  Input Filter      �?   �?  Agent Core        �?   �? Output Filter    �? �?
�? �?  (输入过滤�?       │───→│   (Agent核心)        │───→│  (输出过滤�?      �? �?
�? �?                    �?   �?                    �?   �?                  �? �?
�? �? - PatternMatcher   �?   �? - LLMClient        �?   �? - CommandFilter  �? �?
�? �? - EventClassifier  �?   �? - ContextManager   �?   �? - SafetyChecker  �? �?
�? �? - NoiseReducer     �?   �? - ActionPlanner    �?   �? - RateLimiter    �? �?
�? └─────────────────────�?   └─────────────────────�?   └───────────────────�? �?
�?          �?                         �?                         �?             �?
�?          �?                         �?                         �?             �?
�? ┌─────────────────────────────────────────────────────────────────────────�?  �?
�? �?                       Memory System (记忆系统)                          �?  �?
�? �? - ShortTermMemory: 会话级记�?(SQLite)                                  �?  �?
�? �? - LongTermMemory: 持久化记�?(ChromaDB 向量存储)                        �?  �?
�? �? - ItemContext: Item特定上下�?                                         �?  �?
�? └─────────────────────────────────────────────────────────────────────────�?  �?
└─────────────────────────────────────────────────────────────────────────────────�?
```

## 目录结构

```
backend/
├── app/
�?  ├── main.py              # 应用入口
�?  ├── models.py            # 数据库模�?
�?  ├── crud.py              # 数据库操�?
�?  ├── core/
�?  �?  ├── config.py        # 配置管理
�?  �?  ├── db.py            # 数据库连�?
�?  �?  └── security.py      # 安全工具
�?  ├── api/
�?  �?  ├── main.py          # API路由汇�?
�?  �?  ├── deps.py          # 依赖注入
�?  �?  └── routes/
�?  �?      ├── login.py     # 登录认证
�?  �?      ├── users.py     # 用户管理
�?  �?      ├── items.py     # Item管理
�?  �?      ├── item_handlers.py  # ItemHandler管理
�?  �?      ├── chat.py      # 对话接口
�?  �?      ├── knowledge.py # 知识�?
�?  �?      ├── skills.py    # 技�?
�?  �?      ├── memory.py    # 记忆
�?  �?      └── mcp.py       # MCP协议
�?  ├── services/
�?  �?  ├── agent/           # Agent核心
�?  �?  ├── robot/           # 机器人接�?
�?  �?  ├── socket_pool/     # 终端流分�?
�?  �?  ├── connection_pool/ # Daemon连接管理
�?  �?  ├── filters/         # 输入/输出过滤
�?  �?  └── protocol/        # 通信协议
�?  └── alembic/             # 数据库迁�?
├── skills/                  # Skill存储目录
├── tests/                   # 测试
└── pyproject.toml           # 项目配置
```

## 核心模块

### 1. Agent 系统

Agent 系统采用混合存储架构，结合短期记忆和长期记忆�?

#### Agent �?(`services/agent/agent.py`)

- 一�?ItemHandler 对应一�?Agent 实例
- 自动加载 ItemHandler 配置�?Skills
- 管理记忆（短�?+ 长期�?
- 处理对话请求

#### 会话管理 (`services/agent/session.py`)

- 单个 Item �?Agent 会话状�?
- 会话生命周期管理

#### 流式输出 (`services/agent/stream_manager.py`)

- 流式响应管理
- SSE 事件推�?

### 2. Memory 系统

```
┌─────────────────────────────────────────────────────────────────�?
�?                       Memory System                             �?
├─────────────────────────────────────────────────────────────────�?
�?                                                                 �?
�? ┌─────────────────────�?   ┌─────────────────────�?           �?
�? �?  Short-Term        �?   �?  Long-Term         �?           �?
�? �?  (SQLite)          �?   �?  (ChromaDB)        �?           �?
�? �?                    �?   �?                    �?           �?
�? �? - 会话历史          �?   �? - 向量嵌入          �?           �?
�? �? - 最近N条交�?      �?   �? - 语义检�?         �?           �?
�? �? - 临时上下�?       �?   �? - 持久化存�?       �?           �?
�? └─────────────────────�?   └─────────────────────�?           �?
�?                                                                 �?
└─────────────────────────────────────────────────────────────────�?
```

#### 记忆类型

| 类型 | 说明 |
|------|------|
| `fact` | 事实信息：用户名、路径、配置值等 |
| `preference` | 用户偏好：代码风格、工具选择�?|
| `task` | 任务相关：待办事项、计划等 |
| `error` | 错误记录：已知问题和解决方案 |
| `context` | 上下文：项目结构、依赖关系等 |

### 3. Skill 系统

#### 目录结构

```
backend/skills/
├── my_skill_1/
�?  ├── SKILL.md          # 核心定义文件（必须）
�?  ├── scripts/          # 脚本文件
�?  ├── templates/        # 模板文件
�?  └── examples/         # 示例文件
└── my_skill_2/
    └── SKILL.md
```

#### SKILL.md 格式

```markdown
---
skill_id: npm_fixer
name: NPM 修复�?
description: 自动修复 npm 依赖问题
category: devtools
trigger:
  type: auto
  patterns:
    - "npm ERR!"
action:
  type: llm
  prompt: "分析以下 npm 错误并提供修复方�?
safety:
  requires_approval: false
  risk_level: low
---
```

### 4. Knowledge 系统

知识库采�?RAG (检索增强生�? 架构�?

```
文件入库 �?增量索引 �?切块 �?向量�?�?相似度检�?�?注入 Prompt �?生成回答
```

#### 核心特点

- 知识文件统一进入共享知识�?
- 每个 ItemHandler 只保存启用的知识文件引用
- 回答问题时只检索当�?ItemHandler 启用的知识文�?

### 5. 过滤器系�?

#### 输入过滤层（终端输出 �?Agent�?

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

#### 输出过滤层（Agent �?终端执行�?

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
- 决定消息路由到哪�?Item
- 复用现有 Agent 对话链路

#### NoneBot2 Bridge 进程

- 连接 QQ 官方机器�?
- 接收 QQ 消息并转换为统一结构
- 调用 Backend dispatch 接口
- 发送回复到 QQ

## 数据模型

### 核心实体关系

```
User ──┬── owns ──�?Item (终端)
       �?
       └── owns ──�?ItemHandler (Agent配置)
                         �?
                         ├── binds ──�?Item (多对�?
                         �?
                         ├── enables ──�?KnowledgeFile
                         �?
                         └── loads ──�?Skill
```

### 主要模型

| 模型 | 说明 |
|------|------|
| `User` | 用户 |
| `Item` | 终端实例 |
| `ItemHandler` | Agent 配置 |
| `ItemHandlerItem` | ItemHandler-Item 关联 |
| `ItemHandlerUser` | ItemHandler-User 权限关联 |
| `Robot` | 机器人配�?|
| `RobotItem` | Robot-Item 绑定 |

## 凭证体系

Backend 是所有凭证的唯一签发中心�?

| 凭证类型 | 签发�?| 验证�?| 格式 | 有效�?|
|---------|--------|--------|------|--------|
| 用户 Token | Backend | Backend | JWT | 数小�?�?|
| 终端临时 Token | Backend | Daemon | 签名字符�?| 10分钟 |
| Daemon 认证 Token | Backend | Backend | 随机字符�?| 30分钟 |
| API Key | 预配�?| Daemon | 预配置字符串 | 永久 |

## 配置�?

| 配置�?| 默认�?| 说明 |
|--------|--------|------|
| `SQLITE_DATABASE_URL` | `sqlite:///./sql_app.db` | SQLite 数据库路�?|
| `CHROMA_PERSIST_DIR` | `./chroma_data` | ChromaDB 持久化目�?|
| `KNOWLEDGE_BASE_DIR` | `./knowledge` | 知识文件目录 |
| `ROBOT_PLUGIN_ENABLED` | `true` | 是否启动机器人插�?|
| `ROBOT_BRIDGE_EMBEDDED` | `false` | 是否内嵌 Bridge 进程 |
