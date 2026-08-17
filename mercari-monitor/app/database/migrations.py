"""Lightweight, dependency-free schema migrations for SQLite.

This is a single-database, single-user local tool, so we avoid pulling in
Alembic: migrations are small, ordered, idempotent steps tracked in a
`schema_migrations` table. `run_migrations()` is safe to call on every
startup — already-applied versions are skipped.

To evolve the schema later: update `app/database/models.py` AND append a
new `(version, name, function)` entry to `_MIGRATIONS` that performs the
equivalent SQL change (e.g. `ALTER TABLE ... ADD COLUMN ...`). Never edit an
already-shipped migration in place.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.database.models import Base
from app.utils.logger import get_logger

logger = get_logger(__name__)

MigrationFunc = Callable[[AsyncConnection], Awaitable[None]]
Migration = tuple[int, str, MigrationFunc]


async def _create_initial_schema(conn: AsyncConnection) -> None:
    await conn.run_sync(Base.metadata.create_all)


_MIGRATIONS: list[Migration] = [
    (1, "create_initial_schema", _create_initial_schema),
]


async def _ensure_migrations_table(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
    )


async def _applied_versions(conn: AsyncConnection) -> set[int]:
    result = await conn.execute(text("SELECT version FROM schema_migrations"))
    return {row[0] for row in result.fetchall()}


async def run_migrations(engine: AsyncEngine | Engine) -> None:
    async with engine.begin() as conn:
        await _ensure_migrations_table(conn)
        applied = await _applied_versions(conn)

        for version, name, func in _MIGRATIONS:
            if version in applied:
                continue
            logger.info("Applying migration %s: %s", version, name)
            await func(conn)
            await conn.execute(
                text("INSERT INTO schema_migrations (version, name) VALUES (:v, :n)"),
                {"v": version, "n": name},
            )
