"""Application-wide logging: console + rotating file + an in-memory ring
buffer that backs the dashboard's Logs page.

Call `setup_logging()` once at startup (run.py does this before anything
else is imported that might log). Every other module should just call
`get_logger(__name__)`.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import sys
import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.config.settings import settings

_CONFIGURED = False
_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_WEBHOOK_RE = re.compile(r"https://(discord|discordapp)\.com/api/webhooks/\S+")


def redact(text: str) -> str:
    """Mask anything that looks like a Discord webhook URL before it can
    reach a log line. Defense in depth: callers should already avoid
    logging secrets directly."""
    return _WEBHOOK_RE.sub("https://discord.com/api/webhooks/•••redacted•••", text)


@dataclass
class LogRecordEntry:
    timestamp: datetime
    level: str
    logger: str
    message: str


class RingBufferHandler(logging.Handler):
    """Keeps the last `capacity` log records in memory for the API/UI.

    A rotating file on disk remains the durable record; this handler exists
    purely so the dashboard can serve recent logs without re-parsing files.
    """

    def __init__(self, capacity: int = 2000) -> None:
        super().__init__()
        self._buffer: deque[LogRecordEntry] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        entry = LogRecordEntry(
            timestamp=datetime.fromtimestamp(record.created, tz=UTC),
            level=record.levelname,
            logger=record.name,
            message=redact(record.getMessage()),
        )
        with self._lock:
            self._buffer.append(entry)

    def recent(
        self, *, limit: int = 200, level: str | None = None
    ) -> list[LogRecordEntry]:
        with self._lock:
            items = list(self._buffer)
        if level:
            items = [i for i in items if i.level == level.upper()]
        return items[-limit:][::-1]


_ring_handler = RingBufferHandler()


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    root.handlers.clear()

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    _ring_handler.setFormatter(formatter)
    root.addHandler(_ring_handler)

    if settings.log_level.upper() != "DEBUG":
        for noisy in ("httpx", "httpcore", "playwright", "uvicorn.access"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    if not _CONFIGURED:
        setup_logging()
    return logging.getLogger(name)


def get_recent_logs(*, limit: int = 200, level: str | None = None) -> list[LogRecordEntry]:
    return _ring_handler.recent(limit=limit, level=level)
