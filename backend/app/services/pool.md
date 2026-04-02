一、核心原则（连接池设计前提）

    Backend 连接池：仅管理「主动向外的连接」（如监听 Daemon Room 的 WebSocket 连接），被动接收的连接（浏览器 HTTP/WebSocket、Daemon 主连接）无需池化（由 Web 框架自动管理）；
    Daemon 连接池：管理「Backend 主连接 + 浏览器终端连接 + Backend Room 监听连接」，核心是「按 item_uuid 隔离 + 状态追踪 + 重连机制」；
    所有连接池表都加 threading.Lock 保证线程安全，字段聚焦「连接实例、状态、元信息、重连参数」。

二、Backend 侧内存连接池表（核心：Room 监听连接池）
Backend 作为管控中心，仅需池化「监听 Daemon Item Room 的 WebSocket 连接」（永久订阅者连接），其他连接由 FastAPI/Starlette 自动管理，无需额外池化。
1. 核心连接池表：room_listen_conn_pool
python
运行

import threading
from datetime import datetime
from typing import Dict, List, Optional, Any

# Backend 全局连接池（单例 + 线程锁）
class BackendConnPool:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                # 核心：Room监听连接池（Backend → Daemon Room）
                cls._instance.room_listen_conn_pool: Dict[str, dict] = {}
                # 辅助：Daemon主连接状态追踪（Daemon → Backend）
                cls._instance.daemon_main_conn_state: Dict[str, dict] = {}
            return cls._instance

# 初始化全局连接池
backend_conn_pool = BackendConnPool()

# ====================== 连接池表结构详解 ======================
# 1. room_listen_conn_pool（核心）：Key=item_uuid，Value=连接详情
backend_conn_pool.room_listen_conn_pool = {
    "item_456": {
        # 基础信息
        "conn": Optional[Any],  # WebSocket连接实例（如websockets.client.Connection）
        "conn_id": "listen_conn_123",  # 连接唯一标识
        "daemon_api_key": "daemon_api_123",  # 所属Daemon
        "room_id": "item_456",  # 对应Room ID
        # 状态信息
        "status": "connected",  # connected/disconnected/reconnecting
        "last_heartbeat": datetime.now().timestamp(),  # 最后心跳时间
        "create_time": datetime.now().timestamp(),  # 连接创建时间
        # 重连配置
        "reconnect_times": 0,  # 已重连次数
        "max_reconnect_times": 5,  # 最大重连次数
        "reconnect_interval": 3,  # 重连间隔（秒）
        # 缓存信息
        "cache_output": [],  # 断连期间的Item输出缓存
        "cache_max_size": 1000  # 最大缓存条数（防止内存溢出）
    }
}

# 2. daemon_main_conn_state（辅助）：Key=daemon_api_key，Value=主连接状态
backend_conn_pool.daemon_main_conn_state = {
    "daemon_api_123": {
        "conn_status": "connected",  # Daemon主连接状态
        "last_heartbeat": datetime.now().timestamp(),  # 最后心跳时间
        "ws_main_url": "ws://daemon:9000/main",  # Daemon主连接地址
        "last_reconnect_time": None  # 最后重连时间
    }
}

2. Backend 连接池核心字段说明
表格
字段	作用	取值示例
conn	实际的 WebSocket 连接实例（核心）	websockets.client.Connection
status	连接状态（驱动重连逻辑）	connected/disconnected/reconnecting
reconnect_times	已重连次数（防止无限重连）	0/3/5
cache_output	断连期间的 Item 输出缓存（重连后补发）	[{"item_uuid":"item_456", "content":"xxx"}, ...]
daemon_main_conn_state	辅助追踪 Daemon 主连接状态（主连接断连则暂停 Room 重连）	-
三、Daemon 侧内存连接池表（核心：多维度连接池 + 隔离）
Daemon 作为连接中转核心，需要池化「3 类连接」，且所有连接池都按 item_uuid 隔离，保证通信不交叉。
1. 核心连接池表（单例 + 线程锁）
python
运行

import threading
from datetime import datetime
from typing import Dict, List, Optional, Any

# Daemon 全局连接池（单例 + 线程锁）
class DaemonConnPool:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                # 1. Backend主连接池（Daemon ↔ Backend 管控连接）
                cls._instance.backend_main_conn_pool: Dict[str, dict] = {}
                # 2. 浏览器终端连接池（Daemon ↔ 浏览器 终端交互）
                cls._instance.browser_terminal_conn_pool: Dict[str, List[dict]] = {}
                # 3. Backend Room监听连接池（Daemon ↔ Backend 日志监听）
                cls._instance.backend_room_listen_conn_pool: Dict[str, dict] = {}
            return cls._instance

