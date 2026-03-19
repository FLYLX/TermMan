# TermMan Daemon - 终端管理守护进程

## 概述

TermMan Daemon 是一个轻量级的终端管理守护进程，负责管理终端子进程的生命周期、处理 WebSocket 连接、以及与 Backend 的通信。它采用「凭证唯一签发中心」架构，Backend 负责所有 Token/凭证的签发，Daemon 仅做凭证验证。

## 核心架构

### 三层通信架构

```
┌─────────────┐      HTTP/WS       ┌─────────────┐      WS        ┌─────────────┐
│   Browser   │ ◄───────────────► │   Backend   │ ◄────────────► │   Daemon    │
└─────────────┘                    └─────────────┘                └─────────────┘
       │                                  │                              │
       │ 1. 登录获取用户Token              │                              │
       │ ──────────────────────────────► │                              │
       │                                  │                              │
       │ 2. 申请终端临时Token             │                              │
       │ ──────────────────────────────► │                              │
       │                                  │                              │
       │ ◄────────────────────────────── │                              │
       │    返回: access_token + daemon_url                             │
       │                                  │                              │
       │ 3. 直连Daemon (携带access_token) │                              │
       │ ────────────────────────────────────────────────────────────► │
       │                                  │                              │
       │ ◄──────────────────────────────────────────────────────────── │
       │    验证通过，建立WebSocket连接                                   │
       │                                  │                              │
```

### Room 机制（按 UPDATE.MD 规范）

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              Item Room (item_uuid)                            │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────┐                    ┌─────────────────────┐         │
│  │  Permanent (Backend) │                    │ Temporary (Browser) │         │
│  │                     │                    │                     │         │
│  │  • 监听输出写日志     │                    │  • 实时渲染终端      │         │
│  │  • 永久订阅者        │                    │  • 临时订阅者        │         │
│  │  • Item启动时加入    │                    │  • 用户连接时加入    │         │
│  │  • Item停止时移除    │                    │  • 断开时移除        │         │
│  └─────────────────────┘                    └─────────────────────┘         │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                        Terminal Output                               │    │
│  │                                                                      │    │
│  │   Item Subprocess ─── stdout/stderr ───► Broadcast to Room ───► All │    │
│  │                                                                      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Room 机制核心价值**：
1. **统一广播**：Daemon 只需将 Item 输出广播至 Room，无需区分 Backend / 浏览器
2. **隔离性**：每个 Item 对应独立 Room，无交叉污染
3. **可靠性**：Backend 作为永久订阅者，确保即使无浏览器连接，Item 输出也能被监听并写入日志

## 认证体系

### 凭证类型

| 凭证类型 | 格式 | 用途 | 有效期 |
|---------|------|------|--------|
| 用户Token | JWT | 浏览器登录Backend后的会话凭证 | 数小时/天 |
| 终端临时Token | item_uuid:user_uuid:timestamp:expires_in:signature | 浏览器直连Daemon | 10分钟 |
| API Key | 预配置字符串 | Backend连接Daemon认证 | 永久 |
| Daemon Token | UUID | Daemon内部终端会话标识 | 1天 |

### 认证流程

#### 1. Backend连接Daemon（预认证）

```
Backend ──── WS连接 ────► Daemon
       │                    │
       │ ─── auth事件 ────► │
       │    {api_key}       │
       │                    │
       │ ◄── auth响应 ───── │
       │    {success}       │
```

#### 2. 浏览器直连Daemon

```
Browser ──── WS连接 ────► Daemon
       │                    │
       │ ─ terminal/connect │
       │   {access_token,   │
       │    item_uuid}      │
       │                    │
       │ ◄─ terminal_connected │
       │    或 auth_error    │
```

## 目录结构

```
daemon/
├── src/
│   ├── main.py              # 应用入口
│   ├── api/
│   │   ├── http_routes.py   # HTTP API路由
│   │   └── socket_routes.py # WebSocket事件处理
│   ├── core/
│   │   ├── config.py        # 配置管理
│   │   ├── memory_store.py  # 内存存储（TTL支持）
│   │   ├── file_storage.py  # 文件存储
│   │   └── global_instances.py # 全局实例
│   ├── service/
│   │   ├── auth_service.py  # 认证服务
│   │   ├── socket_service.py # Socket连接管理
│   │   ├── terminal_manager.py # 终端进程管理
│   │   └── room_manager.py  # Room管理器（新增）
│   └── utils/
│       └── logger.py        # 日志工具
├── log/                     # 日志目录
├── .env                     # 环境配置
└── Dockerfile               # Docker构建文件
```

