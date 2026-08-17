"""End-to-end smoke test: does the actual FastAPI app boot — real database
init, a real (Chromium) Mercari browser client, the monitoring service,
the Discord worker — and serve the documented API surface?

Uses `TestClient` as a context manager specifically so FastAPI's lifespan
(spec section 79's startup checklist) actually runs, not a mocked version
of it. Monitoring is paused immediately after startup: this test exercises
real CRUD + the real app wiring, but must not let a spawned scan task make
a real request to mercari.com, which this development sandbox's network
policy blocks outright (see README -> Limitations) and which would make
the test flaky/slow for reasons unrelated to what it's actually checking.

All assertions share a single TestClient/app lifecycle (one real browser
launch) rather than one per test: Playwright's asyncio subprocess driver
does not tear down cleanly across many independent event loops in one
process, which is a test-harness quirk, not an application bug — the
per-assertion browser mechanics are already covered independently by
test_mercari_client.py.

Skips automatically if no Chromium binary is available.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient
from playwright.async_api import async_playwright

from app.config.settings import settings


async def _browser_available() -> bool:
    try:
        async with async_playwright() as p:
            kwargs = (
                {"executable_path": settings.playwright_executable_path}
                if settings.playwright_executable_path
                else {}
            )
            browser = await p.chromium.launch(headless=True, **kwargs)
            await browser.close()
        return True
    except Exception:
        return False


def test_full_api_smoke() -> None:
    if not anyio.run(_browser_available):
        pytest.skip("No Chromium binary available in this environment")

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_app.db"
        original_url = settings.database_url
        settings.database_url = f"sqlite+aiosqlite:///{db_path}"
        try:
            _run_smoke_suite()
        finally:
            settings.database_url = original_url


def _run_smoke_suite() -> None:
    from app.main import app

    with TestClient(app) as client:
        # Prevent any spawned scan task from making a real request against
        # mercari.com during this test — see module docstring.
        client.post("/api/monitoring/pause-all")

        _check_health(client)
        _check_openapi(client)
        _check_search_lifecycle(client)
        _check_validation_error(client)
        _check_websocket(client)
        _check_read_endpoints(client)
        _check_discord_test_without_webhook(client)
        _check_settings_roundtrip(client)
        _check_database_reset(client)


def _check_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["database"] is True
    assert "mercari" in body
    assert body["websocket"] is True


def _check_openapi(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Mercari US Monitor"


def _check_search_lifecycle(client: TestClient) -> None:
    create_resp = client.post("/api/searches", json={"keyword": "Nike ACG", "scan_interval": 5})
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["keyword"] == "Nike ACG"
    assert created["status"] == "ACTIVE"
    search_id = created["id"]

    list_resp = client.get("/api/searches")
    assert list_resp.status_code == 200
    assert any(s["id"] == search_id for s in list_resp.json())

    dup_resp = client.post("/api/searches", json={"keyword": "Nike ACG"})
    assert dup_resp.status_code == 409

    pause_resp = client.post(f"/api/searches/{search_id}/pause")
    assert pause_resp.status_code == 200
    assert pause_resp.json()["active"] is False
    assert pause_resp.json()["status"] == "PAUSED"

    resume_resp = client.post(f"/api/searches/{search_id}/resume")
    assert resume_resp.status_code == 200
    assert resume_resp.json()["active"] is True

    delete_resp = client.delete(f"/api/searches/{search_id}")
    assert delete_resp.status_code == 200

    missing_resp = client.get(f"/api/searches/{search_id}")
    assert missing_resp.status_code == 404


def _check_validation_error(client: TestClient) -> None:
    response = client.post(
        "/api/searches", json={"keyword": "Bad Range", "min_price": 100, "max_price": 10}
    )
    assert response.status_code == 422


def _check_websocket(client: TestClient) -> None:
    with client.websocket_connect("/ws"):
        pass  # connecting and cleanly disconnecting is the assertion


def _check_read_endpoints(client: TestClient) -> None:
    assert client.get("/api/stats").status_code == 200
    assert client.get("/api/settings").status_code == 200
    assert client.get("/api/logs").status_code == 200
    assert client.get("/api/listings").status_code == 200


def _check_discord_test_without_webhook(client: TestClient) -> None:
    response = client.post("/api/discord/test")
    assert response.status_code == 200
    assert response.json()["success"] is False


def _check_settings_roundtrip(client: TestClient) -> None:
    response = client.put(
        "/api/settings", json={"theme": "light", "sound_notifications_enabled": True}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["theme"] == "light"
    assert body["sound_notifications_enabled"] is True


def _check_database_reset(client: TestClient) -> None:
    bad = client.post("/api/database/reset", json={"confirm": "yes please"})
    assert bad.status_code == 400

    good = client.post("/api/database/reset", json={"confirm": "DELETE ALL DATA"})
    assert good.status_code == 200
