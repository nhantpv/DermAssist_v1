"""Integration tests for the auth flow (TIP-005-CANONICAL-V1).

Skips with a friendly message if Postgres is unreachable. Uses
httpx.AsyncClient + asgi_lifespan.LifespanManager so the FastAPI
lifespan startup actually runs (which verifies the DB connection).
"""
from __future__ import annotations

import asyncio
import os
from importlib import reload

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from sqlalchemy import text


def _db_reachable() -> bool:
    """Best-effort check: can we open an asyncpg connection synchronously?"""
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return False

    async def _try() -> bool:
        eng = create_async_engine(db_url, pool_pre_ping=True)
        try:
            async with eng.begin() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
        finally:
            await eng.dispose()

    try:
        return asyncio.run(_try())
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_reachable(),
    reason=(
        "Postgres not reachable — skipping integration tests. "
        "Start it with `docker compose up -d` and re-export DATABASE_URL."
    ),
)


@pytest_asyncio.fixture
async def client():
    """Boot the app under LifespanManager and return an async test client."""
    from backend import main as backend_main

    # `main` imports `engine` at module import time. If a previous test left a
    # disposed engine in place, reload to get a fresh one.
    reload(backend_main)
    app = backend_main.app

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            yield ac


# === /health (no auth) ===

async def test_health_endpoint_returns_ok(client: httpx.AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# === local login flow ===

async def test_login_with_demo_credentials_sets_cookie(client: httpx.AsyncClient):
    resp = await client.post(
        "/auth/login",
        data={"username": "demo", "password": "demo"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    set_cookie = resp.headers.get("set-cookie", "")
    assert "dermassist_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "lax" in set_cookie.lower()


async def test_login_with_bad_password_returns_vietnamese_error(
    client: httpx.AsyncClient,
):
    resp = await client.post(
        "/auth/login",
        data={"username": "demo", "password": "wrong"},
        follow_redirects=False,
    )
    assert resp.status_code == 401
    assert "text/html" in resp.headers.get("content-type", "")
    # Error banner + login form re-rendered
    assert "Sai tên đăng nhập hoặc mật khẩu." in resp.text
    assert 'action="/auth/login"' in resp.text
    # Username preserved, password not
    assert 'value="demo"' in resp.text


async def test_login_with_unknown_username_returns_401(client: httpx.AsyncClient):
    resp = await client.post(
        "/auth/login",
        data={"username": "no_such_user", "password": "x"},
        follow_redirects=False,
    )
    assert resp.status_code == 401


# === /me ===

async def test_me_with_cookie_returns_user(client: httpx.AsyncClient):
    login = await client.post(
        "/auth/login",
        data={"username": "demo", "password": "demo"},
        follow_redirects=False,
    )
    cookie = login.cookies.get("dermassist_session")
    assert cookie is not None

    resp = await client.get(
        "/me", cookies={"dermassist_session": cookie}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "demo"
    assert body["role"] == "demo"
    assert "id" in body
    assert "rate_limit_rpm" in body


async def test_me_without_cookie_returns_401_vietnamese(client: httpx.AsyncClient):
    resp = await client.get("/me")
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"].startswith("Phiên đăng nhập không hợp lệ")


async def test_me_with_garbage_cookie_returns_401(client: httpx.AsyncClient):
    resp = await client.get(
        "/me", cookies={"dermassist_session": "garbage.not.a.token"}
    )
    assert resp.status_code == 401


# === /auth/logout ===

async def test_logout_clears_cookie(client: httpx.AsyncClient):
    resp = await client.post("/auth/logout", follow_redirects=False)
    assert resp.status_code == 303
    set_cookie = resp.headers.get("set-cookie", "")
    # Either Max-Age=0 or expires-in-the-past, depending on Starlette version.
    assert "dermassist_session=" in set_cookie
    assert ("Max-Age=0" in set_cookie) or ("max-age=0" in set_cookie) or (
        "1970" in set_cookie
    )


# === Google OAuth start (no real Google call) ===

async def test_google_start_returns_503_when_unconfigured(client: httpx.AsyncClient):
    """With GOOGLE_CLIENT_ID unset, /auth/google must surface a 503 with
    the Vietnamese 'chưa được cấu hình' message.
    """
    # Settings is lru_cache'd at module load, so clear and reload to pick up
    # an explicitly empty client_id for this test.
    from backend.config import get_settings

    get_settings.cache_clear()
    os.environ["GOOGLE_CLIENT_ID"] = ""
    os.environ["GOOGLE_CLIENT_SECRET"] = ""

    # Reload routes/auth so the module-level _settings reflects the cleared env.
    from backend.routes import auth as routes_auth

    reload(routes_auth)

    # Rebuild the app with the reloaded router.
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    app = FastAPI()

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request, exc):
        detail = exc.detail if isinstance(exc.detail, str) else "Lỗi máy chủ."
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": detail, "status_code": exc.status_code},
        )

    app.include_router(routes_auth.router)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
        resp = await ac.get("/auth/google", follow_redirects=False)
    assert resp.status_code == 503
    assert resp.json()["error"] == "Đăng nhập Google chưa được cấu hình."


async def test_google_start_redirects_when_configured(client: httpx.AsyncClient):
    """With OAuth configured, /auth/google must 303 to accounts.google.com
    with the standard query params present.
    """
    from backend.config import get_settings

    get_settings.cache_clear()
    os.environ["GOOGLE_CLIENT_ID"] = "fake-client-id.apps.googleusercontent.com"
    os.environ["GOOGLE_CLIENT_SECRET"] = "fake-client-secret"
    os.environ["GOOGLE_REDIRECT_URI"] = "http://localhost:8000/auth/google/callback"

    from backend.routes import auth as routes_auth

    reload(routes_auth)

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(routes_auth.router)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
        resp = await ac.get("/auth/google", follow_redirects=False)

    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=fake-client-id" in location
    assert "redirect_uri=" in location
    assert "scope=openid+email+profile" in location or "scope=openid%20email%20profile" in location

    # Cleanup so other tests aren't affected.
    os.environ["GOOGLE_CLIENT_ID"] = ""
    os.environ["GOOGLE_CLIENT_SECRET"] = ""
    get_settings.cache_clear()
