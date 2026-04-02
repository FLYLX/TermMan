一、整体架构目标
设计并实现「浏览器 ↔ Backend ↔ Daemon」三层通信 + 认证架构，核心遵循：

    凭证唯一签发中心：Backend 负责所有 Token / 凭证的签发，Daemon 仅做凭证验证，不生成任何认证信息；
    通信分层隔离：
        浏览器 ↔ Backend：HTTP 处理登录 / 权限 / 凭证签发，WebSocket 可选；
        浏览器 ↔ Daemon：直连 WebSocket 实现终端实时交互，通过临时 Token 认证；
        Daemon ↔ Backend：HTTP 预认证 + WebSocket 主连接，承载管控指令和凭证校验；
    业务路由核心：所有 Item 相关通信以 item_uuid 为唯一标识，实现子进程与 Socket 通信的精准隔离，无交叉污染。

二、全链路核心流程（分阶段）
阶段 1：浏览器登录 Backend，获取用户级长期凭证

    浏览器向 Backend 发起 HTTP POST 请求（/api/user/login），携带账号密码；
    Backend 校验用户身份合法性，生成「用户 Token」（如 JWT，有效期数小时 / 天，关联用户权限）；
    Backend 将「用户 Token + 用户权限列表」返回给浏览器，浏览器本地缓存（如 localStorage）。

阶段 2：浏览器申请 Item 终端临时凭证

    浏览器向 Backend 发起 HTTP POST 请求（/api/item/terminal/token），携带「用户 Token + 目标 item_uuid」；
    Backend 双重校验：① 校验用户 Token 是否有效（未过期、签名合法）；② 校验该用户是否有操作此 item_uuid 的权限；
    校验通过后，Backend 签发「终端临时 Token」（核心特性：短期有效 < 10 分钟、绑定唯一 item_uuid、一次性使用）；
    Backend 将「终端临时 Token + Daemon 的 WebSocket 连接地址」返回给浏览器。

阶段 3：Daemon 向 Backend 完成预认证，建立主连接

    Daemon 启动后，向 Backend 发起 HTTP POST 请求（/api/daemon/auth），携带预配置的 API_KEY；
    Backend 校验 API_KEY 合法性（是否与已配置的 Daemon 信息匹配）；
    校验通过后，Backend 返回「Daemon 认证 Token」（短期有效）+ Backend 的 WebSocket 主连接地址；
    Daemon 携带「Daemon 认证 Token」连接 Backend 的 WebSocket 服务，Backend 二次校验通过后，标记该连接为「可信主连接」，全程无需重复认证；
    Daemon 与 Backend 维持主连接心跳（每 30s 发送心跳包），超时未收到则触发重连。

阶段 4：浏览器直连 Daemon，完成 Token 认证

    浏览器携带「终端临时 Token + item_uuid」，发起对 Daemon 的 WebSocket 连接请求（如 ws://daemon:24444/ws?token=临时Token&item_uuid=xxx）；
    Daemon 收到连接请求后，不直接解析 Token，而是通过「与 Backend 的可信主连接」发起校验请求（携带「终端临时 Token + item_uuid」）；
    Backend 校验该临时 Token：是否未过期、是否绑定该 item_uuid、是否为一次性未使用状态；
    Backend 将校验结果（合法 / 非法）返回给 Daemon：
        校验通过：Daemon 允许浏览器建立 WebSocket 连接，将浏览器加入该 item_uuid 对应的 Room，开启终端交互；
        校验失败：Daemon 直接断开浏览器连接，返回「认证失败」提示。

阶段 5：Item 子进程通信（路由 + 隔离）

    浏览器向 Daemon 发送指令：指令携带 item_uuid，Daemon 校验浏览器已认证后，将指令写入对应 item_uuid 的子进程 stdin（加线程锁避免并发冲突）；
    子进程输出转发：Daemon 异步监听子进程 stdout/stderr，封装为「item_uuid + 输出内容」的消息体，通过 WebSocket 推送给该 Room 内的浏览器；
    管控指令路由：Backend 通过与 Daemon 的主连接下发「启动 / 停止 Item」指令（携带 item_uuid），Daemon 执行后，将结果通过主连接上报给 Backend；
    状态同步：Daemon 定时将 Item 子进程状态（运行 / 停止 / 资源占用）通过主连接上报给 Backend，Backend 同步给浏览器。

