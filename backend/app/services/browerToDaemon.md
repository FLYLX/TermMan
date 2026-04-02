一、前置状态

    用户已完成账号密码登录，Browser（浏览器）本地缓存有 Backend 签发的用户长期 Token（如 JWT，有效期数小时 / 天，用于验证用户身份）；
    Backend 与 Daemon 已建立「可信 WebSocket 主连接」（Daemon 先通过 API_KEY 完成 Backend 预认证，主连接持续在线）；
    目标 Item（实例）已在 Daemon 上启动，状态为运行中。

二、完整流程（分 8 步）
步骤 1：用户触发终端连接操作
用户在浏览器页面点击「打开终端」按钮，前端（JS）捕获该操作，确认要连接的目标 Item 的 item_uuid（如从页面 DOM / 状态中读取）。
步骤 2：浏览器向 Backend 发起临时 Token 请求

    请求构造：
        接口地址：POST /api/terminal/get-temp-token（Backend 暴露的专属接口）；
        请求头：携带用户长期 Token（身份校验），示例：
        plaintext

        Authorization: Bearer {用户长期Token}
        Content-Type: application/json

        请求体：携带目标 Item 标识，示例：
        json

        {
          "item_uuid": "item_123456789" // 要连接的实例ID
        }

    核心目的：告知 Backend「当前登录用户需要访问 item_uuid 的终端，请签发一次性临时 Token」。

步骤 3：Backend 校验并签发终端临时 Token

    第一层校验：用户身份合法性Backend 解析请求头中的「用户长期 Token」，校验：
        Token 是否过期（对比签发时间 + 有效期）；
        Token 签名是否合法（防止篡改）；
        用户是否为有效状态（未被封禁、未注销）。
        ✅ 校验失败：返回 401 错误，浏览器提示「登录已过期，请重新登录」，流程终止。
    第二层校验：用户 Item 操作权限Backend 基于用户 ID 和 item_uuid，查询权限表校验：
        该用户是否为 Item 所属用户 / 管理员；
        用户是否有「终端访问」权限（细粒度权限控制）。
        ✅ 校验失败：返回 403 错误，浏览器提示「无权限访问该实例终端」，流程终止。
    第三层：生成并存储临时 Token
        生成规则：32 位随机字符串（或加密字符串），保证唯一性；
        绑定属性：与 item_uuid 强绑定、标记为「一次性使用」、设置短期有效期（如 5 分钟）；
        存储：将 Token 信息存入 Backend 缓存（如 Redis），示例：
        json

        {
          "temp_token": "abc123def456ghi789", // 终端临时Token
          "item_uuid": "item_123456789",
          "user_id": "user_987654321",
          "expire_at": 1712345678, // 过期时间戳（5分钟后）
          "used": false // 未使用标记
        }

    返回响应：Backend 向浏览器返回成功响应，包含核心信息：
    json

    {
      "code": 200,
      "msg": "临时Token获取成功",
      "data": {
        "temp_token": "abc123def456ghi789", // 终端临时Token
        "ws_url": "ws://daemon:24444/ws", // Daemon的WebSocket地址
        "item_uuid": "item_123456789",
        "expire_seconds": 300 // Token有效期（秒）
      }
    }

步骤 4：浏览器拼接 Daemon 连接地址
浏览器前端解析 Backend 响应，拼接 WebSocket 连接 URL，将临时 Token 和 item_uuid 作为参数携带：
plaintext

ws://daemon:24444/ws?token=abc123def456ghi789&item_uuid=item_123456789

步骤 5：浏览器向 Daemon 发起 WebSocket 连接请求
浏览器通过 new WebSocket(拼接后的URL) 发起连接，Daemon 监听到连接请求后，先暂存连接（不立即建立），进入 Token 校验环节。
步骤 6：Daemon 向 Backend 校验临时 Token

    Daemon 从连接参数中提取 temp_token 和 item_uuid；
    通过「与 Backend 的可信主连接」（WebSocket）向 Backend 发送校验请求，示例：
    json

    {
      "type": "terminal_token_verify",
      "data": {
        "temp_token": "abc123def456ghi789",
        "item_uuid": "item_123456789"
      }
    }

    核心逻辑：Daemon 不存储任何用户 / 权限数据，仅做「请求转发」，所有校验逻辑由 Backend 完成。

