"""User-Agent轮换器"""

import random
from typing import List, Dict


class UserAgentRotator:
    """User-Agent轮换器"""
    
    # Android移动端User-Agent列表
    MOBILE_UA_LIST: List[str] = [
        # Android 14 + Chrome
        "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
        "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
        "Mozilla/5.0 (Linux; Android 14; Xiaomi 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
        "Mozilla/5.0 (Linux; Android 14; OnePlus 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
        
        # Android 13 + Chrome
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.169 Mobile Safari/537.36",
        "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.169 Mobile Safari/537.36",
        "Mozilla/5.0 (Linux; Android 13; Xiaomi 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.169 Mobile Safari/537.36",
        
        # iOS 17 + Safari
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
        
        # iPadOS 17
        "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    ]
    
    # 移动端请求头模板
    MOBILE_HEADERS_TEMPLATE: Dict[str, str] = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
    }
    
    def __init__(self):
        self._index = 0
        self._count = len(self.MOBILE_UA_LIST)
    
    def get_random_ua(self) -> str:
        """
        获取随机User-Agent
        
        Returns:
            User-Agent字符串
        """
        return random.choice(self.MOBILE_UA_LIST)
    
    def get_next_ua(self) -> str:
        """
        获取下一个User-Agent（轮询）
        
        Returns:
            User-Agent字符串
        """
        ua = self.MOBILE_UA_LIST[self._index]
        self._index = (self._index + 1) % self._count
        return ua
    
    def get_mobile_headers(self) -> Dict[str, str]:
        """
        获取移动端请求头
        
        Returns:
            完整的请求头字典
        """
        headers = self.MOBILE_HEADERS_TEMPLATE.copy()
        headers['User-Agent'] = self.get_random_ua()
        return headers
    
    def get_headers_for_android(self) -> Dict[str, str]:
        """获取Android特定请求头"""
        headers = self.get_mobile_headers()
        headers['User-Agent'] = random.choice([
            ua for ua in self.MOBILE_UA_LIST 
            if 'Android' in ua and 'iPhone' not in ua
        ])
        return headers
    
    def get_headers_for_ios(self) -> Dict[str, str]:
        """获取iOS特定请求头"""
        headers = self.get_mobile_headers()
        headers['User-Agent'] = random.choice([
            ua for ua in self.MOBILE_UA_LIST 
            if 'iPhone' in ua or 'iPad' in ua
        ])
        return headers
