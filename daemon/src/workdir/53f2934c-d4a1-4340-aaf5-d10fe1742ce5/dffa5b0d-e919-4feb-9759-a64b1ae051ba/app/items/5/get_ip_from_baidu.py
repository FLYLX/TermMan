#!/usr/bin/env python3
"""
从百度查询IP地址的工具
"""

import requests
from bs4 import BeautifulSoup
import re

def get_ip_from_baidu():
    """
    从百度查询IP地址
    """
    try:
        # 使用百度IP查询页面
        url = "https://www.baidu.com/s?wd=ip"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        print("正在查询IP地址...")
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # 解析HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 查找IP信息 - 百度IP查询结果通常在特定的div中
        ip_info = None
        
        # 方法1: 查找包含"本机IP"的文本
        for text in soup.stripped_strings:
            if "本机IP" in text or "IP地址" in text or "IP:" in text:
                ip_info = text.strip()
                break
        
        # 方法2: 查找常见的IP显示元素
        if not ip_info:
            ip_elements = soup.find_all(['span', 'div', 'p'], class_=re.compile(r'ip|IP|result'))
            for element in ip_elements:
                text = element.get_text().strip()
                if re.search(r'\d+\.\d+\.\d+\.\d+', text):
                    ip_info = text
                    break
        
        # 方法3: 直接搜索IP地址模式
        if not ip_info:
            ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
            all_text = soup.get_text()
            ip_matches = re.findall(ip_pattern, all_text)
            if ip_matches:
                # 取第一个看起来像公网IP的地址
                for ip in ip_matches:
                    if not ip.startswith('127.') and not ip.startswith('192.168.') and not ip.startswith('10.'):
                        ip_info = f"IP地址: {ip}"
                        break
        
        if ip_info:
            print(f"查询结果: {ip_info}")
        else:
            print("未能在百度页面中找到IP信息")
            print("尝试备用方法...")
            
            # 备用方法: 使用其他IP查询API
            try:
                api_response = requests.get('https://api.ipify.org?format=json', timeout=5)
                if api_response.status_code == 200:
                    ip_data = api_response.json()
                    print(f"备用查询结果: 您的IP地址是 {ip_data['ip']}")
                else:
                    print("备用查询失败")
            except Exception as api_error:
                print(f"备用查询出错: {api_error}")
                
    except requests.exceptions.RequestException as e:
        print(f"网络请求错误: {e}")
    except Exception as e:
        print(f"查询过程中出现错误: {e}")

def main():
    """主函数"""
    print("=" * 50)
    print("百度IP查询工具")
    print("=" * 50)
    get_ip_from_baidu()
    print("=" * 50)

if __name__ == "__main__":
    main()
