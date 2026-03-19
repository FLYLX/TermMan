# TermMan Backend - 终端管理系统后端

## 概述

TermMan Backend 是终端管理系统的核心后端服务，基于 FastAPI 构建。它作为「凭证唯一签发中心」，负责所有 Token/凭证的签发、用户权限管理、以及与 Daemon 的通信协调。

## 核心架构

### 三层通信架构

```
┌─────────────┐      HTTP/WS       ┌─────────────┐      WS        ┌─────────────┐
│   Browser   │ ◄───────────────► │   Backend   │ ◄────────────► │   Daemon    │
└─────────────┘                    └─────────────┘                └─────────────┘
       │                                  │                              │
       │                                  │                              │
       │     ┌────────────────────────────┼────────────────────────────┐│
       │     │                            │                            ││
       │     │  通信分层隔离：             │                            ││
       │     │  • Browser ↔ Backend: HTTP │                            ││
       │     │  • Browser ↔ Daemon:  WS   │                            ││
       │     │  • Daemon ↔ Backend:  WS   │                            ││
       │     │                            │                            ││
       │     └────────────────────────────┼────────────────────────────┘│
       │                                  │                              │
```

### 凭证唯一签发中心

Backend 是所有凭证的唯一签发中心，Daemon 仅做凭证验证：

| 凭证类型 | 签发方 | 验证方 | 格式 | 有效期 |
|---------|--------|--------|------|--------|
| 用户Token | Backend | Backend | JWT | 数小时/天 |
| 终端临时Token | Backend | Daemon | 签名字符串 | 10分钟 |
| Daemon认证Token | Backend | Backend | 随机字符串 | 30分钟 |
| API Key | 预配置 | Daemon | 预配置字符串 | 永久 |

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
│   │       └── ...
│   ├── services/
│   │   ├── auth_service.py       # 认证服务
│   │   ├── terminal_service.py   # 终端服务
│   │   ├── connection_handler.py # 连接处理
│   │   ├── daemon_initializer.py # Daemon初始化
│   │   ├── log_manager.py        # 日志管理
│   │   ├── connection_pool/      # Daemon连接池
│   │   │   ├── connection_manager.py
│   │   │   ├── daemon_connection.py
│   │   │   └── connection_models.py
│   │   ├── socket_pool/          # Item Socket池
│   │   │   ├── socket_manager.py
│   │   │   ├── item_socket.py
│   │   │   └── socket_models.py
│   │   └── protocol/             # 通信协议
│   │       ├── codec.py
│   │       └── events.py
│   └── alembic/             # 数据库迁移
├── tests/                   # 测试
├── scripts/                 # 脚本
└── pyproject.toml           # 项目配置
```

## 核心模块

### 1. AuthService (services/auth_service.py)

认证服务，负责所有凭证的签发和验证：

```python
from app.services import auth_service

# 生成终端临时Token（浏览器直连Daemon使用）
result = auth_service.generate_terminal_temp_token(
    item_uuid="xxx",
    user_id="xxx",
    expire_minutes=10
)
# 返回: {"token": "xxx", "item_uuid": "xxx", "expires_in": 600}

# 生成浏览器Access Token（签名格式）
access_token = auth_service.generate_access_token(
    item_uuid="xxx",
    user_id="xxx",
    secret_key=settings.SECRET_KEY,
    expire_seconds=600
)
# 返回: "item_uuid:user_uuid:timestamp:expires_in:signature"

# 验证Access Token
result = auth_service.verify_access_token(
    token=access_token,
    item_uuid="xxx",
    secret_key=settings.SECRET_KEY
)
# 返回: {"success": True, "user_id": "xxx", "item_uuid": "xxx"}
```

### 2. ConnectionManager (services/connection_pool/)

Daemon连接池管理，维护一张表：

```
Daemon连接池表: [daemon ip:port:apikey] -> DaemonConnection
```

```python
from app.services import connection_manager, DaemonConfig

# 创建连接
config = DaemonConfig(ip="localhost", port=9000, api_key="xxx")
connection = connection_manager.get_or_create_connection(config)

# 检查连接状态
if connection.is_connected():
    # 发送终端启动请求
    result = await connection.terminal_start(user_uuid, item_uuid, workdir, command)
```

### 3. SocketManager (services/socket_pool/)

Item Socket池管理，维护两张表：

```
1. Item-Token映射表: {daemon_id: {item_uuid: token}}
2. Item-连接映射表: [item_uuid -> {sid -> {user_uuid, ip}}]
```

```python
from app.services import socket_manager

# 添加Token
socket_manager.add_token(daemon_id, item_uuid, token)

# 获取Token
token = socket_manager.get_token(daemon_id, item_uuid)

# 获取连接表
tables = socket_manager.get_connection_tables()
```

### 4. TerminalService (services/terminal_service.py)

终端核心业务逻辑：

```python
from app.services import TerminalService

terminal_service = TerminalService(connection_manager, socket_manager, connection_handler)

# 启动终端
result = terminal_service.start_terminal(item_uuid, user_uuid, daemon_config)