## 核心模块

### 1. DaemonRoomManager (room_manager.py) - 新增

Room 管理器，按 UPDATE.MD 规范实现：
- 每个 item_uuid 对应一个 Room
- 区分 permanent（Backend）和 temporary（Browser）订阅者
- 支持输出缓存，断连重连时可恢复
- Item 停止时销毁 Room

```python
from service.room_manager import room_manager, Subscriber

# 创建 Room
room_manager.create_room(item_uuid)

# 添加订阅者
subscriber = Subscriber(sid, "backend", user_uuid, ip)
room_manager.add_subscriber(item_uuid, subscriber)

# 获取 Room 信息
room_info = room_manager.get_room_info(item_uuid)
# 返回: {"room_id": "xxx", "permanent_count": 1, "temporary_count": 2, ...}

# 销毁 Room（Item 停止时）
sids = room_manager.destroy_room(item_uuid)
```

### 2. AuthService (auth_service.py)

认证服务，负责：
- API Key 验证（Backend连接认证）
- 终端Token管理（Daemon内部使用）
- 浏览器Access Token验证（与Backend共享密钥）

```python
from service.auth_service import auth_service

# 验证API Key
is_valid = auth_service.validate_api_key(api_key)

# 验证浏览器Access Token
result = auth_service.verify_access_token(access_token, item_uuid)
# 返回: {"success": True, "user_uuid": "xxx", "item_uuid": "xxx"}
```

### 3. SocketService (socket_service.py)

Socket连接池管理，使用Room机制实现消息隔离：
- Backend主连接表: `[sid -> {backend_id, ip}]`
- Item-Token映射表: `{item_uuid: token}`
- SID映射表: `[sid -> {item_uuid, user_uuid, ip, type}]`

```python
# 加入 Room（区分订阅者类型）
await socket_service.join_item_room(sid, item_uuid, "backend", user_uuid)
await socket_service.join_item_room(sid, item_uuid, "browser", user_uuid)

# 广播到终端Room
await socket_service.broadcast_to_terminal(item_uuid, "stream", data)

# 关闭终端所有连接（销毁 Room）
await socket_service.close_terminal_connections(item_uuid)
```

### 4. TerminalManager (terminal_manager.py)

终端进程管理，负责：
- 创建/启动/停止终端进程
- 管理进程stdin/stdout/stderr
- 输出广播到WebSocket

```python
from service.terminal_manager import terminal_manager

# 创建并启动终端
terminal_manager.create_terminal(user_uuid, token, workdir, command, item_uuid)
terminal_manager.start_terminal(item_uuid)

# 写入命令
terminal.write("ls -la\n")

# 停止终端
terminal_manager.stop_terminal(item_uuid)
```

## WebSocket事件

### Backend -> Daemon

| 事件 | 描述 | 参数 |
|------|------|------|
| `auth` | Backend认证 | `{backend_id}` |
| `terminal/start` | 启动终端 | `{user_uuid, item_uuid, working_directory?, command?}` |
| `terminal/stop` | 停止终端 | `{item_uuid}` |
| `terminal/restart` | 重启终端 | `{item_uuid, user_uuid?, working_directory?, command?}` |
| `terminal/status` | 查询状态 | `{item_uuid}` |
| `terminal/list` | 终端列表 | `{}` |
| `connections/get` | 获取Item连接 | `{item_uuid}` |
| `connections/get_all` | 获取所有连接 | `{}` |
| `connections/disconnect` | 断开连接 | `{item_uuid, user_uuid?}` |

### Browser -> Daemon

| 事件 | 描述 | 参数 |
|------|------|------|
| `terminal/connect` | 连接终端 | `{item_uuid, access_token, subscriber_type?}` 或 `{item_uuid, token, subscriber_type?}` |
| `terminal/write` | 写入命令 | `{command}` |

### Daemon -> Client