步骤 7：Backend 校验 Token 并返回结果

    Backend 接收到 Daemon 的校验请求后，查询缓存中的 Token 信息：
        校验 1：Token 是否存在；
        校验 2：是否未过期（对比当前时间戳 vs expire_at）；
        校验 3：是否与 item_uuid 绑定；
        校验 4：是否为「未使用」状态（used: false）。
    校验结果处理：
        ✅ 校验通过：
            将缓存中 Token 的 used 标记为 true（一次性使用，防止复用）；
            向 Daemon 返回「合法」响应：
            json

            {
              "type": "terminal_token_verify_result",
              "data": {
                "valid": true,
                "item_uuid": "item_123456789"
              }
            }

        ❌ 校验失败（任意条件不满足）：
            向 Daemon 返回「非法」响应：
            json

            {
              "type": "terminal_token_verify_result",
              "data": {
                "valid": false,
                "msg": "Token已过期/无效/已使用"
              }
            }

步骤 8：Daemon 处理连接请求（建立 / 断开）

    ✅ 校验通过：
        Daemon 与浏览器建立正式 WebSocket 连接；
        将浏览器连接加入 item_uuid 对应的 Room；
        向浏览器发送「连接成功」消息，开启终端交互（转发 Item 输出、接收用户指令）。
    ❌ 校验失败：
        Daemon 直接断开浏览器连接；
        可选：向浏览器发送「认证失败：{具体原因}」的关闭消息；
        浏览器前端提示「终端连接失败：Token 无效 / 已过期 / 无权限」，流程终止。

三、核心异常场景补充
表格
异常场景	触发节点	处理逻辑
用户长期 Token 过期	步骤 3	Backend 返回 401，浏览器跳转登录页，重新登录后重试
临时 Token 过期	步骤 7	Backend 返回校验失败，Daemon 断开连接，浏览器提示「Token 过期，请重新打开终端」
临时 Token 重复使用	步骤 7	Backend 检测到 used: true，返回失败，触发安全告警（疑似攻击）
Daemon 主连接断开	步骤 6	Daemon 暂存连接请求，触发主连接重连，重连成功后重新发起 Token 校验
Item 未启动	步骤 3 / 步骤 8	Backend 提前校验 Item 状态，返回 400 错误；或 Daemon 校验通过后检测 Item 状态，断开连接并提示
四、流程核心总结

    身份闭环：用户长期 Token 验证身份，临时 Token 隔离权限，全程不暴露敏感凭证；
    职责分离：Backend 管「鉴权 / 签发」，Daemon 管「执行 / 转发」，浏览器仅做「请求发起」；
    安全保障：临时 Token 一次性 + 短期 + 绑定实例，即使泄露也无法跨实例 / 跨时段使用；
    全链路校验：从「用户请求 Token」到「Daemon 建立连接」，共 4 层校验（用户身份→Item 权限→Token 有效性→Token 唯一性），无校验死角。



# 浏览器关闭/断开连接的全链路处理流程（含 Token/连接/进程/资源清理）
## 一、核心处理目标
浏览器主动关闭页面、网络断开、手动断开终端连接时，需实现：
1. **前端优雅断开**：主动告知 Daemon 断开连接，避免无效连接占用资源；
2. **Daemon 清理资源**：移除 Room 订阅、停止输出转发、释放 Socket 句柄；
3. **Backend 状态同步**：更新终端连接状态、标记临时 Token 失效（可选）；
4. **异常兜底**：网络异常断开时，Daemon 能被动检测并完成资源清理。

