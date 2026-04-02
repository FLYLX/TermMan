# Service 结构总览

这个目录现在只保留少量结构说明文件，入口如下：

- `agent/README.md`
  说明 Agent 编排层，包含会话、时间线、MCP、记忆、技能。

- `connection_pool/README.md`
  说明 Backend 到 Daemon 的主连接控制面。

- `socket_pool/README.md`
  说明 item 房间级别的 socket、订阅、输入分发和 SDK。

- `socket_pool/SUBSCRIPTION_CENTER.md`
  单独说明订阅中心，因为它同时连接日志、终端流、Agent 自动处理。

## 目录分工

- `agent/`
  LLM 编排层。
  负责共享聊天时间线、工具调用、记忆、技能和终端自动处理。

- `connection_pool/`
  Backend 到 Daemon 的主控制连接。
  负责 `terminal/start`、`terminal/stop`、`terminal/list` 这类 RPC。

- `socket_pool/`
  item 级运行时连接层。
  负责 room socket、终端输出分发、浏览器连接、命令写入。

- `filters/`
  输入过滤和输出过滤。

- `protocol/`
  事件名和协议常量。

- `terminal_service.py`
  启停终端的业务入口。

- `daemon_initializer.py`
  Backend 启动时恢复 daemon 状态、同步 running item、重建 backend room 监听。

- `log_manager.py`
  后端日志落盘。

- `auth_service.py`
  浏览器临时 token、daemon auth token、访问校验。

## 调试时的判断顺序

1. Daemon 主连接有问题：
   看 `connection_pool/`
2. item 房间输出或浏览器连接有问题：
   看 `socket_pool/`
3. Agent 没响应、时间线不对、工具行为不对：
   看 `agent/`
4. Backend 重启后状态恢复不对：
   看 `daemon_initializer.py`
