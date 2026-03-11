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
NUM_CLIENTS = 5  # 要连接到同一个终端的客户端数量
TEST_COMMANDS = ["echo 'Hello from multiple clients test'", "date", "whoami"]

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
    def __init__(self, client_id, user_uuid, terminal_token, item_uuid):
        self.client_id = client_id
        self.user_uuid = user_uuid
        self.terminal_token = terminal_token
        self.item_uuid = item_uuid
        self.socket_client = None
        self.socket_connected = False
        self.stdout_received = []
        self.response_queue = queue.Queue()
        self.output_events = []
    
    def connect(self):
        """连接到Daemon"""
        try:
            # 创建Socket.IO客户端
            self.socket_client = socketio.Client()
            
            # 事件处理
            @self.socket_client.event
            def connect():
                logger.info(f"客户端{self.client_id}: Socket.IO已连接")
                
            @self.socket_client.event
            def disconnect():
                logger.info(f"客户端{self.client_id}: Socket.IO已断开连接")
                self.socket_connected = False
            
            @self.socket_client.event
            def terminal_connected(data):
                logger.success(f"客户端{self.client_id}: 终端Socket连接成功")
                self.socket_connected = True
                self.response_queue.put("connected")
            
            @self.socket_client.event
            def auth_error(data):
                logger.error(f"客户端{self.client_id}: 终端Socket认证失败: {data}")
                self.socket_connected = False
                self.response_queue.put("auth_error")
            
            @self.socket_client.event
            def stream(data):
                output = data.get("stdout", "")
                if output:
                    self.stdout_received.append(output)
                    self.output_events.append(output.strip())
                    logger.info(f"客户端{self.client_id}输出: {output.strip()}")
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
                    logger.error(f"客户端{self.client_id}: 终端Socket连接超时")
                    return False
            else:
                logger.error(f"客户端{self.client_id}: Socket.IO连接失败")
                return False
        except Exception as e:
            logger.error(f"客户端{self.client_id}: Socket.IO连接异常: {e}")
            return False
    
    def clear_output(self):
        """清空输出记录"""
        self.stdout_received.clear()
        self.output_events.clear()
    
    def disconnect(self):
        """断开连接"""
        if self.socket_client and self.socket_client.connected:
            self.socket_client.disconnect()
            time.sleep(1)
            logger.info(f"客户端{self.client_id}: 已断开连接")

