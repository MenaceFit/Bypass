"""Keyword (search) CRUD + validation — the boundary between the API layer
and the database. API routes never touch `KeywordRepository` directly."""

from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import settings
from app.database.models import Keyword, KeywordStatus
from app.database.repositories import KeywordRepository
from app.utils.validation import (
    join_terms,
    validate_keyword,
    validate_price_range,
    validate_scan_interval,
)


@dataclass
class KeywordInput:
    keyword: str
    scan_interval: int | None = None
    discord_enabled: bool = True
    min_price: float | None = None
    max_price: float | None = None
    category: str | None = None
    brand: str | None = None
    size: str | None = None
    condition: str | None = None
    location: str | None = None
    sort: str = "newest"
    include_keywords: list[str] | None = None
    exclude_keywords: list[str] | None = None


class DuplicateKeywordError(Exception):
    pass


class KeywordService:
    def __init__(self, repo: KeywordRepository) -> None:
        self._repo = repo

    async def create(self, data: KeywordInput) -> Keyword:
        keyword_text = validate_keyword(data.keyword)
        interval = validate_scan_interval(data.scan_interval or settings.default_scan_interval)
        validate_price_range(data.min_price, data.max_price)

        if await self._repo.get_by_text(keyword_text) is not None:
            raise DuplicateKeywordError(f"A search for {keyword_text!r} already exists.")

        return await self._repo.create(
            keyword=keyword_text,
            scan_interval=interval,
            discord_enabled=data.discord_enabled,
            min_price=data.min_price,
            max_price=data.max_price,
            category=data.category,
            brand=data.brand,
            size=data.size,
            condition=data.condition,
            location=data.location,
            sort=data.sort or "newest",
            include_keywords=join_terms(data.include_keywords),
            exclude_keywords=join_terms(data.exclude_keywords),
            status=KeywordStatus.ACTIVE.value,
            active=True,
        )

    async def update(self, keyword_id: int, data: KeywordInput) -> Keyword | None:
        keyword_text = validate_keyword(data.keyword)
        interval = validate_scan_interval(data.scan_interval or settings.default_scan_interval)
        validate_price_range(data.min_price, data.max_price)

        existing = await self._repo.get_by_text(keyword_text)
        if existing is not None and existing.id != keyword_id:
            raise DuplicateKeywordError(f"A search for {keyword_text!r} already exists.")

        return await self._repo.update(
            keyword_id,
            keyword=keyword_text,
            scan_interval=interval,
            discord_enabled=data.discord_enabled,
            min_price=data.min_price,
            max_price=data.max_price,
            category=data.category,
            brand=data.brand,
            size=data.size,
            condition=data.condition,
            location=data.location,
            sort=data.sort or "newest",
            include_keywords=join_terms(data.include_keywords),
            exclude_keywords=join_terms(data.exclude_keywords),
        )

    async def delete(self, keyword_id: int) -> bool:
        return await self._repo.delete(keyword_id)

    async def set_active(self, keyword_id: int, active: bool) -> Keyword | None:
        return await self._repo.set_active(keyword_id, active)

    async def list_all(self) -> list[Keyword]:
        return await self._repo.list_all()

    async def get(self, keyword_id: int) -> Keyword | None:
        return await self._repo.get(keyword_id)

