import os
import sys
import time
import requests
import socketio
import uuid

# 测试配置
DAEMON_HOST = "127.0.0.1"
DAEMON_PORT = 9000
API_KEY = "termman_daemon_secret_key_2024"
BASE_URL = f"http://{DAEMON_HOST}:{DAEMON_PORT}"
API_BASE_URL = f"{BASE_URL}/api"

# 测试用户信息
TEST_USER_UUID = f"user-{uuid.uuid4()}"

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

class DaemonTester:
    """Daemon测试类"""
    def __init__(self):
        self.item_uuid = None
        self.terminal_token = None
        self.socket_client = None
        self.socket_connected = False
        self.stdout_received = []
    
    def test_health_check(self):
        """测试健康检查接口"""
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
    
    def test_start_terminal(self):
        """测试启动终端接口"""
        logger.info("测试2: 启动终端")
        try:
            # 生成随机token
            self.terminal_token = str(uuid.uuid4())
            
            response = requests.post(
                f"{API_BASE_URL}/terminal/start",
                headers={"X-API-Key": API_KEY},
                json={
                    "user_uuid": TEST_USER_UUID,
                    "token": self.terminal_token
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    self.item_uuid = result.get("item_uuid")
                    logger.success(f"✓ 终端启动成功，item_uuid: {self.item_uuid}")
                    return True
                else:
                    logger.error(f"✗ 终端启动失败: {result}")
                    return False
            else:
                logger.error(f"✗ 启动终端接口异常，状态码: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"✗ 启动终端异常: {e}")
            return False
    
    def test_get_terminal_status(self):
        """测试获取终端状态接口"""
        if not self.item_uuid:
            logger.warning("跳过状态测试，终端未创建")
            return False
            
        logger.info("测试3: 获取终端状态")
        try:
            response = requests.get(
                f"{API_BASE_URL}/terminal/status/{self.item_uuid}",
                headers={"X-API-Key": API_KEY}
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    status = result.get("data", {})
                    logger.success(f"✓ 终端状态获取成功，状态: {status.get('status')}")
                    return True
                else:
                    logger.error(f"✗ 终端状态获取失败: {result}")
                    return False
            else:
                logger.error(f"✗ 获取终端状态接口异常，状态码: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"✗ 获取终端状态异常: {e}")
            return False
    
    def test_socket_connection(self):
        """测试Socket.IO连接"""
        if not self.item_uuid or not self.terminal_token:
            logger.warning("跳过Socket连接测试，终端未创建")
            return False
            
        logger.info("测试4: Socket.IO连接")
        try:
            # 创建Socket.IO客户端
            self.socket_client = socketio.Client()
            
            # 事件处理
            @self.socket_client.event
            def connect():
                logger.info("Socket.IO已连接")
                
            @self.socket_client.event
            def disconnect():
                logger.info("Socket.IO已断开连接")
                self.socket_connected = False
            
            @self.socket_client.event
            def terminal_connected(data):
                logger.success("✓ 终端Socket连接成功")
                self.socket_connected = True
            
            @self.socket_client.event
            def auth_error(data):
                logger.error(f"✗ 终端Socket认证失败: {data}")
                self.socket_connected = False
            
            @self.socket_client.event
            def stream(data):
                output = data.get("stdout", "")
                if output:
                    self.stdout_received.append(output)
                    logger.info(f"终端输出: {output.strip()}")
            
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
                time.sleep(2)
                if self.socket_connected:
                    return True
                else:
                    logger.error("✗ 终端Socket连接超时")
                    return False
            else:
                logger.error("✗ Socket.IO连接失败")
                return False
                
        except Exception as e:
            logger.error(f"✗ Socket.IO连接异常: {e}")
            return False
    
    def test_terminal_interaction(self):
        """测试终端交互"""
        if not self.socket_client or not self.socket_connected:
            logger.warning("跳过终端交互测试，Socket未连接")
            return False
            
        logger.info("测试5: 终端交互 (执行ping命令)")
        try:
            # 清空之前的输出
            self.stdout_received.clear()
            
            # 发送ping命令 (Windows使用ping -n 2 127.0.0.1)
            self.socket_client.emit("terminal_write", {
                "command": "ping -n 2 127.0.0.1"
            })
            
            # 等待输出
            time.sleep(5)
            
            # 检查是否收到输出
            if len(self.stdout_received) > 0:
                logger.success("✓ 终端交互成功，收到输出")
                return True
            else:
                logger.error("✗ 终端交互失败，未收到输出")
                return False
                
        except Exception as e:
            logger.error(f"✗ 终端交互异常: {e}")
            return False
    
    def test_disconnect_socket(self):
        """测试断开Socket连接"""
        if not self.socket_client:
            logger.warning("跳过Socket断开测试，Socket未创建")
            return False
            
        logger.info("测试6: 断开Socket连接")
        try:
            if self.socket_client.connected:
                self.socket_client.disconnect()
                time.sleep(1)
                if not self.socket_client.connected:
                    logger.success("✓ Socket连接已断开")
                    return True
                else:
                    logger.error("✗ Socket连接未断开")
                    return False
            else:
                logger.success("✓ Socket连接已断开")
                return True
                
        except Exception as e:
            logger.error(f"✗ 断开Socket连接异常: {e}")
            return False
    
    def test_stop_terminal(self):
        """测试停止终端接口"""
        if not self.item_uuid:
            logger.warning("跳过停止终端测试，终端未创建")
            return False
            
        logger.info("测试7: 停止终端")
        try:
            response = requests.post(
                f"{API_BASE_URL}/terminal/stop",
                headers={"X-API-Key": API_KEY},
                json={"item_uuid": self.item_uuid}
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
                logger.error(f"✗ 停止终端接口异常，状态码: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"✗ 停止终端异常: {e}")
            return False
    
    def test_list_terminals(self):
        """测试获取终端列表接口"""
        logger.info("测试8: 获取终端列表")
        try:
            response = requests.get(
                f"{API_BASE_URL}/terminal/list",
                headers={"X-API-Key": API_KEY}
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    terminal_count = result.get("count", 0)
                    logger.success(f"✓ 终端列表获取成功，当前终端数: {terminal_count}")
                    return True
                else:
                    logger.error(f"✗ 终端列表获取失败: {result}")
                    return False
            else:
                logger.error(f"✗ 获取终端列表接口异常，状态码: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"✗ 获取终端列表异常: {e}")
            return False
    
    def run_all_tests(self):
        """运行所有测试"""
        logger.info("=" * 50)
        logger.info("开始测试 TermMan Daemon")
        logger.info("=" * 50)
        
        # 测试结果记录
        results = []
        
        # 运行测试
        results.append(self.test_health_check())
        results.append(self.test_start_terminal())
        results.append(self.test_get_terminal_status())
        results.append(self.test_socket_connection())
        results.append(self.test_terminal_interaction())
        results.append(self.test_disconnect_socket())
        results.append(self.test_stop_terminal())
        results.append(self.test_list_terminals())
        
        # 总结测试结果
        logger.info("=" * 50)
        logger.info("测试总结")
        logger.info("=" * 50)
        
        total_tests = len(results)
        passed_tests = sum(results)
        failed_tests = total_tests - passed_tests
        
        logger.info(f"总测试数: {total_tests}")
        logger.info(f"通过: {passed_tests}")
        logger.info(f"失败: {failed_tests}")
        
        if passed_tests == total_tests:
            logger.success("✓ 所有测试通过！")
        else:
            logger.error(f"✗ 部分测试失败，通过率: {passed_tests/total_tests*100:.1f}%")
        
        # 清理资源
        if self.socket_client and self.socket_client.connected:
            self.socket_client.disconnect()
        
        return passed_tests == total_tests

if __name__ == "__main__":
    logger.info("请确保Daemon服务已启动在 {}:{}".format(DAEMON_HOST, DAEMON_PORT))
    logger.info(f"使用API Key: {API_KEY}")
    logger.info("")
    
    # 运行测试
    tester = DaemonTester()
    success = tester.run_all_tests()
    
    # 退出状态码
    sys.exit(0 if success else 1)
