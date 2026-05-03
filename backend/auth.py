"""Auth: bcrypt password verify, JWT issue/verify, Google OAuth helpers,
FastAPI dependency.
"""
from datetime import datetime, timedelta, timezone
from typing import Annotated, TypedDict

import bcrypt
import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.db import get_db

_settings = get_settings()


class CurrentUser(TypedDict):
    id: str
    username: str
    role: str
    rate_limit_rpm: int
    email: str | None


# === Password verify (local accounts) ===

def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time bcrypt verify."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# === JWT ===

def create_access_token(*, sub: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=_settings.jwt_expiry_minutes)).timestamp()),
    }
    return jwt.encode(payload, _settings.jwt_secret_key, algorithm=_settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, _settings.jwt_secret_key, algorithms=[_settings.jwt_algorithm])


# === Google OAuth ===

GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


async def exchange_google_code(code: str) -> dict:
    """Exchange auth code for access token + ID token. Returns Google's
    token response dict."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": _settings.google_client_id,
                "client_secret": _settings.google_client_secret,
                "redirect_uri": _settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_google_userinfo(access_token: str) -> dict:
    """Fetch profile info using access token. Returns sub, email,
    name, picture."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            GOOGLE_USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()


# === Cookie session helpers (frontend uses cookies, not Bearer header) ===
# Decision per amendment: HTMX templates need automatic cookie attach;
# Bearer header flow is harder to wire. We issue JWT, store in
# httpOnly cookie. CSRF: SameSite=Lax (sufficient for closed beta).

JWT_COOKIE_NAME = "dermassist_session"


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        key=JWT_COOKIE_NAME,
        value=token,
        max_age=_settings.jwt_expiry_minutes * 60,
        httponly=True,
        samesite="lax",
        secure=False,  # set to True in TIP-013 production deploy
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(JWT_COOKIE_NAME)


# === FastAPI dependency ===

async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CurrentUser:
    """Read JWT from cookie, look up user, return CurrentUser dict.
    Raises 401 with Vietnamese message on failure.
    """
    creds_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Phiên đăng nhập không hợp lệ. Vui lòng đăng nhập lại.",
    )
    token = request.cookies.get(JWT_COOKIE_NAME)
    if not token:
        raise creds_error
    try:
        payload = decode_access_token(token)
        username: str | None = payload.get("sub")
        if not username:
            raise creds_error
    except jwt.PyJWTError as exc:
        raise creds_error from exc

    row = (
        await db.execute(
            text(
                "SELECT id::text AS id, username, role, rate_limit_rpm, email "
                "FROM users WHERE username = :u"
            ),
            {"u": username},
        )
    ).mappings().first()
    if row is None:
        raise creds_error
    return CurrentUser(**dict(row))
