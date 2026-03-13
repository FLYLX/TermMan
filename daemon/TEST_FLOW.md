# TermMan Daemon 测试流程

## 测试环境准备

### 1. 系统要求
- Windows 10/11
- Python 3.10+ 环境
- Poetry 依赖管理工具

### 2. 安装依赖

```bash
# 进入daemon目录
cd daemon

# 安装依赖
poetry install
```

### 3. 配置环境变量

检查 `.env` 文件是否存在，如果不存在则从示例文件创建：

```bash
# 复制示例配置文件
copy .env.example .env
```

编辑 `.env` 文件，确保配置正确：

```ini
# Daemon Configuration
PORT=9000
API_KEY=termman_daemon_secret_key_2024
HOST=0.0.0.0
WORKDIR=./src/workdir
LOG_DIR=./log
DATA_DIR=./src/data

# Terminal Configuration
TERMINAL_SHELL=cmd.exe  # For Windows
TERMINAL_ENCODING=utf-8
TERMINAL_BUFFER_SIZE=8192
```

## 测试流程

### 第一步：启动 Daemon 服务

在一个终端窗口中启动Daemon服务：

```bash
# 进入daemon目录
cd daemon

# 启动服务
poetry run python src/main.py
```

等待服务启动成功，看到类似输出：

```
[INFO] Starting TermMan Daemon on 0.0.0.0:9000
[INFO] API Key: ***2024
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:9000 (Press CTRL+C to quit)
```

### 第二步：运行测试脚本

在另一个终端窗口中运行测试脚本：

```bash
# 进入daemon目录
cd daemon

# 运行测试
poetry run python test_daemon.py
```

## 测试内容说明

测试脚本会依次执行以下测试用例：

### 1. 健康检查接口
- 测试地址：`http://127.0.0.1:9000/`
- 验证Daemon服务是否正常启动

### 2. 启动终端
- 测试接口：`POST /api/terminal/start`
- 功能：创建并启动新的终端进程
- 输入参数：用户UUID、终端Token
- 输出：终端UUID、Token

### 3. 获取终端状态
- 测试接口：`GET /api/terminal/status/{item_uuid}`
- 功能：查询终端的运行状态
- 输出：终端状态（running/stopped/error）

### 4. Socket.IO连接
- 测试地址：`ws://127.0.0.1:9000/`
- 功能：建立与终端的Socket连接
- 验证Token认证机制

### 5. 终端交互
- 功能：向终端发送命令并接收输出
- 测试命令：`ping -n 2 127.0.0.1`
- 验证终端能够正常执行命令并返回结果

### 6. 断开Socket连接
- 功能：断开与终端的Socket连接
- 验证连接能够正常关闭

### 7. 停止终端
- 测试接口：`POST /api/terminal/stop`
- 功能：停止指定的终端进程
- 清理资源

### 8. 获取终端列表
- 测试接口：`GET /api/terminal/list`
- 功能：查询所有终端的状态
- 验证终端已被正确停止

## 测试结果解读

### 成功输出示例

```
[INFO] ==============================
[INFO] 开始测试 TermMan Daemon
[INFO] ==============================
[INFO] 测试1: 健康检查接口
[SUCCESS] ✓ 健康检查接口正常
[INFO] 测试2: 启动终端
[SUCCESS] ✓ 终端启动成功，item_uuid: item-12345678-1234-5678-1234-567812345678
[INFO] 测试3: 获取终端状态
[SUCCESS] ✓ 终端状态获取成功，状态: running
[INFO] 测试4: Socket.IO连接
[INFO] Socket.IO已连接
[SUCCESS] ✓ 终端Socket连接成功
[INFO] 测试5: 终端交互 (执行ping命令)
[INFO] 终端输出: Pinging 127.0.0.1 with 32 bytes of data:
[INFO] 终端输出: Reply from 127.0.0.1: bytes=32 time<1ms TTL=128
[INFO] 终端输出: Reply from 127.0.0.1: bytes=32 time<1ms TTL=128
[INFO] 终端输出: 
[INFO] 终端输出: Ping statistics for 127.0.0.1:
[INFO] 终端输出:     Packets: Sent = 2, Received = 2, Lost = 0 (0% loss),
[INFO] 终端输出: Approximate round trip times in milli-seconds:
[INFO] 终端输出:     Minimum = 0ms, Maximum = 0ms, Average = 0ms
[SUCCESS] ✓ 终端交互成功，收到输出
[INFO] 测试6: 断开Socket连接
[INFO] Socket.IO已断开连接
[SUCCESS] ✓ Socket连接已断开
[INFO] 测试7: 停止终端
[SUCCESS] ✓ 终端停止成功
[INFO] 测试8: 获取终端列表
[SUCCESS] ✓ 终端列表获取成功，当前终端数: 0
[INFO] ==============================
[INFO] 测试总结
[INFO] ==============================
[INFO] 总测试数: 8
[INFO] 通过: 8
[INFO] 失败: 0
[SUCCESS] ✓ 所有测试通过！
```

### 失败情况处理

如果测试失败，根据错误信息进行排查：

1. **服务未启动**
   - 检查Daemon服务是否正常运行
   - 检查端口是否被占用

2. **认证失败**
   - 检查API Key是否配置正确
   - 检查Token是否有效

3. **终端启动失败**
   - 检查TERMINAL_SHELL配置是否正确
   - 检查工作目录是否有写权限

4. **Socket连接失败**
   - 检查网络连接
   - 检查防火墙设置

## 日志查看

测试过程中的日志会输出到以下位置：

- **应用日志**：`./log/daemon.log`
- **终端日志**：`./log/{user_uuid}/{item_uuid}.log`

可以通过查看日志文件来排查问题。

## 清理资源

测试完成后，可以清理测试生成的文件：

```bash
# 删除测试日志
rmdir /s /q log

# 删除工作目录
rmdir /s /q src\workdir

# 重新创建空目录
mkdir log
mkdir src\workdir
```

## 自动化测试

可以将测试脚本集成到CI/CD流程中，使用以下命令进行自动化测试：

```bash
# 运行测试并生成报告
poetry run pytest test_daemon.py -v
```

## 注意事项

1. 确保Daemon服务和测试脚本使用相同的API Key
2. 测试过程中不要关闭Daemon服务窗口
3. 如果测试失败，先检查日志文件获取详细错误信息
4. 测试完成后记得清理测试资源
