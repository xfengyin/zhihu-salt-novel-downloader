"""配置管理器"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, ClassVar

import yaml


class Config:
    """配置管理器"""

    DEFAULT_CONFIG: ClassVar[dict[str, Any]] = {
        "download": {
            "max_concurrent": 3,
            "rate_limit": 2.0,
            "max_retries": 3,
            "timeout": 30,
        },
        "output": {
            "output_dir": "./output",
            "default_format": "md",
        },
        "auth": {
            "cookie_file": "",
            "token": "",
        },
        "content": {
            "clean_content": True,
            "remove_ads": True,
            "remove_watermarks": True,
        },
    }

    def __init__(self, config_file: str | Path | None = None) -> None:
        """
        初始化配置管理器

        Args:
            config_file: 配置文件路径
        """
        self._config = self.DEFAULT_CONFIG.copy()
        if config_file:
            self.load(config_file)

    def load(self, config_file: str | Path) -> None:
        """
        加载配置文件

        Args:
            config_file: 配置文件路径
        """
        path = Path(config_file)
        if not path.exists():
            return

        with open(path, encoding="utf-8") as f:
            user_config: dict[str, Any] = yaml.safe_load(f) or {}

        self._deep_update(self._config, user_config)

    def _deep_update(
        self,
        base: dict[str, Any],
        update: dict[str, Any],
    ) -> None:
        """深度更新配置"""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_update(base[key], value)
            else:
                base[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值

        Args:
            key: 配置键，支持点号分隔的嵌套键
            default: 默认值

        Returns:
            配置值
        """
        keys = key.split(".")
        value: Any = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any) -> None:
        """
        设置配置值

        Args:
            key: 配置键，支持点号分隔的嵌套键
            value: 配置值
        """
        keys = key.split(".")
        target: dict[str, Any] = self._config

        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]

        target[keys[-1]] = value

    def to_dict(self) -> dict[str, Any]:
        """获取配置字典"""
        return self._config.copy()

    @classmethod
    def from_env(cls) -> Config:
        """
        从环境变量创建配置

        Returns:
            Config对象
        """
        config = cls()

        if os.getenv("MAX_CONCURRENT"):
            config.set("download.max_concurrent", int(os.getenv("MAX_CONCURRENT") or 0))
        if os.getenv("RATE_LIMIT"):
            config.set("download.rate_limit", float(os.getenv("RATE_LIMIT") or 0.0))
        if os.getenv("OUTPUT_DIR"):
            config.set("output.output_dir", os.getenv("OUTPUT_DIR"))
        if os.getenv("COOKIE_FILE"):
            config.set("auth.cookie_file", os.getenv("COOKIE_FILE"))

        return config
