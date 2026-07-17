"""插件管理器

提供插件系统的核心管理能力：
- 使用 pluggy 管理插件生命周期
- 源插件注册与 URL 匹配
- 导出器插件注册与格式匹配
- 钩子插件管道执行
- 动态加载目录下的插件
"""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from typing import Any, Protocol

import pluggy

from zhihu_downloader.exporters.base_exporter import BaseExporter
from zhihu_downloader.parsers.article_parser import ArticleInfo, Chapter

logger = logging.getLogger(__name__)

hookspec = pluggy.HookspecMarker("zhihu_downloader")
hookimpl = pluggy.HookimplMarker("zhihu_downloader")


class SourcePlugin(Protocol):
    """源插件协议"""

    @property
    def name(self) -> str:
        """插件名称"""
        ...

    @property
    def priority(self) -> int:
        """匹配优先级（数值越大优先级越高）"""
        ...

    def matches(self, url: str) -> bool:
        """判断 URL 是否匹配此源"""
        ...

    async def fetch_article_info(self, url: str, downloader: Any) -> ArticleInfo:
        """获取文章信息"""
        ...

    async def fetch_chapter_content(self, url: str, downloader: Any) -> str:
        """获取章节内容"""
        ...


class ExporterPlugin(Protocol):
    """导出器插件协议"""

    @property
    def format(self) -> str:
        """支持的导出格式"""
        ...

    def create(self, output_dir: Path) -> BaseExporter:
        """创建导出器实例"""
        ...


class HookPlugin(Protocol):
    """钩子插件协议"""

    @property
    def name(self) -> str:
        """插件名称"""
        ...

    @property
    def priority(self) -> int:
        """执行优先级（数值越小越先执行）"""
        ...

    async def process(self, chapter: Chapter) -> Chapter:
        """处理章节内容"""
        ...


class SourceRegistry:
    """源插件注册表"""

    def __init__(self) -> None:
        self._sources: list[SourcePlugin] = []

    def register(self, source: SourcePlugin) -> None:
        """注册源插件"""
        self._sources.append(source)
        self._sources.sort(key=lambda s: s.priority, reverse=True)
        logger.info("注册源插件: %s (优先级: %d)", source.name, source.priority)

    def match(self, url: str) -> SourcePlugin | None:
        """根据 URL 匹配源插件"""
        for source in self._sources:
            try:
                if source.matches(url):
                    logger.debug("URL %s 匹配源插件: %s", url, source.name)
                    return source
            except Exception as e:
                logger.warning("源插件 %s 匹配失败: %s", source.name, e)
        logger.debug("URL %s 未匹配到任何源插件", url)
        return None

    @property
    def sources(self) -> list[SourcePlugin]:
        """获取所有源插件"""
        return list(self._sources)


class ExporterRegistry:
    """导出器插件注册表"""

    def __init__(self) -> None:
        self._exporters: dict[str, ExporterPlugin] = {}

    def register(self, exporter: ExporterPlugin) -> None:
        """注册导出器插件"""
        self._exporters[exporter.format.lower()] = exporter
        logger.info("注册导出器插件: %s (格式: %s)", exporter.format, exporter.format)

    def get(self, format: str) -> ExporterPlugin | None:
        """根据格式获取导出器插件"""
        exporter = self._exporters.get(format.lower())
        if exporter:
            logger.debug("获取导出器插件: %s", format)
        else:
            logger.debug("未找到格式 %s 的导出器插件", format)
        return exporter

    @property
    def formats(self) -> list[str]:
        """获取所有支持的导出格式"""
        return list(self._exporters.keys())


class HookPipeline:
    """钩子插件管道"""

    def __init__(self) -> None:
        self._hooks: list[HookPlugin] = []

    def register(self, hook: HookPlugin) -> None:
        """注册钩子插件"""
        self._hooks.append(hook)
        self._hooks.sort(key=lambda h: h.priority)
        logger.info("注册钩子插件: %s (优先级: %d)", hook.name, hook.priority)

    async def process(self, chapter: Chapter) -> Chapter:
        """按优先级执行所有钩子插件"""
        result = chapter
        for hook in self._hooks:
            try:
                result = await hook.process(result)
                logger.debug("钩子 %s 处理完成", hook.name)
            except Exception as e:
                logger.warning("钩子 %s 处理失败，跳过: %s", hook.name, e)
        return result

    @property
    def hooks(self) -> list[HookPlugin]:
        """获取所有钩子插件"""
        return list(self._hooks)


@hookspec
def register_sources(registry: SourceRegistry) -> None:
    """注册源插件的钩子规范"""
    pass


@hookspec
def register_exporters(registry: ExporterRegistry) -> None:
    """注册导出器插件的钩子规范"""
    pass


@hookspec
def register_hooks(pipeline: HookPipeline) -> None:
    """注册钩子插件的钩子规范"""
    pass


def build_plugin_manager() -> pluggy.PluginManager:
    """构建插件管理器

    创建 pluggy PluginManager 实例，并注册所有 hookspec。

    Returns:
        pluggy.PluginManager: 插件管理器实例
    """
    manager = pluggy.PluginManager("zhihu_downloader")
    manager.add_hookspecs(sys.modules[__name__])
    logger.info("插件管理器构建完成")
    return manager


def load_plugins_from_directory(
    manager: pluggy.PluginManager,
    directory: Path,
) -> None:
    """从目录动态加载插件

    扫描指定目录下的 Python 文件，动态导入并注册为插件。

    Args:
        manager: 插件管理器
        directory: 插件目录路径
    """
    if not directory.exists():
        logger.warning("插件目录不存在: %s", directory)
        return

    if not directory.is_dir():
        logger.warning("指定路径不是目录: %s", directory)
        return

    for plugin_file in sorted(directory.glob("*.py")):
        if plugin_file.name.startswith("_"):
            continue

        module_name = f"zhihu_downloader.plugins.{plugin_file.stem}"

        try:
            module = importlib.import_module(module_name)
            manager.register(module)
            logger.info("加载插件成功: %s", module_name)
        except ImportError as e:
            logger.warning("加载插件失败 %s: %s", module_name, e)
        except Exception as e:
            logger.error("加载插件异常 %s: %s", module_name, e)


def initialize_plugins(
    manager: pluggy.PluginManager,
) -> tuple[SourceRegistry, ExporterRegistry, HookPipeline]:
    """初始化所有插件

    调用所有注册钩子，初始化源插件、导出器插件和钩子插件。

    Args:
        manager: 插件管理器

    Returns:
        tuple: 包含 SourceRegistry, ExporterRegistry, HookPipeline 的元组
    """
    source_registry = SourceRegistry()
    exporter_registry = ExporterRegistry()
    hook_pipeline = HookPipeline()

    try:
        manager.hook.register_sources(registry=source_registry)
    except Exception as e:
        logger.error("注册源插件失败: %s", e)

    try:
        manager.hook.register_exporters(registry=exporter_registry)
    except Exception as e:
        logger.error("注册导出器插件失败: %s", e)

    try:
        manager.hook.register_hooks(pipeline=hook_pipeline)
    except Exception as e:
        logger.error("注册钩子插件失败: %s", e)

    logger.info(
        "插件初始化完成: 源插件 %d 个, 导出器 %d 个, 钩子 %d 个",
        len(source_registry.sources),
        len(exporter_registry.formats),
        len(hook_pipeline.hooks),
    )

    return source_registry, exporter_registry, hook_pipeline
