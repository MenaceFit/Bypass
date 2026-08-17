#!/usr/bin/env python3
"""Entry point: `python run.py` starts the full application and opens the
dashboard in a browser once it's ready.

This does not install dependencies or build the frontend for you — see
README -> Installation for the one-time setup. If `frontend/dist` doesn't
exist yet, the backend still starts (the API and /docs work fine), and the
root path explains how to build it.
"""

from __future__ import annotations

import threading
import time
import webbrowser

import uvicorn

from app.config.settings import settings
from app.utils.logger import get_logger, setup_logging

setup_logging()
logger = get_logger("run")

_BANNER = """
┌───────────────────────────────────────────┐
│  MERCARI US MONITOR                        │
│  Starting backend, database, and the       │
│  Mercari browser client...                 │
└───────────────────────────────────────────┘
"""


def _open_browser_when_ready(url: str) -> None:
    time.sleep(2.0)
    try:
        webbrowser.open(url)
    except Exception:
        logger.info("Could not auto-open a browser — open %s manually.", url)


def main() -> None:
    print(_BANNER)
    url = f"http://{settings.app_host}:{settings.app_port}"

    threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True).start()

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        log_level=settings.log_level.lower(),
        reload=False,
    )


if __name__ == "__main__":
    main()
