"""重试装饰器"""

import asyncio
import logging
import time
from functools import wraps
from typing import Callable, TypeVar, Any

logger = logging.getLogger(__name__)

T = TypeVar('T')


def async_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential: bool = True,
    exceptions: tuple = (Exception,)
):
    """
    异步重试装饰器
    
    Args:
        max_retries: 最大重试次数
        base_delay: 基础延迟（秒）
        max_delay: 最大延迟（秒）
        exponential: 是否使用指数退避
        exceptions: 需要重试的异常类型
        
    Returns:
        装饰器函数
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt >= max_retries:
                        logger.error(
                            f"{func.__name__} 失败，已达最大重试次数 "
                            f"({max_retries + 1}次): {e}"
                        )
                        raise
                    
                    if exponential:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                    else:
                        delay = base_delay
                    
                    logger.warning(
                        f"{func.__name__} 失败 ({attempt + 1}/{max_retries + 1}), "
                        f"{delay:.1f}s后重试: {e}"
                    )
                    await asyncio.sleep(delay)
            
            raise last_exception
        
        return wrapper
    return decorator


def sync_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential: bool = True,
    exceptions: tuple = (Exception,)
):
    """
    同步重试装饰器
    
    Args:
        max_retries: 最大重试次数
        base_delay: 基础延迟（秒）
        max_delay: 最大延迟（秒）
        exponential: 是否使用指数退避
        exceptions: 需要重试的异常类型
        
    Returns:
        装饰器函数
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt >= max_retries:
                        logger.error(
                            f"{func.__name__} 失败，已达最大重试次数 "
                            f"({max_retries + 1}次): {e}"
                        )
                        raise
                    
                    if exponential:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                    else:
                        delay = base_delay
                    
                    logger.warning(
                        f"{func.__name__} 失败 ({attempt + 1}/{max_retries + 1}), "
                        f"{delay:.1f}s后重试: {e}"
                    )
                    time.sleep(delay)
            
            raise last_exception
        
        return wrapper
    return decorator


class RetryContext:
    """可自定义的重试上下文"""
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential: bool = True
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential = exponential
    
    async def execute(self, func: Callable[..., T], *args, **kwargs) -> T:
        """执行带重试的函数"""
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                else:
                    return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                
                if attempt >= self.max_retries:
                    raise
                
                if self.exponential:
                    delay = min(self.base_delay * (2 ** attempt), self.max_delay)
                else:
                    delay = self.base_delay
                
                logger.warning(f"重试中 ({attempt + 1}/{self.max_retries + 1}), 等待 {delay:.1f}s")
                await asyncio.sleep(delay)
        
        raise last_exception
