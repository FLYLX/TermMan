import os
import sys
import time
import requests
import socketio
import uuid
import threading
import queue

# 测试配置
DAEMON_HOST = "127.0.0.1"
DAEMON_PORT = 24444
API_KEY = "termman_daemon_secret_key_2024"
BASE_URL = f"http://{DAEMON_HOST}:{DAEMON_PORT}"
API_BASE_URL = f"{BASE_URL}/api"

# 测试配置
NUM_TERMINALS = 3  # 要创建的终端数量
TEST_COMMANDS = ["echo 'Hello from terminal 1'", "echo 'Hello from terminal 2'", "echo 'Hello from terminal 3'"]

class TestLogger:
    """测试日志工具"""
    @staticmethod
    def info(message):
        print(f"[INFO] {message}")
    
    @staticmethod
    def success(message):
        print(f"[SUCCESS] {message}")
    
    @staticmethod
    def error(message):
        print(f"[ERROR] {message}")
    
    @staticmethod
    def warning(message):
        print(f"[WARNING] {message}")

logger = TestLogger()

class TerminalClient:
    """终端客户端"""
    def __init__(self, index, user_uuid, terminal_token, item_uuid):
        self.index = index
        self.user_uuid = user_uuid
        self.terminal_token = terminal_token
        self.item_uuid = item_uuid
        self.socket_client = None
        self.socket_connected = False
        self.stdout_received = []
        self.response_queue = queue.Queue()
    
    def connect(self):
        """连接到Daemon"""
        try:
            # 创建Socket.IO客户端
            self.socket_client = socketio.Client()
            
            # 事件处理
            @self.socket_client.event
            def connect():
                logger.info(f"终端{self.index}: Socket.IO已连接")
                
            @self.socket_client.event
            def disconnect():
                logger.info(f"终端{self.index}: Socket.IO已断开连接")
                self.socket_connected = False
            
            @self.socket_client.event
            def terminal_connected(data):
                logger.success(f"终端{self.index}: 终端Socket连接成功")
                self.socket_connected = True
                self.response_queue.put("connected")
            
            @self.socket_client.event
            def auth_error(data):
                logger.error(f"终端{self.index}: 终端Socket认证失败: {data}")
                self.socket_connected = False
                self.response_queue.put("auth_error")
            
            @self.socket_client.event
            def stream(data):
                output = data.get("stdout", "")
                if output:
                    self.stdout_received.append(output)
                    logger.info(f"终端{self.index}输出: {output.strip()}")
                    self.response_queue.put("output_received")
            
            # 连接到Daemon
            self.socket_client.connect(
                BASE_URL,
                transports=["websocket"],
                auth={"api_key": API_KEY}
            )
            
            # 连接到终端
            time.sleep(1)
            if self.socket_client.connected:
                self.socket_client.emit("terminal_connect", {
                    "item_uuid": self.item_uuid,
                    "token": self.terminal_token
                })
                
                # 等待连接完成
                try:
                    result = self.response_queue.get(timeout=5)
                    return result == "connected"
                except queue.Empty:
                    logger.error(f"终端{self.index}: 终端Socket连接超时")
                    return False
            else:
                logger.error(f"终端{self.index}: Socket.IO连接失败")
                return False
        except Exception as e:
            logger.error(f"终端{self.index}: Socket.IO连接异常: {e}")
            return False
    
    def run_command(self, command):
        """执行命令"""
        if not self.socket_client or not self.socket_connected:
            logger.error(f"终端{self.index}: Socket未连接")
            return False
            
        try:
            # 清空之前的输出
            self.stdout_received.clear()
            
            # 发送命令
            self.socket_client.emit("terminal_write", {
                "command": command
            })
            
            # 等待输出
            try:
                result = self.response_queue.get(timeout=10)
                return result == "output_received"
            except queue.Empty:
                logger.error(f"终端{self.index}: 命令执行超时")
                return False
                
        except Exception as e:
            logger.error(f"终端{self.index}: 命令执行异常: {e}")
            return False
    
    def disconnect(self):
        """断开连接"""
        if self.socket_client and self.socket_client.connected:
            self.socket_client.disconnect()
            time.sleep(1)

