"""配置文件加载器"""

import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


logger = logging.getLogger(__name__)


class Config:
    """配置管理器"""
    
    DEFAULT_CONFIG: Dict[str, Any] = {
        'download': {
            'max_concurrent': 3,
            'rate_limit': 2.0,
            'max_retries': 3,
            'retry_delay': 1.0,
            'timeout': 30,
        },
        'cache': {
            'enabled': True,
            'ttl': 3600,  # 1小时
            'cache_dir': './cache',
        },
        'output': {
            'output_dir': './output',
            'default_format': 'md',
            'create_subdir': True,
        },
        'content': {
            'clean_content': True,
            'remove_ads': True,
            'remove_watermarks': True,
        },
        'auth': {
            'cookie_file': None,
            'z_c0_token': None,
        }
    }
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置
        
        Args:
            config_path: 配置文件路径
        """
        self._config = self._deep_copy(self.DEFAULT_CONFIG)
        
        if config_path:
            self.load(config_path)
    
    def load(self, config_path: str):
        """
        加载配置文件
        
        Args:
            config_path: 配置文件路径
        """
        path = Path(config_path)
        
        if not path.exists():
            logger.warning(f"配置文件不存在: {config_path}")
            return
        
        with open(path, 'r', encoding='utf-8') as f:
            user_config = yaml.safe_load(f)
        
        if user_config:
            self._merge_config(self._config, user_config)
            logger.info(f"已加载配置文件: {config_path}")
    
    def _merge_config(self, base: Dict, overlay: Dict):
        """递归合并配置"""
        for key, value in overlay.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_config(base[key], value)
            else:
                base[key] = value
    
    def _deep_copy(self, obj: Any) -> Any:
        """深拷贝"""
        if isinstance(obj, dict):
            return {k: self._deep_copy(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._deep_copy(item) for item in obj]
        else:
            return obj
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值
        
        支持点号分隔的路径，如 'download.max_concurrent'
        
        Args:
            key: 配置键
            default: 默认值
            
        Returns:
            配置值
        """
        keys = key.split('.')
        value = self._config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set(self, key: str, value: Any):
        """
        设置配置值
        
        Args:
            key: 配置键
            value: 配置值
        """
        keys = key.split('.')
        target = self._config
        
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        
        target[keys[-1]] = value
    
    def save(self, output_path: str):
        """
        保存配置到文件
        
        Args:
            output_path: 输出文件路径
        """
        with open(output_path, 'w', encoding='utf-8') as f:
            yaml.dump(self._config, f, allow_unicode=True, default_flow_style=False)
        
        logger.info(f"配置已保存: {output_path}")
    
    def to_dict(self) -> Dict[str, Any]:
        """获取配置字典"""
        return self._deep_copy(self._config)
