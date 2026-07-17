from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)


class DatabaseConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DB_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    type: str = "sqlite"
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    database: str = "zhihu_downloader.db"
    connect_args: dict | None = None
    echo: bool = False
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: int = 30
    pool_recycle: int = 3600
    wal_mode: bool = True

    @property
    def url(self) -> str:
        if self.type == "postgresql":
            return (
                f"postgresql+asyncpg://{self.username}:{self.password}"
                f"@{self.host}:{self.port}/{self.database}"
            )
        return f"sqlite+aiosqlite:///{self.database}"


class DatabaseManager:
    def __init__(self, config: DatabaseConfig | None = None) -> None:
        self._config = config or DatabaseConfig()
        self._engine: AsyncEngine | None = None
        self._session_maker: async_sessionmaker[AsyncSession] | None = None

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            self._engine = self._create_engine()
        return self._engine

    @property
    def session_maker(self) -> async_sessionmaker[AsyncSession]:
        if self._session_maker is None:
            self._session_maker = async_sessionmaker(
                bind=self.engine,
                autocommit=False,
                autoflush=False,
                expire_on_commit=False,
            )
        return self._session_maker

    def _create_engine(self) -> AsyncEngine:
        url = self._config.url
        connect_args = self._config.connect_args or {}

        if self._config.type == "sqlite" and self._config.wal_mode:
            connect_args.setdefault("check_same_thread", False)

        engine = create_async_engine(
            url=url,
            echo=self._config.echo,
            connect_args=connect_args,
            pool_size=self._config.pool_size,
            max_overflow=self._config.max_overflow,
            pool_timeout=self._config.pool_timeout,
            pool_recycle=self._config.pool_recycle,
        )
        logger.info(f"Created async database engine: {self._config.type}")
        return engine

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self.session_maker() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def init_database(self) -> None:
        from zhihu_downloader.infra.models import Base

        async with self.engine.begin() as conn:
            if self._config.type == "sqlite" and self._config.wal_mode:
                await conn.execute(text("PRAGMA journal_mode=WAL;"))
                await conn.execute(text("PRAGMA synchronous=NORMAL;"))
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized successfully")

    async def health_check(self) -> bool:
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1;"))
            logger.info("Database health check passed")
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    async def dispose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            logger.info("Database engine disposed")


_config: DatabaseConfig | None = None
_manager: DatabaseManager | None = None


def get_config() -> DatabaseConfig:
    global _config
    if _config is None:
        _config = DatabaseConfig()
    return _config


def get_manager() -> DatabaseManager:
    global _manager
    if _manager is None:
        _manager = DatabaseManager(get_config())
    return _manager


def create_engine(config: DatabaseConfig | None = None) -> AsyncEngine:
    return get_manager().engine


@asynccontextmanager
async def get_session(
    config: DatabaseConfig | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    manager = get_manager()
    async with manager.get_session() as session:
        yield session


async def init_database(config: DatabaseConfig | None = None) -> None:
    manager = get_manager()
    await manager.init_database()


async def health_check(config: DatabaseConfig | None = None) -> bool:
    manager = get_manager()
    return await manager.health_check()


async def dispose(config: DatabaseConfig | None = None) -> None:
    manager = get_manager()
    await manager.dispose()
