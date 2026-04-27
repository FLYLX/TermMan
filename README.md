# TermMan - 终端管理系统

一个基于 FastAPI + React 的智能终端管理系统，支持 AI Agent 辅助操作、知识库管理、多终端进程监控。

## 项目结构

```
TermMan/
├── backend/           # FastAPI 后端服务
├── frontend/          # React 前端应用
├── daemon/            # 终端守护进程
└── hooks/             # 项目脚手架钩子
```

## 核心架构

```
┌─────────────┐      HTTP/WS       ┌─────────────┐      WS        ┌─────────────┐
│   Browser   │ ◄───────────────► │   Backend   │ ◄────────────► │   Daemon    │
└─────────────┘                    └─────────────┘                └─────────────┘
       │                                  │                              │
       │                                  │                              │
       │     ┌────────────────────────────┼────────────────────────────┐│
       │     │  通信分层隔离：             │                            ││
       │     │  • Browser ↔ Backend: HTTP │                            ││
       │     │  • Browser ↔ Daemon:  WS   │                            ││
       │     │  • Daemon ↔ Backend:  WS   │                            ││
       │     └────────────────────────────┼────────────────────────────┘│
```

### 三大组件

| 组件 | 技术栈 | 职责 |
|------|--------|------|
| **Backend** | FastAPI + SQLite + ChromaDB | 凭证签发中心、用户管理、Agent 运行时、知识库 |
| **Daemon** | Python + WebSocket | 终端进程管理、输出流分发、日志收集 |
| **Frontend** | React + Vite + Tailwind | 用户界面、终端 Web UI、管理面板 |

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+ / Bun
- uv (Python 包管理器)

### 启动后端

```bash
cd backend
uv sync
uv run fastapi dev app/main.py
```

后端服务运行在 http://localhost:8000

### 启动前端

```bash
cd frontend
bun install
bun run dev
```

前端服务运行在 http://localhost:5173

### 启动 Daemon

```bash
cd daemon
uv sync
uv run python -m src.main
```

Daemon 服务运行在 ws://localhost:9000

## 核心功能

### 1. 终端管理 (Item)

- 创建、启动、停止终端进程
- 实时输出流监控
- 日志收集与管理
- 输入/输出过滤器配置

### 2. AI Agent (ItemHandler)

- 每个 ItemHandler 对应一个 AI Agent 实例
- 支持 OpenAI、Anthropic 等多种 LLM
- 技能系统 (Skills) 扩展
- 长期记忆 (ChromaDB 向量存储)
- 短期记忆 (SQLite 会话历史)

### 3. 知识库 (Knowledge)

- 共享知识文件管理
- 自动切块与向量化
- 按需启用到 ItemHandler
- RAG 检索增强生成

### 4. 机器人接入 (Robot)

- QQ 官方机器人接入 (NoneBot2)
- 消息路由到指定终端
- 过滤后输出回推

## API 概览

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/login/access-token` | 登录获取 Token |
| POST | `/api/v1/login/test-token` | 验证 Token |
| POST | `/api/v1/users/` | 注册用户 |

### 终端管理 (Items)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/items/` | 列出终端 |
| POST | `/api/v1/items/` | 创建终端 |
| GET | `/api/v1/items/{id}` | 获取终端详情 |
| PUT | `/api/v1/items/{id}` | 更新终端配置 |
| DELETE | `/api/v1/items/{id}` | 删除终端 |
| POST | `/api/v1/items/{id}/start` | 启动终端 |
| POST | `/api/v1/items/{id}/stop` | 停止终端 |

### Agent 配置 (ItemHandlers)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/item-handlers/` | 列出 Agent 配置 |
| POST | `/api/v1/item-handlers/` | 创建 Agent 配置 |
| PUT | `/api/v1/item-handlers/{id}` | 更新 Agent 配置 |
| GET | `/api/v1/item-handlers/{id}/knowledge/files` | 获取知识文件列表 |

### 对话 (Chat)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/chat/{item_handler_id}` | 发送消息 (流式响应) |

### 知识库 (Knowledge)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/knowledge/files` | 列出知识文件 |
| POST | `/api/v1/knowledge/files` | 上传知识文件 |
| DELETE | `/api/v1/knowledge/files` | 删除知识文件 |

### 技能 (Skills)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/skills/` | 列出技能 |
| GET | `/api/v1/skills/{skill_id}` | 获取技能详情 |

### 记忆 (Memory)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/memory/{item_handler_id}` | 获取记忆列表 |
| DELETE | `/api/v1/memory/{item_handler_id}/{memory_id}` | 删除记忆 |

## 配置

主要环境变量 (`.env`):

```env
PROJECT_NAME=TermMan
ENVIRONMENT=local

SQLITE_DATABASE_URL=sqlite:///./sql_app.db
CHROMA_PERSIST_DIR=./chroma_data
KNOWLEDGE_BASE_DIR=./knowledge

ROBOT_PLUGIN_ENABLED=true
ROBOT_BRIDGE_EMBEDDED=false
```

## 文档

- [Backend 架构](backend/README.md)
- [Backend Services](backend/app/services/README.md)
- [Daemon 文档](daemon/README.md)
- [测试指南](backend/tests/TESTING_GUIDE.md)

## 技术栈

### Backend

- **FastAPI** - Web 框架
- **SQLModel** - ORM
- **ChromaDB** - 向量数据库
- **LiteLLM** - LLM 统一接口
- **sentence-transformers** - 文本嵌入

### Frontend

- **React** - UI 框架
- **TypeScript** - 类型安全
- **Vite** - 构建工具
- **Tailwind CSS** - 样式
- **TanStack Query** - 数据请求
- **xterm.js** - 终端模拟

### Daemon

- **Python** - 运行时
- **WebSocket** - 通信协议
- **asyncio** - 异步 IO
