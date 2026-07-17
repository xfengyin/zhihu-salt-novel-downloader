from __future__ import annotations

import builtins
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from zhihu_downloader.infra.models import APIKey, Book, Shelf, Task, User


class BookRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, book_id: int) -> Book | None:
        result = await self._session.execute(select(Book).where(Book.id == book_id))
        return result.scalar_one_or_none()

    async def get_by_url(self, url: str) -> Book | None:
        result = await self._session.execute(select(Book).where(Book.url == url))
        return result.scalar_one_or_none()

    async def list(self, user_id: int, shelf_id: int | None = None) -> builtins.list[Book]:
        query = select(Book).where(Book.user_id == user_id)
        if shelf_id is not None:
            query = query.where(Book.shelf_id == shelf_id)
        query = query.order_by(Book.created_at.desc())
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def upsert(self, book: Book) -> Book:
        existing = await self.get_by_url(book.url)
        if existing:
            existing.title = book.title
            existing.author = book.author
            existing.chapter_count = book.chapter_count
            existing.cover_url = book.cover_url
            existing.description = book.description
            existing.shelf_id = book.shelf_id
            existing.last_sync_at = book.last_sync_at
            self._session.add(existing)
            await self._session.commit()
            await self._session.refresh(existing)
            return existing
        else:
            self._session.add(book)
            await self._session.commit()
            await self._session.refresh(book)
            return book

    async def delete(self, book_id: int) -> bool:
        result: CursorResult[Any] = await self._session.execute(
            delete(Book).where(Book.id == book_id)
        )
        await self._session.commit()
        return bool(result.rowcount)


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, task: Task) -> Task:
        self._session.add(task)
        await self._session.commit()
        await self._session.refresh(task)
        return task

    async def get(self, task_id: int) -> Task | None:
        result = await self._session.execute(select(Task).where(Task.id == task_id))
        return result.scalar_one_or_none()

    async def get_by_idemp_key(self, idemp_key: str) -> Task | None:
        result = await self._session.execute(
            select(Task).where(Task.idemp_key == idemp_key)
        )
        return result.scalar_one_or_none()

    async def list_pending(self, user_id: int | None = None) -> list[Task]:
        query = select(Task).where(Task.status == "pending")
        if user_id is not None:
            query = query.where(Task.user_id == user_id)
        query = query.order_by(Task.created_at.asc())
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def update_status(
        self, task_id: int, status: str, result: dict[str, Any] | None = None
    ) -> bool:
        values: dict[str, Any] = {"status": status}
        if result is not None:
            values["result"] = result
        db_result: CursorResult[Any] = await self._session.execute(
            update(Task)
            .where(Task.id == task_id)
            .values(**values)
        )
        await self._session.commit()
        return bool(db_result.rowcount)

    async def increment_attempt(self, task_id: int, error: str | None = None) -> bool:
        db_result: CursorResult[Any] = await self._session.execute(
            update(Task)
            .where(Task.id == task_id)
            .values(
                attempts=Task.attempts + 1,
                last_error=error,
                updated_at=datetime.utcnow(),
            )
        )
        await self._session.commit()
        return bool(db_result.rowcount)


class ShelfRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, shelf_id: int) -> Shelf | None:
        result = await self._session.execute(select(Shelf).where(Shelf.id == shelf_id))
        return result.scalar_one_or_none()

    async def list(self, user_id: int) -> builtins.list[Shelf]:
        query = select(Shelf).where(Shelf.user_id == user_id).order_by(Shelf.created_at)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_default(self, user_id: int) -> Shelf | None:
        result = await self._session.execute(
            select(Shelf).where(Shelf.user_id == user_id, Shelf.is_default)
        )
        return result.scalar_one_or_none()

    async def create(self, shelf: Shelf) -> Shelf:
        if shelf.is_default:
            await self._clear_default(shelf.user_id)
        self._session.add(shelf)
        await self._session.commit()
        await self._session.refresh(shelf)
        return shelf

    async def update(self, shelf_id: int, **kwargs: Any) -> bool:
        if kwargs.get("is_default"):
            shelf = await self.get(shelf_id)
            if shelf:
                await self._clear_default(shelf.user_id)
        db_result: CursorResult[Any] = await self._session.execute(
            update(Shelf).where(Shelf.id == shelf_id).values(**kwargs)
        )
        await self._session.commit()
        return bool(db_result.rowcount)

    async def delete(self, shelf_id: int) -> bool:
        db_result: CursorResult[Any] = await self._session.execute(
            delete(Shelf).where(Shelf.id == shelf_id)
        )
        await self._session.commit()
        return bool(db_result.rowcount)

    async def _clear_default(self, user_id: int) -> None:
        await self._session.execute(
            update(Shelf)
            .where(Shelf.user_id == user_id, Shelf.is_default)
            .values(is_default=False)
        )


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: int) -> User | None:
        result = await self._session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create(self, user: User) -> User:
        self._session.add(user)
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def update(self, user_id: int, **kwargs: Any) -> bool:
        db_result: CursorResult[Any] = await self._session.execute(
            update(User).where(User.id == user_id).values(**kwargs)
        )
        await self._session.commit()
        return bool(db_result.rowcount)

    async def delete(self, user_id: int) -> bool:
        db_result: CursorResult[Any] = await self._session.execute(
            delete(User).where(User.id == user_id)
        )
        await self._session.commit()
        return bool(db_result.rowcount)


class APIKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, api_key: APIKey) -> APIKey:
        self._session.add(api_key)
        await self._session.commit()
        await self._session.refresh(api_key)
        return api_key

    async def get(self, key_id: int) -> APIKey | None:
        result = await self._session.execute(select(APIKey).where(APIKey.id == key_id))
        return result.scalar_one_or_none()

    async def get_by_key_hash(self, key_hash: str) -> APIKey | None:
        result = await self._session.execute(
            select(APIKey).where(APIKey.key_hash == key_hash)
        )
        return result.scalar_one_or_none()

    async def list(self, user_id: int) -> builtins.list[APIKey]:
        query = select(APIKey).where(APIKey.user_id == user_id).order_by(APIKey.created_at.desc())
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def delete(self, key_id: int) -> bool:
        db_result: CursorResult[Any] = await self._session.execute(
            delete(APIKey).where(APIKey.id == key_id)
        )
        await self._session.commit()
        return bool(db_result.rowcount)

    async def update_last_used(self, key_id: int) -> bool:
        db_result: CursorResult[Any] = await self._session.execute(
            update(APIKey)
            .where(APIKey.id == key_id)
            .values(last_used_at=datetime.utcnow())
        )
        await self._session.commit()
        return bool(db_result.rowcount)
