import sys
import os
import time
import uuid
from typing import List

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.terminal_service import TerminalService
from app.services.connection_pool import ConnectionManager, DaemonConfig
from app.services.socket_pool import SocketManager
from app.services.socket_pool.subscriber_sdk import ItemSubscriberSDK
from app.services.connection_handler import ConnectionHandler

# 测试配置
DAEMON_HOST = "127.0.0.1"
DAEMON_PORT = 9000
API_KEY = "termman_daemon_secret_key_2024"
BASE_URL = f"http://{DAEMON_HOST}:{DAEMON_PORT}"

# 测试命令
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

class TestTerminalService:
    """使用TerminalService测试与Daemon的通信"""
    
    def __init__(self):
        # 初始化服务
        self.connection_manager = ConnectionManager()
        self.socket_manager = SocketManager()
        self.connection_handler = ConnectionHandler(self.connection_manager, self.socket_manager)
        self.terminal_service = TerminalService(
            self.connection_manager,
            self.socket_manager,
            self.connection_handler
        )
        
        # 测试数据
        self.daemon_id = "test-daemon-1"
        self.item_uuid = f"item-{uuid.uuid4()}"
        self.user_uuids = [f"user-{uuid.uuid4()}" for _ in range(3)]
        self.terminal_token = None
        self.daemon_url = BASE_URL
        self.connected_sockets = []
        self.terminal_output = []  # 存储终端输出
    
    def setup_daemon_connection(self):
        """设置Daemon连接"""
        logger.info("测试1: 设置Daemon连接")
        try:
            # 创建Daemon配置
            daemon_config = DaemonConfig(
                daemon_id=self.daemon_id,
                ip=DAEMON_HOST,
                port=DAEMON_PORT,
                api_key=API_KEY
            )
            
            # 连接到Daemon
            connection = self.connection_manager.get_or_create_connection(daemon_config)
            
            if connection and connection.is_connected():
                logger.success("✓ Daemon连接成功")
                return True
            else:
                logger.error("✗ Daemon连接失败")
                return False
        except Exception as e:
            logger.error(f"✗ Daemon连接异常: {e}")
            return False
    
    def start_terminal(self):
        """启动终端"""
        logger.info("测试2: 启动终端")
        try:
            # 创建Daemon配置
            daemon_config = DaemonConfig(
                daemon_id=self.daemon_id,
                ip=DAEMON_HOST,
                port=DAEMON_PORT,
                api_key=API_KEY
            )
            
            # 使用第一个用户的UUID创建终端
            result = self.terminal_service.start_terminal(
                self.item_uuid,
                self.user_uuids[0],
                daemon_config
            )
            
            if result.get("success"):
                # 更新item_uuid和token
                self.item_uuid = result.get("item_uuid")
                self.terminal_token = result.get("token")
                logger.success(f"✓ 终端启动成功，item_uuid: {self.item_uuid}")
                logger.info(f"✓ 终端token: {self.terminal_token}")
                return True
            else:
                logger.error(f"✗ 终端启动失败: {result}")
                return False
        except Exception as e:
            logger.error(f"✗ 终端启动异常: {e}")
            return False
    
    def connect_users_to_terminal(self):
        """连接多个用户到终端"""
        logger.info(f"测试3: 连接{len(self.user_uuids)}个用户到终端")
        try:
            connected_users = []
            
            for user_idx, user_uuid in enumerate(self.user_uuids):
                logger.info(f"连接用户{user_idx+1}({user_uuid[:8]})...")
                
                # 连接到终端
                result = self.terminal_service.connect_terminal(
                    self.item_uuid,
                    self.terminal_token,
                    self.daemon_url,
                    user_uuid,
                    API_KEY
                )
                
                if result:
                    logger.success(f"✓ 用户{user_idx+1}连接成功")
                    connected_users.append(user_idx)
                else:
                    logger.error(f"✗ 用户{user_idx+1}连接失败")
                
                # 给每个连接一些时间
                time.sleep(1)
            
            if connected_users:
                logger.success(f"✓ 总共{len(connected_users)}个用户连接成功")
                return True
            else:
                logger.error("✗ 没有用户连接成功")
                return False
        except Exception as e:
            logger.error(f"✗ 用户连接异常: {e}")
            return False
    
    def run_commands(self):
        """在终端上执行命令"""
        logger.info("测试4: 执行命令")
        try:
            sdk = ItemSubscriberSDK()
            
            def stream_callback(event):
                data = event.data
                output = data.get("stdout", "")
                if output:
                    self.terminal_output.append(output)
                    logger.info(f"终端输出: {output.strip()}")
                stderr = data.get("stderr", "")
                if stderr:
                    self.terminal_output.append(stderr)
                    logger.error(f"终端错误: {stderr.strip()}")
            
            sdk.subscribe_stream(self.item_uuid, stream_callback)
            
            all_success = True
            
            for i, command in enumerate(TEST_COMMANDS):
                logger.info(f"\n执行命令 {i+1}/{len(TEST_COMMANDS)}: {command}")
                
                # 清空终端输出
                self.terminal_output = []
                
                # 执行命令
                result = self.terminal_service.write_to_terminal(self.item_uuid, command)
                
                if result:
                    logger.success(f"✓ 命令执行成功")
                    # 等待命令输出
                    time.sleep(2)
                    
                    # 检查是否有输出
                    if self.terminal_output:
                        logger.info("✓ 成功获取终端输出")
                    else:
                        logger.warning("! 未获取到终端输出")
                else:
                    logger.error(f"✗ 命令执行失败")
                    all_success = False
            
            return all_success
        except Exception as e:
            logger.error(f"✗ 命令执行异常: {e}")
            return False
    
    def get_terminal_status(self):
        """查询终端状态"""
        logger.info("测试5: 查询终端状态")
        try:
            result = self.terminal_service.get_terminal_status(self.daemon_id, self.item_uuid)
            
            if result.get("success"):
                logger.success(f"✓ 终端状态查询成功: {result}")
                return True
            else:
                logger.error(f"✗ 终端状态查询失败: {result}")
                return False
        except Exception as e:
            logger.error(f"✗ 终端状态查询异常: {e}")
            return False
    
    def stop_terminal(self):
        """停止终端"""
        logger.info("测试6: 停止终端")
        try:
            result = self.terminal_service.stop_terminal(self.daemon_id, self.item_uuid)
            
            if result.get("success"):
                logger.success(f"✓ 终端停止成功")
                return True
            else:
                logger.error(f"✗ 终端停止失败: {result}")
                return False
        except Exception as e:
            logger.error(f"✗ 终端停止异常: {e}")
            return False
    
    def run_all_tests(self):
        """运行所有测试"""
        logger.info("=" * 70)
        logger.info("开始测试Terminal Service")
        logger.info("=" * 70)
        logger.info(f"测试目标: 验证多用户连接同一终端")
        logger.info("=" * 70)
        
        # 测试结果记录
        results = []
        
        # 运行测试
        results.append(self.setup_daemon_connection())
        results.append(self.start_terminal())
        results.append(self.connect_users_to_terminal())
        results.append(self.run_commands())
        results.append(self.get_terminal_status())
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
            logger.success(f"\n✅ 结论: 使用修改后的services层方法成功实现了多用户连接同一终端的功能")
        else:
            logger.error(f"✗ 部分测试失败，通过率: {sum(results)/len(results)*100:.1f}%")

if __name__ == "__main__":
    logger.info(f"[Terminal Service 测试]")
    logger.info(f"Daemon地址: {BASE_URL}")
    logger.info(f"API Key: {API_KEY}")
    logger.info("=" * 70)
    
    # 创建测试实例
    test = TestTerminalService()
    
    # 运行测试
    test.run_all_tests()
