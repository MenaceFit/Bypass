"""Central application settings, loaded from environment variables / .env.

All other modules must read configuration through `get_settings()` (or the
module-level `settings` singleton) rather than reading `os.environ`
directly, so behavior stays consistent and testable.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# mercari-monitor/ project root (three levels up from this file).
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---------------------------------------------------
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_env: Literal["development", "production", "test"] = "production"

    # --- Database --------------------------------------------------------
    database_url: str = Field(
        default_factory=lambda: f"sqlite+aiosqlite:///{(BASE_DIR / 'data' / 'mercari.db').as_posix()}"
    )

    # --- Scanning ----------------------------------------------------------
    default_scan_interval: int = Field(default=5, ge=1)
    min_scan_interval: int = Field(default=3, ge=1)

    # --- Rate limiting (global) ---------------------------------------------
    max_concurrent_requests: int = Field(default=3, ge=1, le=20)
    min_request_interval_ms: int = Field(default=800, ge=0)

    # --- HTTP / browser client -----------------------------------------------
    request_timeout: int = Field(default=10, ge=1)
    navigation_timeout_ms: int = Field(default=15000, ge=1000)
    browser_headless: bool = True
    # Advanced/optional: use a specific Chromium binary instead of
    # Playwright's own managed download (e.g. a system-installed Chromium,
    # or a browser provisioned by a container image). Leave unset for the
    # normal `playwright install chromium` flow.
    playwright_executable_path: str | None = None

    # --- Retry ---------------------------------------------------------------
    retry_max_attempts: int = Field(default=4, ge=1, le=10)
    retry_base_delay_ms: int = Field(default=250, ge=10)
    retry_max_delay_ms: int = Field(default=8000, ge=100)

    # --- Discord ---------------------------------------------------------------
    discord_webhook_url: str | None = None

    # --- Logging -----------------------------------------------------------
    log_level: str = "INFO"
    log_dir: str = Field(default_factory=lambda: str(BASE_DIR / "logs"))
    log_max_bytes: int = 5 * 1024 * 1024
    log_backup_count: int = 5

    # --- Timezone (storage is always UTC; this is display-only) -------------
    display_timezone: str = "UTC"

    # --- Retention -----------------------------------------------------------
    archive_after_days: int = Field(default=90, ge=1)

    # --- First run -------------------------------------------------------------
    first_run_mode: Literal["import_silent", "treat_as_new"] = "import_silent"

    @computed_field  # type: ignore[misc]
    @property
    def data_dir(self) -> Path:
        return BASE_DIR / "data"

    @computed_field  # type: ignore[misc]
    @property
    def frontend_dist_dir(self) -> Path:
        return BASE_DIR / "frontend" / "dist"

    @property
    def has_discord(self) -> bool:
        return bool(self.discord_webhook_url and self.discord_webhook_url.strip())

    def masked_discord_webhook(self) -> str | None:
        """Return a redacted representation safe to show in the UI/logs."""
        if not self.discord_webhook_url:
            return None
        url = self.discord_webhook_url
        if len(url) <= 12:
            return "•" * len(url)
        return f"{url[:20]}…{url[-4:]}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
