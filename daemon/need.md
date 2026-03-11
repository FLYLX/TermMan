后端 Service 模块可读取数据项（item）中存储的ip、port字段，通过 item 内置的api key与目标节点机器建立并维持TCP 长连接（复用 MCSM Socket.IO 基于 HTTP 升级的长连接机制，共享节点端口）。
daemon端也用HTTP服务器方式，接收后端的请求，如启动/中断终端，查询终端状态等。
item对应一个daemon里面的其中一个子进程终端，通过soket连接。
1. 终端未启动时的处理逻辑
当 item 对应的终端未启动，用户发起 item 访问请求时：
    daemon是一个HTTP服务器，后端通过api key认证不同的daemon，认证通过后，后端通过已建立的 TCP 长连接将指令下发至节点。
    后端可以有多个daemon连接，建立一个daemon连接池，如果检测到要连接item的daemon不在连接池，就创建一个新的连接，否则就复用已有的连接。
    节点终端的启动位置是workdir/[user_uuid]/[item_uuid]目录，daemon端创建子进程并启动终端，该子进程作为终端 Socket 服务器；
    也就是说，一个daemon端可以有多个item终端的Socket服务器。后端通过item uuid + token，匹配节点内存中的映射表，建立后端与对应 item 终端 Socket 服务器的连接。
    后端和daemon端是通过HTTP服务器保持长连接，后端和节点终端是通过socket，被http服务器管理。
    log位置为daemon/log/[user_uuid]/[item_uuid].log
    daemon的log位置为daemon/log/daemon.log
     item 终端会对应一个 Socket 服务器，生成唯一token，并通过 TCP 长连接将「用户标识、item 标识、token」回传给后端；
    后端接收到 token 后，更新 item 对应的数据库记录，写入远程 Socket 的 token 字段。
    此时后端可以通过item uuid + token，匹配节点内存中的映射表，建立后端与对应 item 终端 Socket 服务器的连接。注意这里是直接后端对终端socket服务器的连接，不再通过daemon端。
    但是daemon端http服务器也需要保持长连接，与后端保持通信。因为他可以控制节点终端的启动、中断某个socket连接、关闭某个socket服务器，查询状态等。
    
2. 节点端内存存储与 Socket 管理
节点在内存中维护两张核心映射表：

    user_uuid : item_uuid（用户 - 终端归属关系）；
    item_uuid : token（终端 - 访问凭证映射）；
    同时节点维护Socket 服务器池，统一管理所有 item 终端的 Socket 服务器实例，支持接收后端通过 TCP 长连接下发的「中断指令」，精准关闭指定 item 对应的 Socket 服务器 / Socket 连接。
    daemon端也用HTTP服务器方式，接收后端的请求，如启动/中断终端，查询终端状态等参考MCSM。

3. 终端已启动时的连接逻辑
若 item 终端已启动，浏览器 / 后端可直接通过item uuid + token，匹配节点内存中的映射表，建立与对应 item 终端 Socket 服务器的连接。
4. 数据流转与子进程行为

    子进程（终端 Socket 服务器）将自身的stdout实时推送至所有已连接的 Socket 客户端；
    客户端（浏览器 / 后端）通过 Socket 向子进程发送的指令，将作为子进程的stdin输入；
    所有数据交互均通过 Socket 完成，遵循 MCSM「前端 - 后端 - 节点」的 Socket 通讯协议（如stream/write/instance/stdout事件机制）。

核心优化点（对齐 MCSM 实现）

    明确 TCP 长连接复用节点端口（参考 MCSM Daemon 的 HTTP/Socket 共用端口逻辑）；
    补充 Socket 鉴权机制（参考 MCSM 的missionPassport token 验证）；
    对齐 MCSM 的「节点 - 后端」指令交互逻辑（如终端启动 / 中断的指令下发）；
    明确子进程 Socket 服务器的数据流转发规则（参考 MCSM stream/resize/stream/write事件）；
    补充节点内存表的设计（参考 MCSM InstanceStreamListener的实例映射）。


功能模块架构：
service/
├── __init__.py               # 包标记 + 核心实例导出
├── connection_pool/          # TCP长连接池核心模块（按daemon维度管理）
│   ├── __init__.py
│   ├── daemon_connection.py  # 单个Daemon节点的TCP连接封装（复用Socket.IO长连接）
│   ├── connection_manager.py # Daemon连接池管理（创建/复用/销毁/心跳检测）
│   └── connection_models.py  # 连接池数据模型（状态枚举、配置类）
├── socket_pool/              # Item终端Socket连接池（按item维度管理）
│   ├── __init__.py
│   ├── item_socket.py        # 单个Item终端的Socket客户端封装（对接Daemon子进程Socket）
│   ├── socket_manager.py     # Item Socket池管理（token鉴权、连接复用）
│   └── socket_models.py      # Socket数据模型（终端状态、Token信息）
├── connection_handler.py     # 统一连接处理器（指令转发、响应解析、异常处理）
├── terminal_service.py       # 终端核心业务逻辑（启动/中断/查询状态、日志管理）
├── auth_service.py           # 鉴权服务（API Key验证、Token生成/校验，对齐MCSM missionPassport）
└── protocol/                 # MCSM协议适配层（事件定义、数据编解码）
    ├── __init__.py
    ├── events.py             # 事件枚举（stream/write/instance/stdout等）
    └── codec.py              # 数据编解码（对齐MCSM Socket通信格式）

daemon:
    文件结构：
daemon/
├── pyproject.toml            # 项目核心配置（替代requirements.txt）
├── .env                      # 环境变量配置（敏感配置/运行参数）
├── .env.example              # 环境变量示例（提交到版本库）
├── src/
│   ├── __init__.py           # 标记Python包
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py         # 配置管理（读取.env + 持久化config.json）
│   │   ├── memory_store.py   # 内存存储核心（TTL + 内存Map，替代mini_redis）
│   │   └── file_storage.py   # 文件存储封装（JSON/文件读写）
│   ├── service/
│   │   ├── __init__.py
│   │   ├── terminal_manager.py # 终端进程管理（内存Map存储进程状态）
│   │   ├── socket_service.py   # Socket.IO 连接池（内存Map管理连接）
│   │   └── auth_service.py     # 鉴权服务（内存TTL存储Token）
│   ├── api/
│   │   ├── __init__.py
│   │   ├── http_routes.py      # FastAPI 实现 HTTP 接口
│   │   └── socket_routes.py    # Socket.IO 数据流转发
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── logger.py           # 日志写入文件（按目录拆分）
│   ├── data/                  # 持久化文件目录（自动生成）
│   │   ├── __init__.py
│   │   ├── config.json        # 核心配置（非敏感）
│   │   ├── terminals/         # 终端配置（按 user_uuid/item_uuid 拆分）
│   │   └── logs/              # 业务日志文件（按 user_uuid/item_uuid 拆分）
│   ├── workdir/               # 终端工作目录（按 user_uuid/item_uuid 拆分）
│   └── main.py                # 入口文件（初始化+启动服务）
├── log/                       # 应用日志输出目录（独立于业务日志）
└── README.md                  # 项目说明（可选）


注意：
    1. 终端配置（terminals/）和业务日志（logs/）目录，按user_uuid/item_uuid生成子文件夹，避免文件混乱。
    2. 终端工作目录（workdir/）和log目录（logs/），按user_uuid/item_uuid生成子文件夹，确保每个终端进程有独立的工作环境。