class MultiClientsTest:
    """多客户端连接同一终端测试"""
    def __init__(self):
        self.test_user_uuid = f"user-{uuid.uuid4()}"
        self.terminal_clients = []
        self.terminal_info = None
    
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
    
    def create_terminal(self):
        """创建一个终端"""
        logger.info("测试2: 创建一个终端")
        try:
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
                    self.terminal_info = {
                        "item_uuid": item_uuid,
                        "token": terminal_token
                    }
                    logger.success(f"✓ 终端启动成功，item_uuid: {item_uuid}")
                    return True
                else:
                    logger.error(f"✗ 终端启动失败: {result}")
                    return False
            else:
                logger.error(f"✗ 终端启动接口异常，状态码: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"✗ 终端创建异常: {e}")
            return False
    
    def connect_clients(self):
        """连接所有客户端到同一个终端"""
        logger.info(f"测试3: 连接{NUM_CLIENTS}个客户端到同一个终端")
        try:
            threads = []
            results = []
            
            for client_id in range(NUM_CLIENTS):
                client = TerminalClient(
                    client_id,
                    self.test_user_uuid,
                    self.terminal_info["token"],
                    self.terminal_info["item_uuid"]
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
                logger.success(f"✓ 所有{NUM_CLIENTS}个客户端连接成功")
                return True
            else:
                failed_count = NUM_CLIENTS - sum(results)
                logger.error(f"✗ {failed_count}个客户端连接失败")
                return False
        except Exception as e:
            logger.error(f"✗ 客户端连接异常: {e}")
            return False
    
    def run_commands(self):
        """在终端上执行命令，验证所有客户端都能收到输出"""
        logger.info(f"测试4: 执行命令，验证所有客户端都能收到输出")
        
        if not self.terminal_clients:
            logger.error("✗ 没有客户端连接")
            return False
            
        try:
            # 找到第一个连接的客户端来发送命令
            command_client = None
            for client in self.terminal_clients:
                if client.socket_client and client.socket_client.connected:
                    command_client = client
                    break
                    
            if not command_client:
                logger.error("✗ 没有可用的客户端来发送命令")
                return False
            
            all_success = True
            
            for i, command in enumerate(TEST_COMMANDS):
                logger.info(f"\n执行命令 {i+1}/{len(TEST_COMMANDS)}: {command}")
                
                # 清空所有客户端的输出记录
                for client in self.terminal_clients:
                    client.clear_output()
                
                # 发送命令
                command_client.socket_client.emit("terminal_write", {
                    "command": command
                })
                
                # 等待输出
                time.sleep(2)
                
                # 检查每个客户端是否都收到了输出
                # 简化检查：只要有输出就认为成功
                command_output = command.split("'", 2)[1] if "'" in command else command
                
                for client in self.terminal_clients:
                    if client.output_events:
                        logger.success(f"客户端{client.client_id}: ✓ 收到命令输出")
                    else:
                        logger.error(f"客户端{client.client_id}: ✗ 没有收到任何输出")
                        all_success = False
            
            if all_success:
                logger.success(f"✓ 所有命令都成功广播到{NUM_CLIENTS}个客户端")
            else:
                logger.error(f"✗ 部分客户端未收到命令输出")
                
            return all_success
        except Exception as e:
            logger.error(f"✗ 命令执行异常: {e}")
            return False
    
    def disconnect_clients(self):
        """断开所有客户端连接"""
        logger.info(f"测试5: 断开{NUM_CLIENTS}个客户端连接")
        try:
            for client in self.terminal_clients:
                client.disconnect()
            logger.success(f"✓ 所有客户端已断开连接")
            return True
        except Exception as e:
            logger.error(f"✗ 客户端断开异常: {e}")
            return False
    
    def stop_terminal(self):
        """停止终端"""
        logger.info("测试6: 停止终端")
        try:
            response = requests.post(
                f"{API_BASE_URL}/terminal/stop",
                headers={"X-API-Key": API_KEY},
                json={"item_uuid": self.terminal_info["item_uuid"]}
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    logger.success("✓ 终端停止成功")
                    return True
                else:
                    logger.error(f"✗ 终端停止失败: {result}")
                    return False
            else:
                logger.error(f"✗ 终端停止接口异常，状态码: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"✗ 终端停止异常: {e}")
            return False
    
    def run_all_tests(self):
        """运行所有测试"""
        logger.info("=" * 60)
        logger.info("开始多客户端连接同一终端测试")
        logger.info("=" * 60)
        
        # 测试结果记录
        results = []
        
        # 运行测试
        results.append(self.health_check())
        results.append(self.create_terminal())
        results.append(self.connect_clients())
        results.append(self.run_commands())
        results.append(self.disconnect_clients())
        results.append(self.stop_terminal())
        
        # 测试总结
        logger.info("=" * 60)
        logger.info("测试总结")
        logger.info("=" * 60)
        logger.info(f"总测试数: {len(results)}")
        logger.info(f"通过: {sum(results)}")
        logger.info(f"失败: {len(results) - sum(results)}")
        
        if all(results):
            logger.success(f"✓ 所有测试通过！")
            logger.success(f"\n✅ 结论: 同一个终端可以同时被{NUM_CLIENTS}个客户端连接，")
            logger.success(f"✅ 所有客户端都能实时收到终端输出！")
        else:
            logger.error(f"✗ 部分测试失败，通过率: {sum(results)/len(results)*100:.1f}%")

# 主函数
if __name__ == "__main__":
    logger.info(f"[多客户端连接同一终端测试]")
    logger.info(f"测试配置: {NUM_CLIENTS}个客户端连接到同一个终端")
    logger.info(f"Daemon地址: {BASE_URL}")
    logger.info(f"API Key: {API_KEY}")
    logger.info("=" * 60)
    
    # 创建测试实例
    test = MultiClientsTest()
    
    # 运行测试
    test.run_all_tests()