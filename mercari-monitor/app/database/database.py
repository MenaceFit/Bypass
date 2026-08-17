"""Async SQLAlchemy engine/session management.

A single module-level engine and session factory are lazily created and
reused for the process lifetime (`get_engine`, `get_session_factory`).
Tests override this by constructing their own engine against an in-memory
or temp-file database and calling `run_migrations` directly, rather than
mutating this module's globals.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import settings
from app.database.migrations import run_migrations
from app.utils.logger import get_logger

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # noqa: ANN001
    """Enable FK enforcement + WAL so background scans and API reads don't
    lock each other out. No-ops harmlessly for non-SQLite DBAPI connections."""
    if not hasattr(dbapi_connection, "execute"):
        return
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
    except Exception:  # pragma: no cover - defensive, non-sqlite DBAPI
        pass


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False} if "sqlite" in settings.database_url else {}
        _engine = create_async_engine(settings.database_url, echo=False, connect_args=connect_args)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional scope: commits on success, rolls back and re-raises on
    any exception. Use this for anything outside of FastAPI request handlers
    (background scan loop, Discord worker, startup code)."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, committed on success."""
    async with session_scope() as session:
        yield session


async def init_db() -> None:
    logger.info("Initializing database at %s", settings.database_url)
    await run_migrations(get_engine())


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
