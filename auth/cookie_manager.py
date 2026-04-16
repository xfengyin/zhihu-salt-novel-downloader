"""Cookie管理器"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional


logger = logging.getLogger(__name__)


class CookieManager:
    """Cookie管理器"""
    
    def __init__(self):
        self._cookies: Dict[str, str] = {}
        self._z_c0_token: Optional[str] = None
    
    def load_from_file(self, cookie_file: str):
        """
        从文件加载Cookie
        
        支持格式：
        1. JSON文件（Chrome插件导出格式）
        2. 纯文本格式（key=value行）
        
        Args:
            cookie_file: Cookie文件路径
        """
        path = Path(cookie_file)
        
        if not path.exists():
            raise FileNotFoundError(f"Cookie文件不存在: {cookie_file}")
        
        if path.suffix == '.json':
            self._load_json(path)
        else:
            self._load_text(path)
        
        logger.info(f"已加载 {len(self._cookies)} 个Cookie")
    
    def _load_json(self, path: Path):
        """加载JSON格式Cookie（Chrome插件格式）"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        for item in data:
            name = item.get('name', '')
            value = item.get('value', '')
            if name and value:
                self._cookies[name] = value
        
        # 特别处理z_c0
        if 'z_c0' in self._cookies:
            self._z_c0_token = self._cookies['z_c0']
    
    def _load_text(self, path: Path):
        """加载纯文本格式Cookie"""
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                if '=' in line:
                    name, value = line.split('=', 1)
                    self._cookies[name.strip()] = value.strip()
    
    def set_token(self, token: str):
        """
        设置z_c0 token
        
        Args:
            token: z_c0 token值
        """
        self._z_c0_token = token
        self._cookies['z_c0'] = token
        logger.info("已设置z_c0 token")
    
    def set_cookie(self, name: str, value: str):
        """
        设置单个Cookie
        
        Args:
            name: Cookie名称
            value: Cookie值
        """
        self._cookies[name] = value
    
    def get_cookies(self) -> Dict[str, str]:
        """
        获取所有Cookie
        
        Returns:
            Cookie字典
        """
        return self._cookies.copy()
    
    def get_cookie_header(self) -> str:
        """
        获取Cookie头字符串
        
        Returns:
            Cookie头字符串
        """
        return '; '.join(f"{k}={v}" for k, v in self._cookies.items())
    
    @property
    def has_z_c0(self) -> bool:
        """是否已设置z_c0认证"""
        return bool(self._z_c0_token)
    
    def save_to_file(self, output_path: str):
        """
        保存Cookie到文件
        
        Args:
            output_path: 输出文件路径
        """
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump([
                {'name': k, 'value': v}
                for k, v in self._cookies.items()
            ], f, ensure_ascii=False, indent=2)
        
        logger.info(f"Cookie已保存到: {output_path}")
