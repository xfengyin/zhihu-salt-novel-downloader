"""插件协议定义 - pluggy 框架"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import pluggy

if TYPE_CHECKING:
    from zhihu_downloader.parsers.article_parser import ArticleInfo, Chapter

PROJECT_NAME = "zhihu_downloader"

hookspec = pluggy.HookspecMarker(PROJECT_NAME)
hookimpl = pluggy.HookimplMarker(PROJECT_NAME)


@runtime_checkable
class FetcherProtocol(Protocol):
    """受限的请求器接口"""

    async def fetch(self, url: str, use_cache: bool = True) -> str:
        ...

    async def fetch_with_retry(
        self,
        url: str,
        max_retries: int = 3,
        base_delay: float = 1.0,
        use_cache: bool = True,
    ) -> str:
        ...


@runtime_checkable
class CacheProtocol(Protocol):
    """受限的缓存接口"""

    def get(self, key: str) -> str | None:
        ...

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        ...


@runtime_checkable
class ConfigProtocol(Protocol):
    """受限的配置接口"""

    def get(self, key: str, default: Any = None) -> Any:
        ...

    def set(self, key: str, value: Any) -> None:
        ...


class SourceContext:
    """数据源上下文 - 提供受限的接口给插件"""

    def __init__(
        self,
        fetcher: FetcherProtocol,
        cache: CacheProtocol,
        config: ConfigProtocol,
    ) -> None:
        self._fetcher = fetcher
        self._cache = cache
        self._config = config

    async def fetch(self, url: str, use_cache: bool = True) -> str:
        return await self._fetcher.fetch(url, use_cache)

    async def fetch_with_retry(
        self,
        url: str,
        max_retries: int = 3,
        base_delay: float = 1.0,
        use_cache: bool = True,
    ) -> str:
        return await self._fetcher.fetch_with_retry(url, max_retries, base_delay, use_cache)

    def cache_get(self, key: str) -> str | None:
        return self._cache.get(key)

    def cache_set(self, key: str, value: str, ttl: int | None = None) -> None:
        self._cache.set(key, value, ttl)

    def config_get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def config_set(self, key: str, value: Any) -> None:
        self._config.set(key, value)


class SourcePlugin(ABC):
    """数据源插件协议"""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        ...

    @property
    @abstractmethod
    def domains(self) -> list[str]:
        ...

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        ...

    @abstractmethod
    async def parse_book(self, html: str, ctx: SourceContext) -> ArticleInfo:
        ...

    @abstractmethod
    async def fetch_chapter(self, url: str, ctx: SourceContext) -> Chapter:
        ...


class ExporterPlugin(ABC):
    """导出器插件协议"""

    @property
    @abstractmethod
    def format(self) -> str:
        ...

    @property
    @abstractmethod
    def ext(self) -> str:
        ...

    @property
    @abstractmethod
    def mime(self) -> str:
        ...

    @abstractmethod
    def export(self, book: ArticleInfo, output_dir: Path) -> Path:
        ...


class HookPlugin(ABC):
    """钩子插件协议"""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def priority(self) -> int:
        ...

    @abstractmethod
    async def on_chapter(self, chapter: Chapter, ctx: SourceContext) -> None:
        ...


class PluginSpec:
    """插件钩子规范"""

    @hookspec
    def zsd_register_source(self) -> list[type[SourcePlugin]]:
        """注册数据源插件"""
        raise NotImplementedError

    @hookspec
    def zsd_register_exporter(self) -> list[type[ExporterPlugin]]:
        """注册导出器插件"""
        raise NotImplementedError

    @hookspec
    def zsd_register_hook(self) -> list[type[HookPlugin]]:
        """注册钩子插件"""
        raise NotImplementedError
