"""Auth routes: /auth/login (local), /auth/google (OAuth start),
/auth/google/callback (OAuth completion), /auth/logout, /me.
"""
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import (
    CurrentUser,
    clear_session_cookie,
    create_access_token,
    exchange_google_code,
    fetch_google_userinfo,
    get_current_user,
    set_session_cookie,
    verify_password,
)
from backend.config import get_settings
from backend.db import get_db

router = APIRouter(tags=["auth"])
_settings = get_settings()


@router.post("/auth/login")
async def login_local(
    db: Annotated[AsyncSession, Depends(get_db)],
    username: str = Form(...),
    password: str = Form(...),
):
    """Local login (demo/demo, evaluator fallback)."""
    row = (
        await db.execute(
            text(
                "SELECT id::text AS id, username, password_hash, role "
                "FROM users WHERE username = :u"
            ),
            {"u": username},
        )
    ).mappings().first()

    if row is None or not verify_password(password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sai tên đăng nhập hoặc mật khẩu.",
        )

    # Best-effort last_login update
    try:
        await db.execute(
            text("UPDATE users SET last_login_at = NOW() WHERE id = CAST(:id AS uuid)"),
            {"id": row["id"]},
        )
        await db.commit()
    except Exception:
        await db.rollback()

    token = create_access_token(sub=row["username"], role=row["role"])
    redirect = RedirectResponse(url="/encounters/new", status_code=303)
    set_session_cookie(redirect, token)
    return redirect


@router.get("/auth/google")
async def login_google_start():
    """Redirect to Google's OAuth consent screen."""
    if not _settings.google_oauth_enabled:
        raise HTTPException(
            status_code=503,
            detail="Đăng nhập Google chưa được cấu hình.",
        )
    params = {
        "client_id": _settings.google_client_id,
        "redirect_uri": _settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
    }
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    return RedirectResponse(url=url, status_code=303)


@router.get("/auth/google/callback")
async def login_google_callback(
    code: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Handle Google OAuth callback: exchange code, fetch userinfo,
    upsert user, issue JWT cookie.
    """
    if not _settings.google_oauth_enabled:
        raise HTTPException(status_code=503, detail="OAuth chưa được cấu hình.")

    try:
        token_resp = await exchange_google_code(code)
        userinfo = await fetch_google_userinfo(token_resp["access_token"])
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Đăng nhập Google thất bại: {type(e).__name__}",
        ) from e

    google_sub = userinfo["sub"]
    email = userinfo.get("email")
    # Username = email if available, else google_<short_sub>.
    username = email or f"google_{google_sub[:8]}"

    existing = (
        await db.execute(
            text(
                "SELECT id::text AS id, username, role "
                "FROM users WHERE google_sub = :s"
            ),
            {"s": google_sub},
        )
    ).mappings().first()

    if existing:
        # Returning user; update last_login
        await db.execute(
            text(
                "UPDATE users SET last_login_at = NOW(), email = :e "
                "WHERE google_sub = :s"
            ),
            {"e": email, "s": google_sub},
        )
        username_to_token = existing["username"]
        role_to_token = existing["role"]
    else:
        # New user; insert with placeholder password_hash (never used)
        await db.execute(
            text(
                "INSERT INTO users (username, password_hash, role, google_sub, email, "
                "rate_limit_rpm, created_at, last_login_at) "
                "VALUES (:u, :ph, :r, :s, :e, :rpm, NOW(), NOW()) "
                "ON CONFLICT (username) DO UPDATE SET "
                "  google_sub = EXCLUDED.google_sub, email = EXCLUDED.email, "
                "  last_login_at = NOW()"
            ),
            {
                "u": username,
                "ph": "$2b$12$oauth_placeholder_never_used_xxxxxxxxxxxxxxxxxxxxxxxxxx",
                "r": "doctor",
                "s": google_sub,
                "e": email,
                "rpm": 30,  # higher than demo's 10, lower than no-limit
            },
        )
        username_to_token = username
        role_to_token = "doctor"

    await db.commit()

    token = create_access_token(sub=username_to_token, role=role_to_token)
    redirect = RedirectResponse(url="/encounters/new", status_code=303)
    set_session_cookie(redirect, token)
    return redirect


@router.post("/auth/logout")
async def logout():
    redirect = RedirectResponse(url="/login", status_code=303)
    clear_session_cookie(redirect)
    return redirect


@router.get("/me")
async def read_me(user: Annotated[CurrentUser, Depends(get_current_user)]):
    return user