三、核心技术要求
1. 凭证规则

    用户 Token：JWT 格式，包含用户 ID、权限等级、过期时间，服务端验签不存库；
    终端临时 Token：随机字符串（32 位），Backend 存储「Token → item_uuid → 用户 ID → 过期时间」映射，验证后标记为已使用；
    Daemon 认证 Token：随机字符串（64 位），Backend 存储「Token → Daemon API_KEY」映射，主连接建立后失效；
    API_KEY：Daemon 唯一标识，预配置在 Daemon 和 Backend 两端，不传输不泄露。

2. 异常处理

    浏览器 Token 过期：Daemon 断开连接，浏览器自动跳转至 Backend 重新申请临时 Token；
    Daemon 主连接断连：自动触发「HTTP 重新认证 + WebSocket 重连」，重连期间缓存 Item 输出，重连成功后补发；
    子进程退出：Daemon 清理管道 / Socket 资源，通过主连接上报 Backend，Backend 通知浏览器「Item 已停止」；
    Token 重复使用：Backend 检测到一次性 Token 重复校验，直接标记为非法，触发安全告警。

3. 通信隔离

    每个 item_uuid 对应独立子进程 + 独立 Room，不同 Item 的指令 / 输出完全隔离；
    Daemon 主连接仅承载管控 / 校验指令，不参与终端实时流传输，保证实时性；
    浏览器仅能访问已认证的 item_uuid 终端，无法跨 Item 操作。

四、核心数据结构（参考）
python
运行

# Backend 端凭证存储
token_store = {
    "terminal_temp_token": {
        "temp_token_123": {"item_uuid": "item_456", "user_id": "user_789", "expire_at": 1712345678, "used": False}
    },
    "daemon_auth_token": {
        "daemon_token_789": {"api_key": "daemon_api_123", "expire_at": 1712345678}
    }
}

# Daemon 端核心映射
daemon_state = {
    "api_key": "daemon_api_123",
    "ws_main_conn": None,  # 与 Backend 的主连接
    "item_map": {
        "item_456": {
            "process": <subprocess.Popen 对象>,
            "stdin_lock": threading.Lock(),
            "is_running": True,
            "subscribers": ["browser_sid_123"]  # 订阅该 Item 的浏览器 Socket ID
        }
    }
}

总结（核心关键点）

    认证闭环：Backend 是唯一凭证签发中心，浏览器用「临时 Token」连 Daemon，Daemon 用「API_KEY 预认证」连 Backend，全程无敏感凭证暴露；
    路由核心：item_uuid 贯穿所有通信环节，实现「主连接管控 + Room 隔离 + 子进程独立通信」；
    安全原则：短期临时 Token 替代长期凭证，一次性使用避免泄露风险，Daemon 仅做验证不存权限数据。



阶段 5：Item 子进程通信（新增 Backend 加入 Room 监听）

    Item 启动（Backend 加入 Room）：
        Backend 通过主连接下发「启动 Item」指令（item_uuid）；
        Daemon 启动 Item 子进程，创建该 item_uuid 对应的 Room；
        Daemon 主动通知 Backend：{item_uuid: "xxx", action: "room_create", room_ws_url: "ws://daemon:24445/room?token=xxx&item_uuid=xxx"}；
        Backend 携带「Daemon 认证 Token + item_uuid」连接该 Room 的 WebSocket 地址，Daemon 校验通过后，将 Backend 加入该 Item Room；
        标记 Backend 为「永久订阅者」（区别于浏览器的临时订阅者），即使无浏览器连接，Backend 也始终在 Room 内监听。
    Item 输出广播（Room 全域推送）：
        Daemon 监听 Item 子进程 stdout/stderr，封装为标准化消息体：
        json

        {
          "item_uuid": "xxx",
          "type": "stdout/stderr",
          "content": "输出内容",
          "timestamp": 1712345678
        }

        Daemon 将消息体广播至该 Item Room 内所有订阅者（Backend + 浏览器）；
        Backend 接收广播后，立即写入本地日志文件，完成持久化；
        浏览器接收广播后，实时渲染终端输出。
    Item 停止（Backend 退出 Room）：
        Backend 通过主连接下发「停止 Item」指令（item_uuid）；
        Daemon 终止 Item 子进程，向 Room 内所有订阅者推送「Item 已停止」消息；
        Daemon 移除 Room 内所有订阅者（Backend + 浏览器），销毁该 Item Room；
        Backend 接收停止消息后，写入退出日志，标记 Item 状态为「已停止」；
        Daemon 仅释放该 Item Room 相关资源，不影响 Daemon 主连接和其他 Item Room。

