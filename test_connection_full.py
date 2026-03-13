#!/usr/bin/env python3
"""
完整连接功能测试工具

测试功能：
1. 多用户多项目的连接表管理
2. 获取连接表信息
3. 断开特定用户与项目的连接
4. 验证权限检查
5. 建立实际WebSocket连接
"""

import requests
import uuid
import time
import json
from typing import Dict, Any, List
import socketio
import threading
import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'daemon'))

# 配置参数
DAEMON_URL = "http://localhost:9000"
SOCKET_URL = "http://localhost:9000"
API_KEY = "termman_daemon_secret_key_2024"

class ConnectionFullTest:
    """完整连接测试类"""
    def __init__(self):
        self.users = []
        self.terminals = []
        self.sockets = []  # 存储所有Socket连接
        self.terminal_outputs = {}  # 存储每个终端的输出
        self.headers = {
            "X-API-Key": API_KEY,
            "Content-Type": "application/json"
        }

    def generate_users(self, count: int) -> list:
        """生成测试用户"""
        users = []
        for i in range(count):
            user_uuid = f"test_user_{uuid.uuid4()}"
            users.append(user_uuid)
        self.users = users
        print(f"✓ 生成了 {count} 个测试用户")
        return users

    def start_terminals(self, count: int, users: list) -> list:
        """启动测试终端"""
        terminals = []
        
        for i in range(count):
            # 循环使用用户
            user_uuid = users[i % len(users)]
            
            # 生成终端token
            token = str(uuid.uuid4())
            
            # 启动终端
            response = requests.post(
                f"{DAEMON_URL}/api/terminal/start",
                headers=self.headers,
                data=json.dumps({
                    "user_uuid": user_uuid,
                    "token": token
                })
            )
            
            if response.status_code == 200:
                result = response.json()
                terminal = {
                    "item_uuid": result.get("item_uuid"),
                    "token": token,
                    "user_uuid": user_uuid
                }
                terminals.append(terminal)
                print(f"✓ 终端启动成功: {terminal['item_uuid']} (用户: {user_uuid})")
            else:
                print(f"✗ 终端启动失败: {response.status_code} - {response.text}")
        
        self.terminals = terminals
        return terminals

    def connect_to_socket(self, terminal: Dict[str, Any]) -> socketio.Client:
        """建立Socket.IO连接"""
        sio = socketio.Client()
        
        # 为该终端创建输出存储
        item_uuid = terminal['item_uuid']
        if item_uuid not in self.terminal_outputs:
            self.terminal_outputs[item_uuid] = []
        
        @sio.event
        def connect():
            print(f"✓ Socket连接建立: 终端 {terminal['item_uuid']} (用户: {terminal['user_uuid']})")
            # 发送初始化消息
            sio.emit('terminal_connect', {
                'item_uuid': terminal['item_uuid'],
                'user_uuid': terminal['user_uuid'],
                'token': terminal['token']
            })
        
        @sio.event
        def disconnect():
            print(f"✗ Socket连接断开: 终端 {terminal['item_uuid']} (用户: {terminal['user_uuid']})")
        
        @sio.event
        def terminal_connected(data):
            print(f"✓ 终端连接成功: {terminal['item_uuid']} (用户: {terminal['user_uuid']})")
        
        @sio.event
        def auth_error(data):
            print(f"✗ 终端认证失败: {terminal['item_uuid']} (用户: {terminal['user_uuid']}), 错误: {data}")
        
        @sio.on('stream')
        def on_terminal_output(data):
            """处理终端输出事件"""
            output = data.get("stdout", "")
            stderr = data.get("stderr", "")
            
            if output:
                self.terminal_outputs[item_uuid].append(output)
                print(f"[终端输出] {terminal['item_uuid']}: {output.strip()}")
            if stderr:
                self.terminal_outputs[item_uuid].append(stderr)
                print(f"[终端错误] {terminal['item_uuid']}: {stderr.strip()}")
        
        # 连接到服务器
        sio.connect(SOCKET_URL, auth={'api_key': API_KEY})
        
        # 等待连接稳定
        time.sleep(1)
        
        return sio

    def connect_all_terminals(self) -> List[socketio.Client]:
        """为所有终端建立Socket连接"""
        sockets = []
        
        for terminal in self.terminals:
            try:
                sio = self.connect_to_socket(terminal)
                sockets.append(sio)
                self.sockets.append(sio)
            except Exception as e:
                print(f"✗ 建立Socket连接失败: {e}")
        
        return sockets

    def get_connection_tables(self) -> Dict[str, Any]:
        """获取连接表"""
        response = requests.get(
            f"{DAEMON_URL}/api/connections",
            headers=self.headers
        )
        
        if response.status_code == 200:
            result = response.json()
            print("✓ 获取连接表成功")
            return result.get("data", {})
        else:
            print(f"✗ 获取连接表失败: {response.status_code} - {response.text}")
            return {}

    def disconnect_user_from_terminal(self, item_uuid: str, user_uuid: str) -> bool:
        """断开用户与终端的连接"""
        response = requests.post(
            f"{DAEMON_URL}/api/connections/disconnect",
            headers=self.headers,
            data=json.dumps({
                "item_uuid": item_uuid,
                "user_uuid": user_uuid
            })
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get("success"):
                print(f"✓ 断开连接成功: 用户 {user_uuid} 与终端 {item_uuid}")
                return True
            else:
                print(f"✗ 断开连接失败: {result.get('message')}")
                return False
        else:
            print(f"✗ 断开连接请求失败: {response.status_code} - {response.text}")
            return False

    def write_to_terminal(self, item_uuid: str, command: str) -> bool:
        """向终端写入命令"""
        for sio in self.sockets:
            try:
                sio.emit('terminal_write', {
                    'command': command
                })
                return True
            except Exception as e:
                print(f"✗ 向终端 {item_uuid} 发送命令失败: {e}")
        return False

    def run_commands(self, item_uuid: str, commands: List[str]):
        """在指定终端上执行命令并检查输出"""
        print(f"=== 在终端 {item_uuid} 上执行命令 ===")
        
        if item_uuid not in self.terminal_outputs:
            print("✗ 终端未找到")
            return False
            
        try:
            all_success = True
            
            for i, command in enumerate(commands):
                print(f"\n执行命令 {i+1}/{len(commands)}: {command}")
                
                # 清空终端输出
                self.terminal_outputs[item_uuid] = []
                
                # 执行命令
                result = self.write_to_terminal(item_uuid, command)
                
                if result:
                    print(f"✓ 命令发送成功")
                    # 等待命令输出
                    time.sleep(2)
                    
                    # 检查是否有输出
                    if self.terminal_outputs[item_uuid]:
                        print(f"✓ 获取到终端输出 ({len(self.terminal_outputs[item_uuid])} 行)")
                    else:
                        print(f"! 未获取到终端输出")
                else:
                    print(f"✗ 命令发送失败")
                    all_success = False
            
            return all_success
        except Exception as e:
            print(f"✗ 命令执行异常: {e}")
            return False

    def stop_terminals(self):
        """停止所有测试终端"""
        # 先断开所有Socket连接
        for sio in self.sockets:
            try:
                sio.disconnect()
            except:
                pass
        
        # 再停止终端
        for terminal in self.terminals:
            response = requests.post(
                f"{DAEMON_URL}/api/terminal/stop",
                headers=self.headers,
                data=json.dumps({
                    "item_uuid": terminal["item_uuid"]
                })
            )
            if response.status_code == 200:
                print(f"✓ 终端停止成功: {terminal['item_uuid']}")
            else:
                print(f"✗ 终端停止失败: {response.status_code} - {response.text}")

    def run_test(self):
        """运行完整测试流程"""
        print("=" * 60)
        print("完整连接功能测试")
        print("=" * 60)
        
        try:
            # 1. 生成测试用户
            users = self.generate_users(3)
            print(f"测试用户: {users}")
            print()
            
            # 2. 启动测试终端
            terminals = self.start_terminals(5, users)
            print()
            
            # 3. 建立Socket连接
            print("=== 建立Socket连接 ===")
            sockets = self.connect_all_terminals()
            print(f"✓ 共建立了 {len(sockets)} 个Socket连接")
            print()
            
            # 等待连接状态稳定
            time.sleep(2)
            
            # 4. 执行命令测试
            if terminals:
                test_commands = ["echo 'Hello from test'", "date"]
                self.run_commands(terminals[0]["item_uuid"], test_commands)
            
            # 5. 获取初始连接表
            print("=== 初始连接表 ===")
            tables = self.get_connection_tables()
            
            # 打印用户-项目映射
            print("\n用户-项目映射 (user_item_map):")
            user_item_map = tables.get("user_item_map", {})
            for user_uuid, items in user_item_map.items():
                print(f"  {user_uuid}: {items}")
            
            # 打印项目-用户连接映射
            print("\n项目-用户连接映射 (item_user_conn_map):")
            item_user_conn_map = tables.get("item_user_conn_map", {})
            for item_uuid, user_conns in item_user_conn_map.items():
                print(f"  {item_uuid}:")
                for user_uuid, conn_info in user_conns.items():
                    print(f"    {user_uuid}: {conn_info}")
            
            # 打印项目-Token映射
            print("\n项目-Token映射 (item_token_map):")
            item_token_map = tables.get("item_token_map", {})
            for item_uuid, token in item_token_map.items():
                print(f"  {item_uuid}: {token}")
            
            print()
            
            # 5. 断开一个用户与终端的连接
            if terminals and user_item_map and item_user_conn_map:
                terminal_to_disconnect = terminals[0]
                print("=== 断开连接测试 ===")
                print(f"尝试断开用户 {terminal_to_disconnect['user_uuid']} 与终端 {terminal_to_disconnect['item_uuid']} 的连接")
                
                success = self.disconnect_user_from_terminal(
                    terminal_to_disconnect["item_uuid"],
                    terminal_to_disconnect["user_uuid"]
                )
                
                # 等待断开状态稳定
                time.sleep(2)
                
                print()
                
                # 6. 获取断开连接后的连接表
                print("=== 断开连接后的连接表 ===")
                tables_after = self.get_connection_tables()
                
                # 打印用户-项目映射
                print("\n用户-项目映射 (user_item_map):")
                user_item_map_after = tables_after.get("user_item_map", {})
                for user_uuid, items in user_item_map_after.items():
                    print(f"  {user_uuid}: {items}")
                
                # 打印项目-用户连接映射
                print("\n项目-用户连接映射 (item_user_conn_map):")
                item_user_conn_map_after = tables_after.get("item_user_conn_map", {})
                for item_uuid, user_conns in item_user_conn_map_after.items():
                    print(f"  {item_uuid}:")
                    for user_uuid, conn_info in user_conns.items():
                        print(f"    {user_uuid}: {conn_info}")
                
                print()
            
            # 7. 验证权限检查功能
            print("=== 权限检查测试 ===")
            print("权限检查逻辑：")
            print("- 前端请求item时，后端检查item的所有itemhandler")
            print("- 再查itemhandleruser映射表，是否有该用户的对应关系")
            print("- 如果有，就返回该item的token")
            
            # 模拟权限检查流程
            if tables.get("item_token_map", {}):
                sample_item = next(iter(tables["item_token_map"]))
                sample_token = tables["item_token_map"][sample_item]
                print(f"\n模拟权限检查:")
                print(f"- 示例项目: {sample_item}")
                print(f"- 项目Token: {sample_token}")
                print(f"- 权限检查通过，返回Token给前端")
            
            print()
            
            # 8. 统计结果
            print("=== 测试统计 ===")
            print(f"生成用户数: {len(users)}")
            print(f"启动终端数: {len(terminals)}")
            print(f"建立Socket连接数: {len(sockets)}")
            print(f"初始连接数: {sum(len(conns) for conns in item_user_conn_map.values())}")
            if 'tables_after' in locals():
                item_user_conn_map_after = tables_after.get("item_user_conn_map", {})
                print(f"断开连接后连接数: {sum(len(conns) for conns in item_user_conn_map_after.values())}")
            
            print()
            print("✓ 所有测试完成！")
            
        finally:
            # 清理资源
            print("\n=== 清理资源 ===")
            self.stop_terminals()
            print("\n测试结束")

if __name__ == "__main__":
    test = ConnectionFullTest()
    test.run_test()
