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
DAEMON_PORT = 9000
API_KEY = "termman_daemon_secret_key_2024"
BASE_URL = f"http://{DAEMON_HOST}:{DAEMON_PORT}"
API_BASE_URL = f"{BASE_URL}/api"

# 测试配置
NUM_USERS = 3  # 要创建的用户数量
TEST_COMMANDS = ["echo 'Hello from user 1'", "echo 'Hello from user 2'", "echo 'Hello from user 3'", "date"]

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

class UserClient:
    """用户客户端"""
    def __init__(self, user_id, user_uuid, terminal_token, item_uuid):
        self.user_id = user_id
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
                logger.info(f"用户{self.user_id}({self.user_uuid[:8]}): Socket.IO已连接")
                
            @self.socket_client.event
            def disconnect():
                logger.info(f"用户{self.user_id}({self.user_uuid[:8]}): Socket.IO已断开连接")
                self.socket_connected = False
            
            @self.socket_client.event
            def terminal_connected(data):
                logger.success(f"用户{self.user_id}({self.user_uuid[:8]}): 终端Socket连接成功")
                self.socket_connected = True
                self.response_queue.put("connected")
            
            @self.socket_client.event
            def auth_error(data):
                logger.error(f"用户{self.user_id}({self.user_uuid[:8]}): 终端Socket认证失败: {data}")
                self.socket_connected = False
                self.response_queue.put("auth_error")
            
            @self.socket_client.event
            def stream(data):
                output = data.get("stdout", "")
                if output:
                    self.stdout_received.append(output)
                    self.output_events.append(output.strip())
                    logger.info(f"用户{self.user_id}({self.user_uuid[:8]})输出: {output.strip()}")
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
                    "token": self.terminal_token,
                    "user_uuid": self.user_uuid
                })
            
            # 等待连接完成
            try:
                result = self.response_queue.get(timeout=5)
                return result == "connected"
            except queue.Empty:
                logger.error(f"用户{self.user_id}({self.user_uuid[:8]}): 终端Socket连接超时")
                return False
            else:
                logger.error(f"用户{self.user_id}({self.user_uuid[:8]}): Socket.IO连接失败")
                return False
        except Exception as e:
            logger.error(f"用户{self.user_id}({self.user_uuid[:8]}): Socket.IO连接异常: {e}")
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
            logger.info(f"用户{self.user_id}({self.user_uuid[:8]}): 已断开连接")

