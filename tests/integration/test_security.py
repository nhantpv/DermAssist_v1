"""Cross-user scoping tests (TIP-011).

Two doctors are seeded ('demo' from migration 002, plus a second
'doctor2' created in fixture). doctor2 attempts to:
  - GET another doctor's uploaded image → 404
  - POST a chat message into another doctor's encounter → 404
  - POST finalize on another doctor's encounter → 404

Each path must 404 (never 200, never 500). 404 is preferred over 403
so resource existence isn't probeable across doctors.
"""
from __future__ import annotations

import asyncio
import io
import os
from importlib import reload

import bcrypt
import httpx
import numpy as np
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from PIL import Image
from sqlalchemy import text


def _db_reachable() -> bool:
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
    reason="Postgres not reachable — skipping security tests.",
)


_DOCTOR2_USERNAME = "doctor2_test"
_DOCTOR2_PASSWORD = "doctor2pwd"


def _make_sharp_jpeg(seed: int = 42, size: int = 512) -> bytes:
    rng = np.random.default_rng(seed=seed)
    base = rng.integers(0, 100, size=(size, size, 3), dtype=np.int32)
    arr = (base + 128 - 50).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


@pytest_asyncio.fixture
async def client():
    from backend import main as backend_main
    reload(backend_main)
    app = backend_main.app
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            yield ac


@pytest_asyncio.fixture
async def seed_doctor2():
    """Idempotently insert a second doctor for cross-user tests."""
    from sqlalchemy.ext.asyncio import create_async_engine

    pwd_hash = bcrypt.hashpw(
        _DOCTOR2_PASSWORD.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")
    eng = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with eng.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO users (username, password_hash, full_name, role) "
                    "VALUES (:u, :h, 'Doctor Two', 'doctor') "
                    "ON CONFLICT (username) DO NOTHING"
                ),
                {"u": _DOCTOR2_USERNAME, "h": pwd_hash},
            )
    finally:
        await eng.dispose()
    yield _DOCTOR2_USERNAME


async def _login(client: httpx.AsyncClient, username: str, password: str) -> str:
    resp = await client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code == 303, f"login failed for {username}: {resp.text[:200]}"
    cookie = resp.cookies.get("dermassist_session")
    assert cookie is not None
    return cookie


# === A: /uploads/{filename} — ownership gate ===

@pytest.mark.asyncio
async def test_uploads_404s_for_other_doctors_image(
    client: httpx.AsyncClient, mock_diagnose, seed_doctor2
):
    """AC-A2: doctor2 cannot fetch demo's uploaded image."""
    # demo creates an encounter
    demo_cookie = await _login(client, "demo", "demo")
    files = {"image": ("a.jpg", _make_sharp_jpeg(seed=10), "image/jpeg")}
    create = await client.post(
        "/encounters/create",
        cookies={"dermassist_session": demo_cookie},
        files=files,
        data={"clinical_note": "demo's encounter"},
        follow_redirects=False,
    )
    assert create.status_code == 303
    encounter_id = create.headers["location"].rsplit("/", 1)[-1]

    # Look up the image filename via the result page
    detail = await client.get(
        f"/encounters/{encounter_id}",
        cookies={"dermassist_session": demo_cookie},
    )
    assert detail.status_code == 200
    # Pull filename from /uploads/<sha>.jpg in body
    import re
    m = re.search(r'/uploads/([0-9a-f]{64}\.jpg)', detail.text)
    assert m, "no /uploads/<sha>.jpg link found in detail page"
    filename = m.group(1)

    # demo can fetch their own image
    own = await client.get(
        f"/uploads/{filename}",
        cookies={"dermassist_session": demo_cookie},
    )
    assert own.status_code == 200

    # doctor2 (different doctor) cannot
    d2_cookie = await _login(client, _DOCTOR2_USERNAME, _DOCTOR2_PASSWORD)
    cross = await client.get(
        f"/uploads/{filename}",
        cookies={"dermassist_session": d2_cookie},
    )
    assert cross.status_code == 404, (
        f"cross-user upload fetch should 404, got {cross.status_code}"
    )


@pytest.mark.asyncio
async def test_uploads_rejects_invalid_filename(
    client: httpx.AsyncClient, mock_diagnose
):
    """Path-traversal and non-hex names hit early 404 before DB lookup."""
    cookie = await _login(client, "demo", "demo")
    for bad in ["../etc/passwd", "abc.jpg", "GGGGGGGG.jpg"]:
        # path traversal goes through 400 (slash/.. check); enumeration
        # via short or non-hex names goes through 404 (sha-format check)
        resp = await client.get(
            f"/uploads/{bad}",
            cookies={"dermassist_session": cookie},
        )
        assert resp.status_code in (400, 404), (
            f"bad filename '{bad}' got status {resp.status_code}"
        )


# === B: /chat/message — encounter ownership ===

@pytest.mark.asyncio
async def test_chat_404s_for_other_doctors_encounter(
    client: httpx.AsyncClient, mock_diagnose, mock_chat_followup, seed_doctor2
):
    """AC-A3: doctor2 cannot post a chat message into demo's encounter."""
    demo_cookie = await _login(client, "demo", "demo")
    files = {"image": ("b.jpg", _make_sharp_jpeg(seed=11), "image/jpeg")}
    create = await client.post(
        "/encounters/create",
        cookies={"dermassist_session": demo_cookie},
        files=files,
        data={"clinical_note": "demo private"},
        follow_redirects=False,
    )
    assert create.status_code == 303
    encounter_id = create.headers["location"].rsplit("/", 1)[-1]

    d2_cookie = await _login(client, _DOCTOR2_USERNAME, _DOCTOR2_PASSWORD)
    resp = await client.post(
        "/chat/message",
        cookies={"dermassist_session": d2_cookie},
        data={"encounter_id": encounter_id, "message": "snoop"},
    )
    assert resp.status_code == 404


# === C: /encounters/{id}/finalize — encounter ownership ===

@pytest.mark.asyncio
async def test_finalize_404s_for_other_doctors_encounter(
    client: httpx.AsyncClient, mock_diagnose, seed_doctor2
):
    """AC-A4: doctor2 cannot finalize demo's encounter."""
    demo_cookie = await _login(client, "demo", "demo")
    files = {"image": ("c.jpg", _make_sharp_jpeg(seed=12), "image/jpeg")}
    create = await client.post(
        "/encounters/create",
        cookies={"dermassist_session": demo_cookie},
        files=files,
        data={"clinical_note": "demo private"},
        follow_redirects=False,
    )
    assert create.status_code == 303
    encounter_id = create.headers["location"].rsplit("/", 1)[-1]

    d2_cookie = await _login(client, _DOCTOR2_USERNAME, _DOCTOR2_PASSWORD)
    resp = await client.post(
        f"/encounters/{encounter_id}/finalize",
        cookies={"dermassist_session": d2_cookie},
        data={
            "doctor_diagnosis": "stolen finalize",
            "doctor_tier": "home_care",
            "doctor_notes": "",
        },
    )
    assert resp.status_code == 404