# 初始化全局连接池
daemon_conn_pool = DaemonConnPool()

# ====================== 连接池表结构详解 ======================
# 1. backend_main_conn_pool（核心）：Key=daemon_api_key（唯一），Value=主连接详情
daemon_conn_pool.backend_main_conn_pool = {
    "daemon_api_123": {
        "conn": Optional[Any],  # WebSocket主连接实例
        "conn_id": "main_conn_789",
        "auth_token": "daemon_auth_token_xyz",  # 认证Token
        "status": "connected",  # connected/disconnected/reconnecting
        "last_heartbeat": datetime.now().timestamp(),
        "heartbeat_interval": 30,  # 心跳间隔（秒）
        "reconnect_times": 0,
        "max_reconnect_times": 10
    }
}

# 2. browser_terminal_conn_pool（隔离核心）：Key=item_uuid，Value=该Item下的浏览器连接列表
daemon_conn_pool.browser_terminal_conn_pool = {
    "item_456": [
        {
            "conn": Optional[Any],  # 浏览器WebSocket连接实例
            "conn_id": "browser_conn_abc",
            "sid": "browser_sid_123",  # 浏览器会话ID
            "temp_token": "terminal_temp_token_123",  # 认证用临时Token
            "auth_status": "authenticated",  # unauthenticated/authenticated/expired
            "join_time": datetime.now().timestamp(),
            "last_active_time": datetime.now().timestamp()
        }
    ]
}

# 3. backend_room_listen_conn_pool（日志监听）：Key=item_uuid，Value=Backend监听连接详情
daemon_conn_pool.backend_room_listen_conn_pool = {
    "item_456": {
        "conn": Optional[Any],  # Backend监听Room的WebSocket连接
        "conn_id": "listen_conn_456",
        "auth_token": "daemon_auth_token_xyz",  # 认证Token
        "status": "connected",
        "is_permanent": True,  # 永久订阅者标识
        "last_heartbeat": datetime.now().timestamp(),
        "reconnect_notify": False  # 是否已通知Backend重连
    }
}

2. Daemon 连接池核心字段说明
表格
连接池类型	核心隔离维度	关键字段作用
backend_main_conn_pool	按 Daemon API_KEY（唯一）	heartbeat_interval 驱动心跳，reconnect_times 限制重连次数，保证主连接稳定性
browser_terminal_conn_pool	按 item_uuid	auth_status 管控认证状态，last_active_time 清理闲置连接，sid 唯一标识浏览器
backend_room_listen_conn_pool	按 item_uuid	is_permanent 标记永久订阅者，reconnect_notify 触发 Backend 重连通知，保证日志不丢失
四、连接池表使用核心规则
1. Backend 侧

    仅池化「主动连接 Daemon Room 的 WebSocket 连接」，其他连接（如浏览器 HTTP/WebSocket、Daemon 主连接）由 FastAPI 自动管理；
    连接状态变更（如 disconnected）触发重连逻辑，cache_output 缓存断连期间的 Item 输出，重连后批量补发；
    定时清理「超过最大重连次数」的无效连接。

2. Daemon 侧

    主连接池：单例（一个 Daemon 仅一个主连接），心跳超时触发重连，重连期间缓存管控指令；
    浏览器连接池：按 item_uuid 隔离，认证失败 / Token 过期 / 闲置超时（如 5 分钟）直接断开并移除；
    Room 监听连接池：按 item_uuid 隔离，连接断连立即通知 Backend，缓存输出直到重连成功。

总结（核心连接池表清单）
表格
节点	核心连接池表	隔离维度	核心作用
Backend	room_listen_conn_pool	item_uuid	池化 Room 监听连接，保证日志不丢失
Backend	daemon_main_conn_state	daemon_api_key	辅助追踪 Daemon 主连接状态
Daemon	backend_main_conn_pool	daemon_api_key	池化 Backend 主连接，承载管控指令
Daemon	browser_terminal_conn_pool	item_uuid	隔离浏览器终端连接，保证通信不交叉
Daemon	backend_room_listen_conn_pool	item_uuid	池化 Backend 监听连接，保证日志广播
这套连接池表结构完全适配你的「三层通信 + Room 隔离 + 认证闭环」需求，纯内存实现、线程安全，可直接嵌入到你之前的内存表中，无需依赖任何数据库 / 第三方库