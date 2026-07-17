"""插件路由 - 插件管理

GET    /plugins       列出插件
POST   /plugins       安装/启用插件
DELETE /plugins/{id}  删除/禁用插件
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from zhihu_downloader.api.schemas import PluginCreateRequest, PluginSchema
from zhihu_downloader.auth.jwt_auth import TokenData, get_current_user
from zhihu_downloader.plugins.manager import (
    build_plugin_manager,
    initialize_plugins,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plugins", tags=["plugins"])

_plugins_cache: dict[str, dict] = {}


@router.get("")
async def list_plugins(
    token_data: TokenData = Depends(get_current_user),
) -> list[PluginSchema]:
    """列出插件"""
    manager = build_plugin_manager()
    source_registry, exporter_registry, hook_pipeline = initialize_plugins(manager)

    plugins = []

    for source in source_registry.sources:
        plugins.append(
            PluginSchema(
                id=hash(source.name) % 10000,
                name=source.name,
                version="1.0.0",
                kind="source",
                entry=f"sources.{source.name.lower()}",
                enabled=True,
                created_at="",
            )
        )

    for fmt in exporter_registry.formats:
        exporter = exporter_registry.get(fmt)
        if exporter:
            plugins.append(
                PluginSchema(
                    id=hash(fmt) % 10000,
                    name=f"{fmt}_exporter",
                    version="1.0.0",
                    kind="exporter",
                    entry=f"exporters.{fmt}_exporter",
                    enabled=True,
                    created_at="",
                )
            )

    for hook in hook_pipeline.hooks:
        plugins.append(
            PluginSchema(
                id=hash(hook.name) % 10000,
                name=hook.name,
                version="1.0.0",
                kind="hook",
                entry=f"hooks.{hook.name.lower()}",
                enabled=True,
                created_at="",
            )
        )

    return plugins


@router.post("")
async def install_plugin(
    body: PluginCreateRequest,
    token_data: TokenData = Depends(get_current_user),
) -> PluginSchema:
    """安装/启用插件"""
    from datetime import datetime

    from zhihu_downloader.infra.database import get_session
    from zhihu_downloader.infra.models import Plugin as PluginModel

    async with get_session() as session:
        from sqlalchemy import select

        existing = await session.execute(
            select(PluginModel).where(PluginModel.name == body.name)
        )
        existing = existing.scalar_one_or_none()

        if existing:
            raise HTTPException(status_code=409, detail="插件已存在")

        plugin = PluginModel(
            name=body.name,
            version=body.version,
            kind=body.kind,
            entry=body.entry,
            config=body.config,
            enabled=True,
            created_at=datetime.utcnow(),
        )

        session.add(plugin)
        await session.commit()
        await session.refresh(plugin)

        return PluginSchema(
            id=plugin.id,
            name=plugin.name,
            version=plugin.version,
            kind=plugin.kind,
            entry=plugin.entry,
            enabled=plugin.enabled,
            created_at=plugin.created_at.isoformat(),
        )


@router.delete("/{plugin_id}")
async def uninstall_plugin(
    plugin_id: int,
    token_data: TokenData = Depends(get_current_user),
) -> dict:
    """删除/禁用插件"""
    from sqlalchemy import delete

    from zhihu_downloader.infra.database import get_session

    async with get_session() as session:
        from zhihu_downloader.infra.models import Plugin as PluginModel

        result = await session.execute(
            delete(PluginModel).where(PluginModel.id == plugin_id)
        )
        await session.commit()

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="插件不存在")

        return {"message": "插件已删除", "plugin_id": plugin_id}