## 二、完整处理流程（分场景+分步骤）
### 场景1：浏览器主动关闭/手动断开（正常场景）
#### 步骤1：前端触发主动断开逻辑
1. **触发时机**：用户点击「关闭终端」按钮、关闭浏览器标签页/窗口；
2. **前端处理**：
   - 监听页面关闭事件（`beforeunload`）或「关闭终端」按钮点击事件；
   - 若 WebSocket 连接仍处于 `OPEN` 状态，主动发送「断开通知」：
     ```javascript
     // 前端 JS 示例
     const socket = new WebSocket(`ws://daemon:24444/ws?token=${tempToken}&item_uuid=${itemUuid}`);
     
     // 监听页面关闭
     window.addEventListener("beforeunload", () => {
       if (socket.readyState === WebSocket.OPEN) {
         // 发送断开指令（自定义协议）
         socket.send(JSON.stringify({
           type: "browser_disconnect",
           data: { item_uuid: itemUuid, reason: "user_close" }
         }));
         // 延迟断开（确保消息发送成功）
         setTimeout(() => socket.close(1000, "user close"), 100);
       }
     });
     
     // 手动关闭终端按钮
     function closeTerminal() {
       if (socket.readyState === WebSocket.OPEN) {
         socket.send(JSON.stringify({
           type: "browser_disconnect",
           data: { item_uuid: itemUuid, reason: "manual_close" }
         }));
         socket.close(1000, "manual close");
       }
       // 清理前端状态
       delete localStorage.terminalConnStatus;
     }
     ```
   - 核心：先发送「断开通知」，再关闭连接，避免 Daemon 收不到断开指令。

#### 步骤2：Daemon 接收断开指令并清理资源
1. **监听断开事件**：
   Daemon 监听 WebSocket 的 `message` 事件（接收主动断开指令）+ `disconnect` 事件（被动兜底）：
   ```python
   # Daemon 端 Socket.IO 示例（Python）
   @sio.event
   def message(sid, data):
       data = json.loads(data)
       if data.get("type") == "browser_disconnect":
           item_uuid = data["data"]["item_uuid"]
           # 1. 移除该客户端从对应 Room
           sio.leave_room(sid, item_uuid)
           # 2. 清理订阅表（sid 与 item_uuid 映射）
           if item_uuid in subscriber_map and sid in subscriber_map[item_uuid]:
               subscriber_map[item_uuid].remove(sid)
           # 3. 记录断开日志
           print(f"客户端 {sid} 主动断开 Item {item_uuid}，原因：{data['data']['reason']}")
           # 4. 可选：通知 Backend 连接断开
           notify_backend_disconnect(item_uuid, sid, "active_close")

   # 被动监听 disconnect 事件（兜底）
   @sio.event
   def disconnect(sid):
       # 遍历所有 Item，清理该 sid 的订阅关系
       for item_uuid in list(subscriber_map.keys()):
           if sid in subscriber_map[item_uuid]:
               subscriber_map[item_uuid].remove(sid)
               print(f"客户端 {sid} 被动断开，清理 Item {item_uuid} 订阅")
               # 可选：通知 Backend
               notify_backend_disconnect(item_uuid, sid, "passive_close")
   ```
2. **核心清理动作**：
   - 从 `item_uuid` 对应的 Room 中移除客户端 `sid`；
   - 从 `subscriber_map`（订阅表）中删除 `sid`，避免内存泄漏；
   - 若该 Item 无剩余订阅者（`len(subscriber_map[item_uuid]) == 0`）：
     - 可选：停止 Item 子进程输出的实时转发（仅保留日志写入）；
     - 可选：释放子进程管道的临时缓存。

#### 步骤3：Daemon 同步状态到 Backend（可选）
1. Daemon 通过「与 Backend 的可信主连接」发送断开通知：
   ```python
   def notify_backend_disconnect(item_uuid, sid, reason):
       # 主连接发送消息
       daemon_main_ws.send(json.dumps({
           type: "terminal_disconnect",
           data: {
               item_uuid: item_uuid,
               browser_sid: sid,
               reason: reason,
               disconnect_time: time.time()
           }
       }))
   ```
2. Backend 处理：
   - 更新终端连接状态（如缓存中标记 `item_uuid` 的「在线终端数」-1）；
   - 可选：若为「手动关闭」，标记该终端临时 Token 为「已失效」（防止复用）；
   - 记录断开日志（用户 ID、Item ID、断开时间、原因）。

### 场景2：浏览器异常断开（网络中断/页面崩溃）
#### 步骤1：Daemon 被动检测断开
1. **心跳检测机制**（核心兜底方案）：
   - Daemon 向浏览器定时发送心跳包（如每 30 秒）：
     ```python
     # Daemon 端心跳检测
     def heartbeat_check():
         while True:
             for item_uuid in subscriber_map:
                 for sid in subscriber_map[item_uuid]:
                     try:
                         # 发送心跳包（Socket.IO 内置心跳或自定义）
                         sio.emit("heartbeat", {"timestamp": time.time()}, to=sid)
                     except Exception as e:
                         # 发送失败，判定为断开
                         subscriber_map[item_uuid].remove(sid)
                         sio.leave_room(sid, item_uuid)
                         print(f"客户端 {sid} 心跳失败，判定为断开 Item {item_uuid}")
             time.sleep(30)

     # 启动心跳线程
     threading.Thread(target=heartbeat_check, daemon=True).start()
     ```
   - 浏览器需回复心跳响应（`heartbeat_ack`），若 Daemon 连续 2 次未收到响应（60 秒），判定为断开。
2. **Socket 内置断开检测**：
   Daemon 监听 WebSocket 的 `close`/`error` 事件，被动捕获连接断开：
   ```python
   @sio.event
   def error(sid, error):
       # 连接出错，触发清理
       for item_uuid in list(subscriber_map.keys()):
           if sid in subscriber_map[item_uuid]:
               subscriber_map[item_uuid].remove(sid)
               sio.leave_room(sid, item_uuid)
       print(f"客户端 {sid} 连接出错：{error}，已清理资源")
   ```

#### 步骤2：Daemon 执行资源清理（同主动断开）
- 移除 Room 订阅、清理 `subscriber_map`、记录异常断开日志；
- 若 Item 无剩余订阅者，停止实时输出转发；
- 通过主连接同步断开状态到 Backend，标记原因为「network_error/crash」。

#### 步骤3：Backend 异常处理
- 标记该终端连接为「异常断开」；
- 可选：向用户推送通知（如「你的终端连接已异常断开，请重新打开」）；
- 若临时 Token 未过期，可选：标记为「失效」，避免用户重连时使用旧 Token。

### 场景3：浏览器重连（断开后恢复）
#### 步骤1：前端重连逻辑
1. 监听 `onclose` 事件，触发重连：
   ```javascript
   socket.onclose = (event) => {
     if (event.code !== 1000) { // 非主动关闭，触发重连
       const reconnectInterval = setInterval(() => {
         // 重新获取临时 Token（旧 Token 可能已失效）
         fetch("/api/terminal/get-temp-token", {
           method: "POST",
           headers: { "Authorization": `Bearer ${userToken}` },
           body: JSON.stringify({ item_uuid: itemUuid })
         }).then(res => res.json()).then(data => {
           if (data.code === 200) {
             // 重新建立连接
             socket = new WebSocket(`${data.data.ws_url}?token=${data.data.temp_token}&item_uuid=${itemUuid}`);
             clearInterval(reconnectInterval);
           }
         });
       }, 5000); // 每 5 秒重试
     }
   };
   ```
2. 核心：重连前需重新获取临时 Token（旧 Token 可能已被标记为「已使用」）。

#### 步骤2：Daemon/Backend 重连处理
- Backend 重新签发新的临时 Token（绑定相同 `item_uuid`）；
- Daemon 校验新 Token 后，重新将浏览器加入 Room，恢复输出转发；
- 可选：Daemon 向浏览器补发重连期间丢失的 Item 输出（从日志中拉取）。

## 三、核心清理动作总结（Daemon 侧）
| 清理项                | 处理逻辑                                                                 |
|-----------------------|--------------------------------------------------------------------------|
| Room 订阅             | `sio.leave_room(sid, item_uuid)` 移除客户端从对应 Room                  |
| 订阅表                | 从 `subscriber_map[item_uuid]` 中删除 `sid`，空列表则删除该 Item 键      |
| Socket 资源           | 释放 Socket 句柄，关闭未发送完成的消息队列                              |
| 子进程转发            | 无订阅者时停止实时转发（仅保留日志写入），有新订阅时恢复                 |
| 临时缓存              | 清理该客户端的指令缓存、输出缓存                                        |
| 状态同步              | 向 Backend 发送断开通知，更新连接状态                                    |

## 四、关键优化点
1. **避免重复清理**：在清理逻辑中增加「存在性判断」（如 `if sid in list`），防止 KeyError；
2. **日志完整性**：记录所有断开事件（主动/被动、原因、时间、客户端 ID），便于问题排查；
3. **资源释放时机**：
   - 主动断开：立即清理；
   - 异常断开：心跳检测确认后清理（避免误判）；
4. **Token 安全**：
   - 主动断开：标记临时 Token 为「已失效」，防止复用；
   - 异常断开：Token 过期后自动失效，不提前作废（允许用户短时间内重连）。

## 五、全链路处理总结
1. **主动断开**：前端先发指令 → Daemon 清理资源 → Backend 同步状态，全程可控；
2. **异常断开**：Daemon 心跳检测兜底 → 被动清理资源 → 前端自动重连（重新获取 Token）；
3. **核心原则**：
   - 前端：能主动断开就不被动，重连前重新获取 Token；
   - Daemon：清理资源优先（Room/订阅表），状态同步其次；
   - Backend：仅维护连接状态，不参与资源清理，保证职责分离。

这套流程既保证了「正常断开时的优雅清理」，又解决了「异常断开时的资源泄漏」问题，同时支持重连恢复，符合生产级别的稳定性要求。