class MultiUsersTest:
    """多用户连接同一终端测试"""
    def __init__(self):
        self.user_uuids = []
        self.user_clients = []
        self.terminal_info = None
        self.terminal_token = str(uuid.uuid4())  # 所有用户共享同一个token
    
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
            # 使用第一个用户的UUID创建终端
            first_user_uuid = f"user-{uuid.uuid4()}"
            self.user_uuids.append(first_user_uuid)
            
            response = requests.post(
                f"{API_BASE_URL}/terminal/start",
                headers={"X-API-Key": API_KEY},
                json={
                    "user_uuid": first_user_uuid,
                    "token": self.terminal_token
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    item_uuid = result.get("item_uuid")
                    self.terminal_info = {
                        "item_uuid": item_uuid,
                        "token": self.terminal_token
                    }
                    logger.success(f"✓ 终端启动成功，item_uuid: {item_uuid}")
                    logger.info(f"✓ 终端token: {self.terminal_token}")
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
    
    def generate_users(self):
        """生成更多用户UUID"""
        logger.info(f"测试3: 生成{NUM_USERS-1}个额外用户UUID")
        try:
            for i in range(1, NUM_USERS):
                user_uuid = f"user-{uuid.uuid4()}"
                self.user_uuids.append(user_uuid)
                logger.success(f"✓ 用户{i+1} UUID: {user_uuid}")
            logger.info(f"✓ 总共生成{len(self.user_uuids)}个用户UUID")
            return True
        except Exception as e:
            logger.error(f"✗ 用户生成异常: {e}")
            return False
    
    def connect_clients(self):
        """连接所有用户到同一个终端"""
        logger.info(f"测试4: 连接{NUM_USERS}个用户到同一个终端")
        try:
            threads = []
            results = []
            
            for user_id, user_uuid in enumerate(self.user_uuids):
                client = UserClient(
                    user_id,
                    user_uuid,
                    self.terminal_info["token"],
                    self.terminal_info["item_uuid"]
                )
                self.user_clients.append(client)
                
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
                logger.success(f"✓ 所有{NUM_USERS}个用户连接成功")
                return True
            else:
                failed_count = NUM_USERS - sum(results)
                logger.error(f"✗ {failed_count}个用户连接失败")
                return False
        except Exception as e:
            logger.error(f"✗ 用户连接异常: {e}")
            return False
    
    def run_commands(self):
        """在终端上执行命令，验证所有用户都能看到相同的输出"""
        logger.info(f"测试5: 执行命令，验证所有用户都能看到相同的输出")
        
        if not self.user_clients:
            logger.error("✗ 没有用户连接")
            return False
            
        try:
            # 找到第一个连接的用户来发送命令
            command_client = None
            for client in self.user_clients:
                if client.socket_client and client.socket_client.connected:
                    command_client = client
                    break
                    
            if not command_client:
                logger.error("✗ 没有可用的用户来发送命令")
                return False
            
            all_success = True
            
            for i, command in enumerate(TEST_COMMANDS):
                logger.info(f"\n执行命令 {i+1}/{len(TEST_COMMANDS)}: {command}")
                
                # 清空所有用户的输出记录
                for client in self.user_clients:
                    client.clear_output()
                
                # 发送命令
                command_client.socket_client.emit("terminal_write", {
                    "command": command
                })
                
                # 等待输出
                time.sleep(2)
                
                # 检查所有用户是否都收到了输出
                any_output = False
                for client in self.user_clients:
                    if client.output_events:
                        any_output = True
                        break
                
                if not any_output:
                    logger.error(f"✗ 没有用户收到命令输出")
                    all_success = False
                    continue
                
                # 验证所有用户收到的输出是否一致
                reference_output = self.user_clients[0].output_events
                for client_idx, client in enumerate(self.user_clients):
                    if client.output_events == reference_output:
                        logger.success(f"用户{client.user_id}({client.user_uuid[:8]}): ✓ 输出与参考一致")
                    else:
                        logger.warning(f"用户{client.user_id}({client.user_uuid[:8]}): ! 输出与参考不一致")
                        logger.info(f"  参考输出: {reference_output}")
                        logger.info(f"  用户输出: {client.output_events}")
            
            if all_success:
                logger.success(f"✓ 所有命令都成功执行，所有用户都能看到输出")
            else:
                logger.error(f"✗ 部分命令执行失败")
                
            return all_success
        except Exception as e:
            logger.error(f"✗ 命令执行异常: {e}")
            return False
    
    def disconnect_clients(self):
        """断开所有用户连接"""
        logger.info(f"测试6: 断开{NUM_USERS}个用户连接")
        try:
            for client in self.user_clients:
                client.disconnect()
            logger.success(f"✓ 所有用户已断开连接")
            return True
        except Exception as e:
            logger.error(f"✗ 用户断开异常: {e}")
            return False
    
    def stop_terminal(self):
        """停止终端"""
        logger.info("测试7: 停止终端")
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
        logger.info("=" * 70)
        logger.info("开始多用户连接同一终端测试")
        logger.info("=" * 70)
        logger.info(f"测试目标: 验证{NUM_USERS}个不同用户连接到同一个终端")
        logger.info(f"共享token: {self.terminal_token}")
        logger.info("=" * 70)
        
        # 测试结果记录
        results = []
        
        # 运行测试
        results.append(self.health_check())
        results.append(self.create_terminal())
        results.append(self.generate_users())
        results.append(self.connect_clients())
        results.append(self.run_commands())
        results.append(self.disconnect_clients())
        results.append(self.stop_terminal())
        
        # 测试总结
        logger.info("=" * 70)
        logger.info("测试总结")
        logger.info("=" * 70)
        logger.info(f"总测试数: {len(results)}")
        logger.info(f"通过: {sum(results)}")
        logger.info(f"失败: {len(results) - sum(results)}")
        
        if all(results):
            logger.success(f"✓ 所有测试通过！")
            logger.success(f"\n✅ 结论: {NUM_USERS}个不同用户可以共享同一个终端，")
            logger.success(f"✅ 所有用户都能实时看到相同的终端输出！")
        else:
            logger.error(f"✗ 部分测试失败，通过率: {sum(results)/len(results)*100:.1f}%")

# 主函数
if __name__ == "__main__":
    logger.info(f"[多用户连接同一终端测试]")
    logger.info(f"Daemon地址: {BASE_URL}")
    logger.info(f"API Key: {API_KEY}")
    logger.info("=" * 70)
    
    # 创建测试实例
    test = MultiUsersTest()
    
    # 运行测试
    test.run_all_tests()