四、核心技术细节（Room 机制 + Backend 监听）
1. Room 设计规则（Daemon 侧）

    Room 标识：以 item_uuid 作为 Room 唯一 ID，一一对应；
    订阅者分类：
        永久订阅者：Backend（Item 启动即加入，停止才退出）；
        临时订阅者：浏览器（认证通过加入，断开 / Token 过期 / Item 停止退出）；
    广播机制：Daemon 对每个 Room 维护订阅者列表，Item 输出统一广播，无需区分订阅者类型；
    隔离性：不同 Room 的广播完全隔离，消息仅在所属 Room 内流转。

2. Backend 监听连接认证（安全保障）

    Backend 加入 Room 时，携带「Daemon 认证 Token + item_uuid」；
    Daemon 校验：
    ① Daemon 认证 Token 是否有效（未过期、与 Daemon 本地 API_KEY 绑定）；
    ② 该 item_uuid 是否属于当前 Daemon 管理；
    校验通过则允许加入 Room，否则拒绝连接。

3. 异常处理（针对 Backend 监听连接）

    Backend 监听连接断连：
    ① Daemon 立即通过主连接通知 Backend「监听连接断开」；
    ② Backend 自动重新申请加入该 Item Room；
    ③ Daemon 缓存断连期间的 Item 输出，Backen 重连成功后批量补发；
    无订阅者的 Room：即使无浏览器连接，Backend 作为永久订阅者始终存在，确保 Item 输出不丢失；
    Room 销毁：仅当 Item 停止时销毁 Room，避免无效资源占用。



# Daemon 端核心映射（新增 Room 管理）
daemon_state = {
    "api_key": "daemon_api_123",
    "ws_main_conn": None,  # 与 Backend 的主连接（管控）
    "item_map": {
        "item_456": {
            "process": <subprocess.Popen 对象>,
            "stdin_lock": threading.Lock(),
            "is_running": True,
            # Room 核心字段
            "room_id": "item_456",  # Room ID 与 item_uuid 一致
            "subscribers": {
                "permanent": [  # 永久订阅者（Backend）
                    {"conn": <WebSocketConnection 对象>, "type": "backend"}
                ],
                "temporary": [  # 临时订阅者（浏览器）
                    {"conn": <WebSocketConnection 对象>, "type": "browser", "sid": "browser_sid_123"}
                ]
            },
            "output_cache": [],  # 断连时的输出缓存
            "last_output_time": 1712345678
        }
    }
}

# Backend 端核心存储（新增 Room 监听连接）
backend_state = {
    "item_state": {
        "item_456": {
            "daemon_api_key": "daemon_api_123",
            "is_running": True,
            "room_listen_conn": <WebSocketConnection 对象>,  # 监听 Room 的连接
            "room_listen_status": "connected",  # connected/disconnected/reconnecting
            # 日志元信息（无修改）
            "log_base_path": "./backend_logs/item_456",
            "current_log_file": "./backend_logs/item_456/item_456_20260318_14.log",
            "log_download_url": "/api/item/456/log/download"
        }
    }
}

