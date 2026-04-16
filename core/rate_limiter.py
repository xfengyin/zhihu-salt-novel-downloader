"""速率限制器 - 令牌桶算法"""

import asyncio
import time
import logging
from typing import Optional


logger = logging.getLogger(__name__)


class RateLimiter:
    """
    速率限制器 - 令牌桶算法
    
    控制每秒请求数，支持突发流量
    """
    
    def __init__(self, rate: float = 2.0, burst: Optional[int] = None):
        """
        初始化速率限制器
        
        Args:
            rate: 每秒请求数
            burst: 突发容量，默认为rate的值
        """
        self.rate = rate
        self.burst = burst or int(rate)
        self._tokens = float(self.burst)
        self._last_update = time.monotonic()
        self._lock = asyncio.Lock()
    
    async def acquire(self, tokens: int = 1):
        """
        获取令牌
        
        Args:
            tokens: 需要获取的令牌数
        """
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._last_update
                
                # 补充令牌
                self._tokens = min(
                    self.burst,
                    self._tokens + elapsed * self.rate
                )
                self._last_update = now
                
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                
                # 需要等待
                wait_time = (tokens - self._tokens) / self.rate
                logger.debug(f"速率限制: 等待 {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
    
    def reset(self):
        """重置令牌桶"""
        self._tokens = float(self.burst)
        self._last_update = time.monotonic()
    
    @property
    def available_tokens(self) -> float:
        """当前可用令牌数"""
        now = time.monotonic()
        elapsed = now - self._last_update
        return min(
            self.burst,
            self._tokens + elapsed * self.rate
        )