class MultiTerminalTest:
    """多终端测试"""
    def __init__(self):
        self.test_user_uuid = f"user-{uuid.uuid4()}"
        self.terminal_clients = []
        self.terminal_info = []
    
    def health_check(self):
        """健康检查"""
        logger.info("测试1: 健康检查接口")
        try:
            response = requests.get(BASE_URL)
            if response.status_code == 200:
                logger.success("✓ 健康检查接口正常")
                return True
            else:
                logger.error(f"✗ 健康检查接口异常，状态码: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"✗ 健康检查接口异常: {e}")
            return False
    
    def create_terminals(self):
        """创建多个终端"""
        logger.info(f"测试2: 创建{NUM_TERMINALS}个终端")
        try:
            for i in range(NUM_TERMINALS):
                # 生成随机token
                terminal_token = str(uuid.uuid4())
                
                response = requests.post(
                    f"{API_BASE_URL}/terminal/start",
                    headers={"X-API-Key": API_KEY},
                    json={
                        "user_uuid": self.test_user_uuid,
                        "token": terminal_token
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("success"):
                        item_uuid = result.get("item_uuid")
                        self.terminal_info.append({
                            "index": i,
                            "item_uuid": item_uuid,
                            "token": terminal_token
                        })
                        logger.success(f"✓ 终端{i}启动成功，item_uuid: {item_uuid}")
                    else:
                        logger.error(f"✗ 终端{i}启动失败: {result}")
                        return False
                else:
                    logger.error(f"✗ 终端{i}启动接口异常，状态码: {response.status_code}")
                    return False
            return True
        except Exception as e:
            logger.error(f"✗ 终端创建异常: {e}")
            return False
    
    def connect_clients(self):
        """连接所有终端客户端"""
        logger.info(f"测试3: 连接{NUM_TERMINALS}个终端客户端")
        try:
            threads = []
            results = []
            
            for info in self.terminal_info:
                client = TerminalClient(
                    info["index"],
                    self.test_user_uuid,
                    info["token"],
                    info["item_uuid"]
                )
                self.terminal_clients.append(client)
                
                # 使用线程并发连接
                def connect_thread(client, result_list):
                    result = client.connect()
                    result_list.append(result)
                
                thread = threading.Thread(
                    target=connect_thread,
                    args=(client, results)
                )
                threads.append(thread)
                thread.start()
            
            # 等待所有线程完成
            for thread in threads:
                thread.join()
            
            # 检查结果
            if all(results):
                logger.success(f"✓ 所有{NUM_TERMINALS}个终端客户端连接成功")
                return True
            else:
                logger.error(f"✗ 部分终端客户端连接失败")
                return False
        except Exception as e:
            logger.error(f"✗ 客户端连接异常: {e}")
            return False
    
    def run_commands(self):
        """在所有终端上执行命令"""
        logger.info(f"测试4: 在所有终端上执行命令")
        try:
            threads = []
            results = []
            
            for i, client in enumerate(self.terminal_clients):
                # 选择测试命令
                command = TEST_COMMANDS[i % len(TEST_COMMANDS)]
                
                # 使用线程并发执行命令
                def command_thread(client, command, result_list):
                    result = client.run_command(command)
                    result_list.append(result)
                
                thread = threading.Thread(
                    target=command_thread,
                    args=(client, command, results)
                )
                threads.append(thread)
                thread.start()
            
            # 等待所有线程完成
            for thread in threads:
                thread.join()
            
            # 检查结果
            if all(results):
                logger.success(f"✓ 所有{NUM_TERMINALS}个终端命令执行成功")
                return True
            else:
                logger.error(f"✗ 部分终端命令执行失败")
                return False
        except Exception as e:
            logger.error(f"✗ 命令执行异常: {e}")
            return False
    
    def disconnect_clients(self):
        """断开所有客户端连接"""
        logger.info(f"测试5: 断开所有终端客户端连接")
        try:
            for client in self.terminal_clients:
                client.disconnect()
            logger.success(f"✓ 所有终端客户端连接已断开")
            return True
        except Exception as e:
            logger.error(f"✗ 客户端断开异常: {e}")
            return False
    
    def stop_terminals(self):
        """停止所有终端"""
        logger.info(f"测试6: 停止所有终端")
        try:
            for info in self.terminal_info:
                response = requests.post(
                    f"{API_BASE_URL}/terminal/stop",
                    headers={"X-API-Key": API_KEY},
                    json={"item_uuid": info["item_uuid"]}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("success"):
                        logger.success(f"✓ 终端{info['index']}停止成功")
                    else:
                        logger.error(f"✗ 终端{info['index']}停止失败: {result}")
                else:
                    logger.error(f"✗ 终端{info['index']}停止接口异常，状态码: {response.status_code}")
            return True
        except Exception as e:
            logger.error(f"✗ 终端停止异常: {e}")
            return False
    
    def run_all_tests(self):
        """运行所有测试"""
        logger.info("=" * 50)
        logger.info("开始多终端连接测试")
        logger.info("=" * 50)
        
        # 测试结果记录
        results = []
        
        # 运行测试
        results.append(self.health_check())
        results.append(self.create_terminals())
        results.append(self.connect_clients())
        results.append(self.run_commands())
        results.append(self.disconnect_clients())
        results.append(self.stop_terminals())
        
        # 测试总结
        logger.info("=" * 50)
        logger.info("测试总结")
        logger.info("=" * 50)
        logger.info(f"总测试数: {len(results)}")
        logger.info(f"通过: {sum(results)}")
        logger.info(f"失败: {len(results) - sum(results)}")
        
        if all(results):
            logger.success(f"✓ 所有测试通过！")
        else:
            logger.error(f"✗ 部分测试失败，通过率: {sum(results)/len(results)*100:.1f}%")

# 主函数
if __name__ == "__main__":
    logger.info(f"[多终端连接测试]")
    logger.info(f"测试配置: {NUM_TERMINALS}个终端，同一端口")
    logger.info(f"Daemon地址: {BASE_URL}")
    logger.info(f"API Key: {API_KEY}")
    logger.info("=" * 50)
    
    # 创建测试实例
    test = MultiTerminalTest()
    
    # 运行测试
    test.run_all_tests()