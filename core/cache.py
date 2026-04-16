"""HTML响应缓存 - 基于URL哈希"""

import hashlib
import json
import time
import logging
from pathlib import Path
from typing import Optional, Dict
from dataclasses import dataclass, asdict


logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """缓存条目"""
    url: str
    content: str
    created_at: float
    expires_at: float
    
    def is_expired(self) -> bool:
        """检查是否过期"""
        return time.time() > self.expires_at


class ResponseCache:
    """响应缓存"""
    
    def __init__(self, ttl: int = 3600, cache_dir: Optional[str] = None):
        """
        初始化缓存
        
        Args:
            ttl: 缓存有效期（秒），默认1小时
            cache_dir: 缓存目录路径
        """
        self.ttl = ttl
        self._memory_cache: Dict[str, CacheEntry] = {}
        
        if cache_dir:
            self._cache_dir = Path(cache_dir)
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()
        else:
            self._cache_dir = None
    
    def _get_cache_key(self, url: str) -> str:
        """生成缓存键（URL的MD5哈希）"""
        return hashlib.md5(url.encode()).hexdigest()
    
    def _get_cache_path(self, key: str) -> Path:
        """获取缓存文件路径"""
        return self._cache_dir / f"{key}.json"
    
    def get(self, url: str) -> Optional[str]:
        """
        获取缓存内容
        
        Args:
            url: 目标URL
            
        Returns:
            缓存内容，不存在或已过期返回None
        """
        key = self._get_cache_key(url)
        
        # 内存缓存优先
        if key in self._memory_cache:
            entry = self._memory_cache[key]
            if not entry.is_expired():
                return entry.content
            else:
                del self._memory_cache[key]
        
        # 磁盘缓存
        if self._cache_dir:
            cache_path = self._get_cache_path(key)
            if cache_path.exists():
                try:
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    entry = CacheEntry(**data)
                    if not entry.is_expired():
                        # 回填内存缓存
                        self._memory_cache[key] = entry
                        return entry.content
                    else:
                        cache_path.unlink()
                except Exception as e:
                    logger.warning(f"读取缓存失败: {e}")
        
        return None
    
    def set(self, url: str, content: str):
        """
        设置缓存
        
        Args:
            url: 目标URL
            content: 内容
        """
        key = self._get_cache_key(url)
        now = time.time()
        
        entry = CacheEntry(
            url=url,
            content=content,
            created_at=now,
            expires_at=now + self.ttl
        )
        
        # 写入内存缓存
        self._memory_cache[key] = entry
        
        # 写入磁盘缓存
        if self._cache_dir:
            cache_path = self._get_cache_path(key)
            try:
                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump(asdict(entry), f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"写入缓存失败: {e}")
    
    def delete(self, url: str):
        """
        删除缓存
        
        Args:
            url: 目标URL
        """
        key = self._get_cache_key(url)
        
        # 清除内存缓存
        if key in self._memory_cache:
            del self._memory_cache[key]
        
        # 清除磁盘缓存
        if self._cache_dir:
            cache_path = self._get_cache_path(key)
            if cache_path.exists():
                cache_path.unlink()
    
    def clear(self):
        """清除所有缓存"""
        self._memory_cache.clear()
        
        if self._cache_dir and self._cache_dir.exists():
            for cache_file in self._cache_dir.glob("*.json"):
                cache_file.unlink()
        
        logger.info("缓存已清除")
    
    def _load_from_disk(self):
        """从磁盘加载缓存"""
        if not self._cache_dir or not self._cache_dir.exists():
            return
        
        for cache_file in self._cache_dir.glob("*.json"):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                entry = CacheEntry(**data)
                if not entry.is_expired():
                    key = cache_file.stem
                    self._memory_cache[key] = entry
            except Exception:
                pass
    
    def stats(self) -> Dict[str, int]:
        """获取缓存统计"""
        now = time.time()
        expired = sum(1 for e in self._memory_cache.values() if e.is_expired())
        
        return {
            'total': len(self._memory_cache),
            'valid': len(self._memory_cache) - expired,
            'expired': expired
        }
