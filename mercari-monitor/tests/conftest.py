"""Shared pytest fixtures.

Tests never touch the real `data/mercari.db`: each test that needs the
database gets its own temp-file SQLite database (a fresh engine/connection
pool), and the global engine is disposed before and after so no state or
open file handles leak between tests.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.config.settings import settings
from app.database.database import dispose_engine, get_engine, session_scope
from app.database.migrations import run_migrations


@pytest.fixture
async def test_db():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        original_url = settings.database_url
        settings.database_url = f"sqlite+aiosqlite:///{db_path}"
        await dispose_engine()
        await run_migrations(get_engine())
        try:
            yield
        finally:
            await dispose_engine()
            settings.database_url = original_url


@pytest.fixture
async def db_session(test_db):
    async with session_scope() as session:
        yield session
