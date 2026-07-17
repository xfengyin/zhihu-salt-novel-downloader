"""UA轮询器 - 支持随机选择和顺序轮询"""

from __future__ import annotations

import enum
import random
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

from pydantic_settings import BaseSettings, SettingsConfigDict


class UAStrategy(enum.Enum):
    """UA选择策略"""

    RANDOM = "random"
    SEQUENTIAL = "sequential"


class UARotatorSettings(BaseSettings):
    """UA轮询器配置"""

    model_config = SettingsConfigDict(env_prefix="UA_ROTATOR_")

    strategy: UAStrategy = UAStrategy.RANDOM
    custom_ua_file: str | None = None


class UARotator:
    """User-Agent轮询器"""

    DESKTOP_UAS: ClassVar[list[str]] = [
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
            "Gecko/20100101 Firefox/121.0"
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) "
            "Gecko/20100101 Firefox/120.0"
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) "
            "Gecko/20100101 Firefox/121.0"
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) "
            "Gecko/20100101 Firefox/120.0"
        ),
        (
            "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) "
            "Gecko/20100101 Firefox/121.0"
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0"
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Edge/119.0.0.0"
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15"
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 "
            "Safari/537.36 Edg/120.0.0.0"
        ),
    ]

    MOBILE_UAS: ClassVar[list[str]] = [
        (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
            "Mobile/15E148 Safari/604.1"
        ),
        (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 15_7 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.7 "
            "Mobile/15E148 Safari/604.1"
        ),
        (
            "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        (
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 "
            "Mobile Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 "
            "Mobile Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 "
            "Mobile Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Linux; Android 13; Pixel 7 Pro) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 "
            "Mobile Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Linux; Android 14; SM-S928B) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 "
            "Mobile Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Linux; Android 13; SM-G998B) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 "
            "Mobile Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Linux; Android 14; SM-G918B) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 "
            "Mobile Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Linux; Android 13; SM-G900F) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 "
            "Mobile Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Linux; Android 14; Xiaomi 14) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 "
            "Mobile Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Linux; Android 13; Xiaomi 13) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 "
            "Mobile Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Linux; Android 14; vivo X100) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 "
            "Mobile Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Linux; Android 13; OPPO Find X6) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 "
            "Mobile Safari/537.36"
        ),
    ]

    def __init__(
        self,
        strategy: UAStrategy | str = UAStrategy.RANDOM,
        custom_ua_file: str | Path | None = None,
    ) -> None:
        """
        初始化UA轮询器

        Args:
            strategy: 选择策略，支持 'random' 或 'sequential'
            custom_ua_file: 自定义UA文件路径
        """
        if isinstance(strategy, str):
            strategy = UAStrategy(strategy.lower())
        self._strategy = strategy

        self._desktop_uas = self.DESKTOP_UAS.copy()
        self._mobile_uas = self.MOBILE_UAS.copy()
        self._all_uas = self._desktop_uas + self._mobile_uas

        self._desktop_index = 0
        self._mobile_index = 0
        self._all_index = 0

        if custom_ua_file:
            self.load_from_file(custom_ua_file)

    @property
    def strategy(self) -> UAStrategy:
        """获取当前策略"""
        return self._strategy

    @strategy.setter
    def strategy(self, value: UAStrategy | str) -> None:
        """设置策略"""
        if isinstance(value, str):
            value = UAStrategy(value.lower())
        self._strategy = value

    @property
    def desktop_count(self) -> int:
        """桌面端UA数量"""
        return len(self._desktop_uas)

    @property
    def mobile_count(self) -> int:
        """移动端UA数量"""
        return len(self._mobile_uas)

    @property
    def total_count(self) -> int:
        """总UA数量"""
        return len(self._all_uas)

    def next(self) -> str:
        """
        返回下一个UA（混合桌面端和移动端）

        Returns:
            User-Agent字符串
        """
        if self._strategy == UAStrategy.RANDOM:
            return random.choice(self._all_uas)
        else:
            ua = self._all_uas[self._all_index]
            self._all_index = (self._all_index + 1) % len(self._all_uas)
            return ua

    def next_mobile(self) -> str:
        """
        返回下一个移动端UA

        Returns:
            移动端User-Agent字符串
        """
        if self._strategy == UAStrategy.RANDOM:
            return random.choice(self._mobile_uas)
        else:
            ua = self._mobile_uas[self._mobile_index]
            self._mobile_index = (self._mobile_index + 1) % len(self._mobile_uas)
            return ua

    def next_desktop(self) -> str:
        """
        返回下一个桌面端UA

        Returns:
            桌面端User-Agent字符串
        """
        if self._strategy == UAStrategy.RANDOM:
            return random.choice(self._desktop_uas)
        else:
            ua = self._desktop_uas[self._desktop_index]
            self._desktop_index = (self._desktop_index + 1) % len(self._desktop_uas)
            return ua

    def load_from_file(self, file_path: str | Path) -> None:
        """
        从文件加载自定义UA列表

        文件格式：每行一个UA，以 # 开头的行作为注释

        Args:
            file_path: UA文件路径
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"UA文件不存在: {file_path}")

        desktop_uas: list[str] = []
        mobile_uas: list[str] = []

        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                lower_line = line.lower()
                if any(
                    device in lower_line
                    for device in [
                        "mobile",
                        "android",
                        "iphone",
                        "ipad",
                        "tablet",
                        "pixel",
                        "sm-",
                    ]
                ):
                    mobile_uas.append(line)
                else:
                    desktop_uas.append(line)

        if desktop_uas:
            self._desktop_uas = desktop_uas
        if mobile_uas:
            self._mobile_uas = mobile_uas

        self._all_uas = self._desktop_uas + self._mobile_uas
        self._reset_indices()

    def _reset_indices(self) -> None:
        """重置顺序索引"""
        self._desktop_index = 0
        self._mobile_index = 0
        self._all_index = 0

    def __iter__(self) -> Iterator[str]:
        """迭代器接口"""
        return self

    def __next__(self) -> str:
        """迭代器next方法"""
        return self.next()

    def __len__(self) -> int:
        """返回总UA数量"""
        return self.total_count

    @classmethod
    def from_settings(cls, settings: UARotatorSettings | None = None) -> UARotator:
        """
        从配置创建UA轮询器

        Args:
            settings: UARotatorSettings配置对象

        Returns:
            UARotator实例
        """
        if settings is None:
            settings = UARotatorSettings()
        return cls(strategy=settings.strategy, custom_ua_file=settings.custom_ua_file)
