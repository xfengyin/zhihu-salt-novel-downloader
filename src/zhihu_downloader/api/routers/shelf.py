"""书架路由 - 书架 CRUD 管理

GET    /shelves          列出所有书架
POST   /shelves          创建书架
DELETE /shelves          清空书架
GET    /shelves/stats    获取书架统计
GET    /shelves/{url}    获取书籍详情
PUT    /shelves/{url}    更新书籍信息
DELETE /shelves/{url}    删除书籍
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from zhihu_downloader.api.dependencies import get_shelf_service
from zhihu_downloader.api.schemas import (
    BookSchema,
    MessageResponse,
    ShelfAddRequest,
    ShelfStatsSchema,
)
from zhihu_downloader.services.shelf_service import ShelfService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shelves", tags=["shelves"])


@router.get("")
async def list_shelves(
    shelf_service: ShelfService = Depends(get_shelf_service),
) -> list[dict]:
    """列出所有书架"""
    books = shelf_service.list_books()
    return [_normalize_shelf_book(b) for b in books]


@router.post("")
async def add_to_shelf(
    body: ShelfAddRequest,
    shelf_service: ShelfService = Depends(get_shelf_service),
) -> MessageResponse:
    """添加书籍到书架"""
    result = shelf_service.add_book(body.url)
    return MessageResponse(message=result["message"], success=result["success"])


@router.delete("")
async def clean_shelf(
    shelf_service: ShelfService = Depends(get_shelf_service),
) -> MessageResponse:
    """清空书架"""
    result = shelf_service.clean_shelf()
    return MessageResponse(message=result["message"], success=result["success"])


@router.get("/stats")
async def get_shelf_stats(
    shelf_service: ShelfService = Depends(get_shelf_service),
) -> ShelfStatsSchema:
    """获取书架统计信息"""
    return ShelfStatsSchema(**shelf_service.get_statistics())


@router.get("/{url:path}")
async def get_shelf_book(
    url: str,
    shelf_service: ShelfService = Depends(get_shelf_service),
) -> BookSchema:
    """获取书架中书籍详情"""
    book = shelf_service.get_book(url)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return BookSchema(**_normalize_shelf_book(book))


@router.put("/{url:path}")
async def update_shelf_book(
    url: str,
    body: dict,
    shelf_service: ShelfService = Depends(get_shelf_service),
) -> MessageResponse:
    """更新书架中书籍信息"""
    book = shelf_service.get_book(url)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    result = shelf_service.add_book(url, body)
    return MessageResponse(message=result["message"], success=result["success"])


@router.delete("/{url:path}")
async def remove_from_shelf(
    url: str,
    shelf_service: ShelfService = Depends(get_shelf_service),
) -> MessageResponse:
    """从书架移除书籍"""
    result = shelf_service.remove_book(url)
    return MessageResponse(message=result["message"], success=result["success"])


def _normalize_shelf_book(book: dict) -> dict:
    """将书架字典字段对齐到 BookSchema"""
    return {
        "url": book.get("url", ""),
        "title": book.get("title", "未知标题"),
        "author": book.get("author", "未知作者"),
        "chapter_count": book.get("chapter_count", 0),
        "completed": book.get("completed", False),
        "added_at": book.get("added_at", ""),
        "last_update": book.get("last_update", ""),
    }
