"""书籍路由 - 书籍 CRUD 与章节管理

GET    /books               列出书籍
POST   /books               添加书籍
GET    /books/{id}          获取书籍详情
DELETE /books/{id}          删除书籍
GET    /books/{id}/chapters 获取书籍章节列表
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from zhihu_downloader.api.dependencies import get_download_service
from zhihu_downloader.api.schemas import BookCreateRequest, BookDetailSchema, ChapterSchema
from zhihu_downloader.infra.models import Book as BookModel
from zhihu_downloader.infra.repository import BookRepository
from zhihu_downloader.parsers.article_parser import ArticleParser
from zhihu_downloader.services.download_service import DownloadService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/books", tags=["books"])


@router.get("")
async def list_books(
    shelf_id: int | None = None,
) -> list[BookDetailSchema]:
    """列出书籍"""
    from zhihu_downloader.infra.database import get_session

    async with get_session() as session:
        repo = BookRepository(session)
        books = await repo.list(user_id=1, shelf_id=shelf_id)
        return [_model_to_schema(book) for book in books]


@router.post("")
async def create_book(
    body: BookCreateRequest,
    download_service: DownloadService = Depends(get_download_service),
) -> BookDetailSchema:
    """添加书籍"""
    from zhihu_downloader.infra.database import get_session

    async with get_session() as session:
        repo = BookRepository(session)

        existing = await repo.get_by_url(body.url)
        if existing:
            raise HTTPException(status_code=409, detail="书籍已存在")

        parser = ArticleParser()
        downloader = download_service._downloader if hasattr(download_service, '_downloader') else None

        if downloader:
            try:
                html = await downloader.fetch(body.url)
                info = parser.parse_article_info(html)
            except Exception as e:
                logger.warning("获取书籍信息失败，使用默认值: %s", e)
                info = None
        else:
            info = None

        book = BookModel(
            user_id=1,
            shelf_id=body.shelf_id,
            source="zhihu",
            url=body.url,
            title=info.title if info else "未知标题",
            author=info.author if info else None,
            chapter_count=info.chapter_count if info else 0,
            cover_url=info.cover_url if info else None,
            description=info.description if info else None,
            last_sync_at=datetime.utcnow(),
        )

        book = await repo.upsert(book)
        return _model_to_schema(book)


@router.get("/{book_id}")
async def get_book(
    book_id: int,
) -> BookDetailSchema:
    """获取书籍详情"""
    from zhihu_downloader.infra.database import get_session

    async with get_session() as session:
        repo = BookRepository(session)
        book = await repo.get(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="书籍不存在")
        return _model_to_schema(book)


@router.delete("/{book_id}")
async def delete_book(
    book_id: int,
) -> dict:
    """删除书籍"""
    from zhihu_downloader.infra.database import get_session

    async with get_session() as session:
        repo = BookRepository(session)
        success = await repo.delete(book_id)
        if not success:
            raise HTTPException(status_code=404, detail="书籍不存在")
        return {"message": "书籍已删除", "book_id": book_id}


@router.get("/{book_id}/chapters")
async def get_book_chapters(
    book_id: int,
) -> list[ChapterSchema]:
    """获取书籍章节列表"""
    from zhihu_downloader.infra.database import get_session

    async with get_session() as session:
        repo = BookRepository(session)
        book = await repo.get(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="书籍不存在")

        chapters = []
        for idx in range(1, book.chapter_count + 1):
            chapters.append(
                ChapterSchema(
                    id=f"{book_id}-{idx}",
                    title=f"章节 {idx}",
                    url=f"{book.url}/chapter/{idx}",
                    order=idx,
                )
            )
        return chapters


def _model_to_schema(book: BookModel) -> BookDetailSchema:
    """将数据库模型转换为 schema"""
    return BookDetailSchema(
        id=book.id,
        url=book.url,
        title=book.title,
        author=book.author or "",
        chapter_count=book.chapter_count,
        cover_url=book.cover_url or "",
        description=book.description or "",
        source=book.source,
        last_sync_at=book.last_sync_at.isoformat() if book.last_sync_at else None,
        created_at=book.created_at.isoformat(),
        shelf_id=book.shelf_id,
    )