六、关键流程详解（Backend 加入 Room 监听）
1. Item 启动 + Backend 加入 Room 全流程
ItemSubprocessDaemonBackendItemSubprocessDaemonBackend下发启动指令（item_uuid）创建 Item Room（room_id=item_uuid）启动子进程推送 Room 连接信息（room_ws_url + 临时 Token）连接 Room WebSocket（携带 Token + item_uuid）校验 Token，将 Backend 加入 Room 永久订阅者列表确认加入 Room 成功标记 Room 监听状态为 connected
2. Item 输出广播 + Backend 写日志全流程
BrowserBackendBackendLogFileBrowser (Room订阅者)Backend (Room订阅者)DaemonItemSubprocessBrowserBackendBackendLogFileBrowser (Room订阅者)Backend (Room订阅者)DaemonItemSubprocess输出内容（stdout/stderr）封装标准化消息体广播消息（Room 内推送）广播消息（Room 内推送）写入日志（追加模式）更新日志元信息实时渲染终端输出
七、核心代码示例（Daemon 侧 Room 管理）
python
运行

import threading
from typing import Dict, List

# Room 订阅者类型
Subscriber = Dict[str, any]  # {"conn": WebSocket连接对象, "type": "backend/browser", "sid": 可选}

class DaemonRoomManager:
    def __init__(self):
        self.rooms: Dict[str, Dict[str, List[Subscriber]]] = {}  # {room_id: {"permanent": [], "temporary": []}}
        self.room_lock = threading.Lock()

    def create_room(self, room_id: str):
        """创建 Item Room"""
        with self.room_lock:
            if room_id not in self.rooms:
                self.rooms[room_id] = {"permanent": [], "temporary": []}

    def add_subscriber(self, room_id: str, subscriber: Subscriber):
        """添加订阅者到 Room"""
        with self.room_lock:
            if room_id not in self.rooms:
                raise ValueError(f"Room {room_id} 不存在")
            
            # 区分永久/临时订阅者
            if subscriber["type"] == "backend":
                self.rooms[room_id]["permanent"].append(subscriber)
            else:
                self.rooms[room_id]["temporary"].append(subscriber)

    def remove_subscriber(self, room_id: str, subscriber_conn: any, subscriber_type: str):
        """从 Room 移除订阅者"""
        with self.room_lock:
            if room_id not in self.rooms:
                return
            
            target_list = self.rooms[room_id]["permanent"] if subscriber_type == "backend" else self.rooms[room_id]["temporary"]
            self.rooms[room_id][subscriber_type] = [s for s in target_list if s["conn"] != subscriber_conn]

    def broadcast(self, room_id: str, message: dict):
        """向 Room 内所有订阅者广播消息"""
        with self.room_lock:
            if room_id not in self.rooms:
                return
            
            # 合并永久+临时订阅者
            all_subscribers = self.rooms[room_id]["permanent"] + self.rooms[room_id]["temporary"]
            for subscriber in all_subscribers:
                try:
                    # 推送消息（WebSocket 异步发送）
                    subscriber["conn"].send_json(message)
                except Exception as e:
                    # 连接异常则移除该订阅者
                    self.remove_subscriber(room_id, subscriber["conn"], subscriber["type"])

    def destroy_room(self, room_id: str):
        """销毁 Room（Item 停止时）"""
        with self.room_lock:
            if room_id in self.rooms:
                # 先关闭所有连接
                all_subscribers = self.rooms[room_id]["permanent"] + self.rooms[room_id]["temporary"]
                for subscriber in all_subscribers:
                    try:
                        subscriber["conn"].close()
                    except:
                        pass
                # 移除 Room
                del self.rooms[room_id]

总结

    核心调整：Backend 不再仅被动接收日志，而是作为「永久订阅者」加入 Item 专属 Room，通过 Room 广播机制实时监听 Item 输出，日志仍由 Backend 持久化存储；
    Room 机制价值：
        统一广播：Daemon 只需将 Item 输出广播至 Room，无需区分 Backend / 浏览器，简化转发逻辑；
        隔离性：每个 Item 对应独立 Room，Backend 仅监听授权的 Item Room，无交叉污染；
        可靠性：Backend 作为永久订阅者，确保即使无浏览器连接，Item 输出也能被监听并写入日志；
    资源释放：Item 停止时，Daemon 销毁对应 Room，移除所有订阅者（Backend + 浏览器），仅释放该 Item 相关资源，不影响整体服务。
