import requests
import socketio
import sys
import threading
import json
import time
import uuid
from typing import Callable, Dict, Any

class ProtocolEvents:
    """协议事件枚举"""
    STREAM = "stream"
    WRITE = "terminal_write"
    TERMINAL_CONNECT = "terminal_connect"
    TERMINAL_START = "terminal/start"
    TERMINAL_STOP = "terminal/stop"
    TERMINAL_STATUS = "terminal/status"

class TerminalStatus:
    """终端状态枚举"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"

class IntegratedTerminalTest:
    """整合终端测试类"""
    def __init__(self):
        # 配置参数
        self.daemon_url = "http://localhost:9000"
        self.api_key = "TermPaws_daemon_secret_key_2024"
        self.user_uuid = "test_user_123"
        self.terminal_item_uuid = None
        self.terminal_token = None
        self.interactive_terminal = None

    def start_terminal(self) -> bool:
        """启动终端"""
        print("=== 1. 启动终端 ===")
        
        api_url = f"{self.daemon_url}/api/terminal/start"
        self.terminal_token = str(uuid.uuid4())
        
        # 准备请求数据
        data = {
            "user_uuid": self.user_uuid,
            "token": self.terminal_token,
            "command": "bash",  # 启动bash终端
            "args": [],
            "cwd": "/tmp"
        }
        
        # 发送请求
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.post(api_url, headers=headers, data=json.dumps(data))
            
            if response.status_code == 200:
                result = response.json()
                self.terminal_item_uuid = result.get("item_uuid")
                print(f"✓ 终端启动成功")
                print(f"  Item UUID: {self.terminal_item_uuid}")
                print(f"  Token: {self.terminal_token}")
                print(f"  User UUID: {self.user_uuid}")
                return True
            else:
                print(f"✗ 终端启动失败: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"✗ 启动终端时发生错误: {str(e)}")
            return False

    class InteractiveTerminal:
        """交互式终端客户端"""
        def __init__(self, daemon_url: str, item_uuid: str, token: str, user_uuid: str, api_key: str):
            self.daemon_url = daemon_url
            self.item_uuid = item_uuid
            self.token = token
            self.user_uuid = user_uuid
            self.api_key = api_key
            self.status = TerminalStatus.STOPPED
            self.sio = socketio.Client(reconnection=False)
            self.setup_event_handlers()
            self.should_exit = False

        def setup_event_handlers(self):
            """设置Socket.IO事件处理器"""
            @self.sio.event
            def connect():
                self.status = TerminalStatus.RUNNING
                print("✓ 已连接到终端服务器")
                # 发送终端连接事件
                self.sio.emit(ProtocolEvents.TERMINAL_CONNECT, {
                    "item_uuid": self.item_uuid,
                    "token": self.token,
                    "user_uuid": self.user_uuid
                })

            @self.sio.event
            def disconnect():
                self.status = TerminalStatus.STOPPED
                print("✗ 已断开与终端服务器的连接")

            @self.sio.event
            def terminal_connected(data):
                print(f"✓ 终端已连接: {json.dumps(data)}")

            @self.sio.event
            def auth_error(data):
                print(f"✗ 认证错误: {json.dumps(data)}")
                self.should_exit = True

            @self.sio.on(ProtocolEvents.STREAM)
            def on_stream(data):
                """处理终端输出流"""
                stdout = data.get("stdout", "")
                stderr = data.get("stderr", "")
                
                if stdout:
                    sys.stdout.write(stdout)
                    sys.stdout.flush()
                if stderr:
                    sys.stderr.write(stderr)
                    sys.stderr.flush()

        def connect(self) -> bool:
            """建立与终端服务器的连接"""
            try:
                self.status = TerminalStatus.STARTING
                print(f"正在连接到: {self.daemon_url}...")
                
                # 连接到Daemon的Socket.IO服务
                self.sio.connect(
                    self.daemon_url,
                    transports=["websocket"],
                    auth={"api_key": self.api_key}
                )
                
                return True
            except Exception as e:
                self.status = TerminalStatus.ERROR
                print(f"✗ 连接失败: {str(e)}")
                return False

        def disconnect(self):
            """断开连接"""
            try:
                self.sio.disconnect()
            except Exception:
                pass
            self.status = TerminalStatus.STOPPED

        def write(self, command: str) -> bool:
            """向终端写入命令"""
            if self.status != TerminalStatus.RUNNING:
                print("✗ 终端未连接")
                return False
            try:
                self.sio.emit(ProtocolEvents.WRITE, {
                    "command": command + "\n"  # 添加换行符以执行命令
                })
                return True
            except Exception as e:
                print(f"✗ 发送命令失败: {str(e)}")
                return False

        def is_connected(self) -> bool:
            """检查连接状态"""
            return self.status == TerminalStatus.RUNNING

        def input_loop(self):
            """用户输入循环"""
            import sys
            print("\n=== 3. 交互式终端已启动 ===")
            print("输入 'exit' 或 'quit' 退出终端")
            print("输入 'test' 运行测试命令")
            print("直接输入命令即可与终端交互\n")

            # 发送测试命令
            self.write("echo 'Interactive terminal is ready!'")
            # 使用Windows兼容的命令
            self.write("echo %USERNAME%")
            self.write("cd")

            while not self.should_exit:
                try:
                    # 使用sys.stdin.readline()获取输入，更可靠地处理回车事件
                    print(">", end="", flush=True)
                    command = sys.stdin.readline().rstrip("\r\n")  # 移除Windows换行符
                    
                    if not command:  # 处理空行
                        continue
                    
                    if command.lower() in ['exit', 'quit']:
                        self.should_exit = True
                        print("\n正在断开连接...")
                        break
                    elif command.lower() == 'test':
                        # 运行测试命令
                        self.write("echo '=== 运行测试命令 ==='")
                        self.write("echo %USERNAME%")
                        self.write("cd")
                        self.write("echo 'Test completed'")
                    else:
                        # 发送命令到终端
                        self.write(command)
                        
                except KeyboardInterrupt:
                    self.should_exit = True
                    print("\n\n收到中断信号，正在退出...")
                    break
                except EOFError:
                    self.should_exit = True
                    print("\n\n收到EOF信号，正在退出...")
                    break

        def start(self):
            """启动交互式终端"""
            try:
                # 建立连接
                if not self.connect():
                    return False

                # 等待连接稳定
                time.sleep(1)

                if not self.is_connected():
                    print("✗ 连接未建立成功")
                    return False

                # 启动输入循环
                self.input_loop()

                return True
            finally:
                # 确保断开连接
                self.disconnect()

    def run_interactive_session(self) -> bool:
        """运行交互式会话"""
        if not self.terminal_item_uuid or not self.terminal_token:
            print("✗ 终端未启动，无法建立交互会话")
            return False

        print("\n=== 2. 建立交互连接 ===")
        self.interactive_terminal = self.InteractiveTerminal(
            daemon_url=self.daemon_url,
            item_uuid=self.terminal_item_uuid,
            token=self.terminal_token,
            user_uuid=self.user_uuid,
            api_key=self.api_key
        )

        return self.interactive_terminal.start()

    def stop_terminal(self) -> bool:
        """停止终端"""
        if not self.terminal_item_uuid:
            print("✗ 没有可停止的终端")
            return False

        print("\n=== 4. 停止终端 ===")
        api_url = f"{self.daemon_url}/api/terminal/stop"
        
        data = {
            "item_uuid": self.terminal_item_uuid
        }
        
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.post(api_url, headers=headers, data=json.dumps(data))
            
            if response.status_code == 200:
                result = response.json()
                print(f"✓ 终端已停止: {json.dumps(result)}")
                return True
            else:
                print(f"✗ 停止终端失败: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"✗ 停止终端时发生错误: {str(e)}")
            return False

    def run(self):
        """运行完整测试流程"""
        print("=" * 50)
        print("TermPaws 集成测试")
        print("=" * 50)

        try:
            # 1. 启动终端
            if not self.start_terminal():
                return False

            # 2. 建立交互会话
            if not self.run_interactive_session():
                return False

            # 3. 停止终端
            if not self.stop_terminal():
                return False

            print("\n" + "=" * 50)
            print("✓ 所有测试步骤完成")
            print("=" * 50)
            return True
        except Exception as e:
            print(f"\n✗ 测试过程中发生错误: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == "__main__":
    """主函数"""
    test = IntegratedTerminalTest()
    success = test.run()
    sys.exit(0 if success else 1)
