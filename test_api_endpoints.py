import requests
import uuid

# 测试配置
DAEMON_HOST = "127.0.0.1"
DAEMON_PORT = 24444
API_KEY = "termman_daemon_secret_key_2024"
BASE_URL = f"http://{DAEMON_HOST}:{DAEMON_PORT}"
API_BASE_URL = f"{BASE_URL}/api"

# 测试健康检查
def test_health_check():
    print("测试健康检查...")
    try:
        response = requests.get(BASE_URL)
        print(f"状态码: {response.status_code}")
        print(f"响应: {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"错误: {e}")
        return False

# 测试创建终端
def test_create_terminal():
    print("\n测试创建终端...")
    try:
        user_uuid = f"user-{uuid.uuid4()}"
        terminal_token = str(uuid.uuid4())
        
        response = requests.post(
            f"{API_BASE_URL}/terminal/start",
            headers={"X-API-Key": API_KEY},
            json={
                "user_uuid": user_uuid,
                "token": terminal_token
            }
        )
        
        print(f"状态码: {response.status_code}")
        print(f"响应: {response.json()}")
        
        if response.status_code == 200:
            return response.json().get("item_uuid")
        return None
    except Exception as e:
        print(f"错误: {e}")
        return None

# 测试终端状态查询
def test_terminal_status(item_uuid):
    print(f"\n测试终端状态查询 (item_uuid: {item_uuid})...")
    try:
        response = requests.get(
            f"{API_BASE_URL}/terminal/status/{item_uuid}",
            headers={"X-API-Key": API_KEY}
        )
        
        print(f"状态码: {response.status_code}")
        print(f"响应: {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"错误: {e}")
        return False

# 测试终端停止
def test_terminal_stop(item_uuid):
    print(f"\n测试终端停止 (item_uuid: {item_uuid})...")
    try:
        response = requests.post(
            f"{API_BASE_URL}/terminal/stop",
            headers={"X-API-Key": API_KEY},
            json={"item_uuid": item_uuid}
        )
        
        print(f"状态码: {response.status_code}")
        print(f"响应: {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"错误: {e}")
        return False

# 测试终端列表
def test_terminal_list():
    print("\n测试终端列表...")
    try:
        response = requests.get(
            f"{API_BASE_URL}/terminal/list",
            headers={"X-API-Key": API_KEY}
        )
        
        print(f"状态码: {response.status_code}")
        print(f"响应: {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"错误: {e}")
        return False

# 运行所有测试
if __name__ == "__main__":
    print("=" * 50)
    print("API端点测试")
    print("=" * 50)
    
    # 运行测试
    results = []
    
    results.append(test_health_check())
    item_uuid = test_create_terminal()
    
    if item_uuid:
        results.append(test_terminal_status(item_uuid))
        results.append(test_terminal_list())
        results.append(test_terminal_stop(item_uuid))
        results.append(test_terminal_list())  # 检查终端是否已停止
    else:
        print("\n创建终端失败，跳过后续测试")
    
    # 测试总结
    print("\n" + "=" * 50)
    print("测试总结")
    print("=" * 50)
    print(f"总测试数: {len(results)}")
    print(f"通过: {sum(results)}")
    print(f"失败: {len(results) - sum(results)}")
    print(f"通过率: {sum(results)/len(results)*100:.1f}%")