# 停止终端
result = terminal_service.stop_terminal(daemon_id, item_uuid)
```

## API端点

### 认证相关

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/v1/login/access-token` | 登录获取Token |
| POST | `/api/v1/login/test-token` | 测试Token有效性 |
| POST | `/api/v1/password-recovery/{email}` | 密码恢复 |

### 用户管理

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/api/v1/users/` | 获取用户列表 |
| POST | `/api/v1/users/` | 创建用户 |
| GET | `/api/v1/users/me` | 获取当前用户 |
| PATCH | `/api/v1/users/me` | 更新当前用户 |

### Item管理

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/api/v1/items/` | 获取Item列表 |
| POST | `/api/v1/items/` | 创建Item |
| GET | `/api/v1/items/{id}` | 获取Item详情 |
| PUT | `/api/v1/items/{id}` | 更新Item |
| DELETE | `/api/v1/items/{id}` | 删除Item |
| POST | `/api/v1/items/{id}/start` | 启动Item |
| POST | `/api/v1/items/{id}/stop` | 停止Item |
| POST | `/api/v1/items/{id}/restart` | 重启Item |
| GET | `/api/v1/items/{id}/terminal-token` | **获取终端临时Token** |
| POST | `/api/v1/items/{id}/verify-terminal-token` | **验证终端Token** |
| POST | `/api/v1/items/{id}/disconnect-user` | 断开用户连接 |

## 全链路认证流程

### 阶段1：浏览器登录Backend

```
Browser ─── POST /login/access-token ───► Backend
       │                                     │
       │ ◄─────── JWT Token ──────────────── │
```

### 阶段2：浏览器申请终端临时Token

```
Browser ─── GET /items/{id}/terminal-token ───► Backend
       │         (携带JWT Token)                   │
       │                                            │
       │     1. 验证用户Token                        │
       │     2. 验证用户权限                         │
       │     3. 签发临时Token                        │
       │                                            │
       │ ◄──── access_token + daemon_url ────────── │
```

### 阶段3：Daemon预认证（启动时）

```
Daemon ─── WS连接 ───► Backend
       │                   │
       │ ─── auth事件 ────► │
       │    {api_key}       │
       │                   │
       │ ◄── auth响应 ──── │
       │    {success}       │
```

### 阶段4：浏览器直连Daemon

```
Browser ─── WS连接 ───► Daemon
       │                   │
       │ ─ terminal/connect │
       │   {access_token,   │
       │    item_uuid}      │
       │                   │
       │ ◄─ terminal_connected │
```

## 配置

### 环境变量

```env
# 项目配置
PROJECT_NAME=TermMan
API_V1_STR=/api/v1
SECRET_KEY=your_secret_key_here
ACCESS_TOKEN_EXPIRE_MINUTES=11520  # 8天

# 数据库
SQLITE_DATABASE_URL=sqlite:///./sql_app.db

# CORS
FRONTEND_HOST=http://localhost:5173
BACKEND_CORS_ORIGINS=["http://localhost:5173"]

# 超级用户
FIRST_SUPERUSER=admin@example.com
FIRST_SUPERUSER_PASSWORD=admin123

# 邮件（可选）
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=user@example.com
SMTP_PASSWORD=password
EMAILS_FROM_EMAIL=noreply@example.com
```

### 重要：SECRET_KEY配置

`SECRET_KEY` 必须与 Daemon 的 `SECRET_KEY` 保持一致，否则浏览器 Access Token 验证会失败。

## 运行

### 本地开发

```bash
# 安装依赖
uv sync

# 激活虚拟环境
source .venv/bin/activate

# 运行数据库迁移
alembic upgrade head

# 启动服务
fastapi dev app/main.py
```

### Docker

```bash
# 构建
docker build -t termman-backend .

# 运行
docker run -d \
  -p 8000:8000 \
  -e SECRET_KEY=your_secret_key \
  -e FIRST_SUPERUSER=admin@example.com \
  -e FIRST_SUPERUSER_PASSWORD=admin123 \
  termman-backend
```

### Docker Compose

```bash
docker compose up -d
```

## 测试

```bash
# 运行所有测试
bash ./scripts/test.sh

# 运行特定测试
pytest tests/api/routes/test_items.py -v

# 测试覆盖率
pytest --cov=app tests/
```

## 数据库迁移

```bash
# 创建迁移
alembic revision --autogenerate -m "描述"

# 执行迁移
alembic upgrade head

# 回滚
alembic downgrade -1
```

## 安全注意事项

1. **SECRET_KEY 保护**：生产环境必须使用强随机密钥
2. **CORS 配置**：生产环境应限制允许的源
3. **Token 有效期**：终端临时 Token 有效期仅 10 分钟
4. **API Key 管理**：定期轮换 Daemon 的 API Key
5. **HTTPS**：生产环境必须使用 HTTPS

## 日志

应用日志通过 Python logging 模块输出，可通过环境变量配置日志级别。

## 监控

- 健康检查：`GET /api/v1/utils/health-check`
- OpenAPI 文档：`GET /docs`
- ReDoc 文档：`GET /redoc`