| 事件 | 描述 | 数据 |
|------|------|------|
| `stream` | 终端输出 | `{stdout?}` 或 `{stderr?}` |
| `terminal_connected` | 连接成功 | `{item_uuid, subscriber_type, room_info}` |
| `auth_error` | 认证失败 | `{message}` |
| `connection_update` | 连接池更新 | `{type, connections, rooms}` |

## 关键流程

### Item 启动 + Backend 加入 Room

```
Backend                     Daemon                      Item Subprocess
   │                           │                              │
   │ ─── terminal/start ─────► │                              │
   │     {item_uuid}           │                              │
   │                           │                              │
   │                           │ ─── 创建 Item Room ────────► │
   │                           │     (room_id=item_uuid)      │
   │                           │                              │
   │                           │ ─── 启动子进程 ────────────► │
   │                           │                              │
   │ ◄── terminal/start ────── │                              │
   │     {token, success}      │                              │
   │                           │                              │
   │ ─── terminal/connect ───► │                              │
   │     {token, item_uuid,    │                              │
   │      subscriber_type=     │                              │
   │      "backend"}           │                              │
   │                           │                              │
   │                           │ ─── 加入 Room ────────────►  │
   │                           │     (permanent订阅者)        │
   │                           │                              │
   │ ◄── terminal_connected ── │                              │
   │     {room_info}           │                              │
   │                           │                              │
   │ ◄─────────────────────── stream ──────────────────────► │
   │     {stdout/stderr}       │     (广播到Room)             │
   │                           │                              │
   │ ─── 写入日志 ──────────── │                              │
   │                           │                              │
```

### Item 停止 + 销毁 Room

```
Backend                     Daemon                      Item Subprocess
   │                           │                              │
   │ ─── terminal/stop ──────► │                              │
   │     {item_uuid}           │                              │
   │                           │                              │
   │                           │ ─── 停止子进程 ────────────► │
   │                           │                              │
   │                           │ ─── 销毁 Room ────────────► │
   │                           │     (移除所有订阅者)         │
   │                           │                              │
   │ ◄── terminal/stop ─────── │                              │
   │     {success}             │                              │
   │                           │                              │
   │ ◄── WebSocket断开 ─────── │                              │
   │     (Backend订阅者被移除) │                              │
   │                           │                              │
```

## 配置

### 环境变量 (.env)

```env
# 服务配置
PORT=9000
HOST=0.0.0.0

# 认证配置（必须与Backend一致）
API_KEY=your_api_key_here
SECRET_KEY=your_secret_key_here

# 目录配置
WORKDIR=./src/workdir
LOG_DIR=./log
DATA_DIR=./src/data

# 终端配置
TERMINAL_SHELL=cmd.exe  # Windows使用cmd.exe，Linux使用bash
TERMINAL_ENCODING=utf-8
TERMINAL_BUFFER_SIZE=8192
```

### 重要：SECRET_KEY配置

`SECRET_KEY` 必须与 Backend 的 `SECRET_KEY` 保持一致，否则浏览器 Access Token 验证会失败。

```env
# Backend (.env)
SECRET_KEY=termman_secret_key_for_access_token_2024

# Daemon (.env)
SECRET_KEY=termman_secret_key_for_access_token_2024
```

## 运行

### 本地开发

```bash
# 安装依赖
pip install -r requirements.txt

# 运行
python src/main.py
```

### Docker

```bash
# 构建
docker build -t termman-daemon .

# 运行
docker run -d \
  -p 9000:9000 \
  -e API_KEY=your_api_key \
  -e SECRET_KEY=your_secret_key \
  -v ./log:/app/log \
  termman-daemon
```

## 安全注意事项

1. **API Key 保护**：API Key 不应通过网络传输，仅在 Backend 和 Daemon 启动时预配置
2. **SECRET_KEY 同步**：确保 Backend 和 Daemon 的 SECRET_KEY 一致
3. **Token 有效期**：浏览器 Access Token 有效期为 10 分钟，短期有效降低泄露风险
4. **IP 白名单**：生产环境建议配置 IP 白名单限制 Backend 连接

## 日志

日志文件位于 `./log/` 目录：
- `daemon.log` - Daemon主日志
- `{user_uuid}/{item_uuid}.log` - 终端输出日志

## 健康检查

```bash
# HTTP健康检查
curl http://localhost:9000/api/health

# 状态检查
curl http://localhost:9000/api/status
```
