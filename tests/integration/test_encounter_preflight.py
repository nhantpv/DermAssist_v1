"""End-to-end test of /encounters/create with preflight + redaction.

Skipped if DB not reachable. Logs in as demo, posts a known-blurry
image (rejected) and a known-sharp image with PII in the note (passes,
PII redacted, count=1+). Verifies persistence via direct SQL.
"""
from __future__ import annotations

import asyncio
import io
import os
from importlib import reload

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
    reason=(
        "Postgres not reachable — skipping integration tests. "
        "Start it with `docker compose up -d` and re-export DATABASE_URL."
    ),
)


def _make_jpeg(mean_intensity: int, *, sharp: bool, size: int = 512) -> bytes:
    """Helper: make a sharp or flat jpeg of given mean intensity."""
    if sharp:
        rng = np.random.default_rng(seed=99)
        # Mean-shifted noisy image
        base = rng.integers(0, 100, size=(size, size, 3), dtype=np.int32)
        arr = (base + mean_intensity - 50).clip(0, 255).astype(np.uint8)
    else:
        arr = np.full((size, size, 3), mean_intensity, dtype=np.uint8)
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _make_undersized_jpeg() -> bytes:
    arr = np.full((100, 100, 3), 200, dtype=np.uint8)
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
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


async def _login_demo(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        "/auth/login",
        data={"username": "demo", "password": "demo"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    cookie = resp.cookies.get("dermassist_session")
    assert cookie is not None
    return cookie


async def _count_encounters() -> int:
    """Count encounters for the demo user via fresh asyncpg engine."""
    from sqlalchemy.ext.asyncio import create_async_engine

    eng = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with eng.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) AS n FROM encounters "
                        "WHERE doctor_id = (SELECT id FROM users WHERE username='demo')"
                    )
                )
            ).mappings().first()
            return int(row["n"])
    finally:
        await eng.dispose()


async def _fetch_encounter(encounter_id: str) -> dict:
    from sqlalchemy.ext.asyncio import create_async_engine

    eng = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with eng.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT clinical_note, pii_redacted_count, "
                        "       preflight_blur_score, preflight_brightness, "
                        "       patient_context "
                        "  FROM encounters "
                        " WHERE id = CAST(:eid AS uuid)"
                    ),
                    {"eid": encounter_id},
                )
            ).mappings().first()
            assert row is not None
            return dict(row)
    finally:
        await eng.dispose()


# === Preflight failure paths ===

async def test_create_rejects_blurry_image(client: httpx.AsyncClient):
    cookie = await _login_demo(client)
    before = await _count_encounters()

    blurry_jpeg = _make_jpeg(128, sharp=False)
    files = {"image": ("blur.jpg", blurry_jpeg, "image/jpeg")}
    r = await client.post(
        "/encounters/create",
        data={"clinical_note": "test"},
        files=files,
        cookies={"dermassist_session": cookie},
        follow_redirects=False,
    )
    # Rerender with flash, NOT a 303 redirect to /encounters/...
    assert r.status_code == 400
    assert "mờ" in r.text

    # AC-E2: no row created for the rejected submit
    after = await _count_encounters()
    assert after == before


async def test_create_rejects_undersized_image(client: httpx.AsyncClient):
    cookie = await _login_demo(client)
    files = {"image": ("small.jpg", _make_undersized_jpeg(), "image/jpeg")}
    r = await client.post(
        "/encounters/create",
        data={"clinical_note": "test"},
        files=files,
        cookies={"dermassist_session": cookie},
        follow_redirects=False,
    )
    assert r.status_code == 400
    # AC-E7: dimension hint should be present
    assert "256" in r.text


async def test_create_rejects_garbage_image_bytes(client: httpx.AsyncClient):
    cookie = await _login_demo(client)
    files = {"image": ("evil.jpg", b"not actually an image", "image/jpeg")}
    r = await client.post(
        "/encounters/create",
        data={"clinical_note": ""},
        files=files,
        cookies={"dermassist_session": cookie},
        follow_redirects=False,
    )
    # AC-E8: undecodable image → flash with friendly Vietnamese message
    assert r.status_code == 400
    assert "Không thể đọc ảnh" in r.text


# === Preflight success + PII redaction path ===

async def test_create_passes_sharp_image_redacts_pii(client: httpx.AsyncClient):
    cookie = await _login_demo(client)
    sharp_jpeg = _make_jpeg(128, sharp=True)
    files = {"image": ("sharp.jpg", sharp_jpeg, "image/jpeg")}
    note_with_pii = "BN. Nguyen Van X, ĐT 0912345678, ngứa 14 ngày."
    r = await client.post(
        "/encounters/create",
        data={"clinical_note": note_with_pii, "age_years": "35", "sex": "M"},
        files=files,
        cookies={"dermassist_session": cookie},
        follow_redirects=False,
    )
    # AC-E3: 303 to /encounters/{id}
    assert r.status_code == 303
    location = r.headers["location"]
    assert location.startswith("/encounters/")
    encounter_id = location.rsplit("/", 1)[-1]

    # AC-E4: persisted state matches
    row = await _fetch_encounter(encounter_id)
    assert "[PII]" in row["clinical_note"]
    assert "ngứa 14 ngày" in row["clinical_note"]  # clinical content preserved
    assert row["pii_redacted_count"] >= 2          # name + phone
    assert row["preflight_blur_score"] is not None and row["preflight_blur_score"] > 100
    assert row["preflight_brightness"] is not None
    assert 0 <= row["preflight_brightness"] <= 255

    # AC-E4: patient_context is non-null JSON with the form values
    pc = row["patient_context"]
    assert pc is not None
    assert pc["age_years"] == 35
    assert pc["sex"] == "M"


async def test_create_passes_with_empty_note(client: httpx.AsyncClient):
    cookie = await _login_demo(client)
    sharp_jpeg = _make_jpeg(140, sharp=True)
    files = {"image": ("sharp2.jpg", sharp_jpeg, "image/jpeg")}
    r = await client.post(
        "/encounters/create",
        data={"clinical_note": ""},
        files=files,
        cookies={"dermassist_session": cookie},
        follow_redirects=False,
    )
    # AC-E5: 303 (preflight passed)
    assert r.status_code == 303
    encounter_id = r.headers["location"].rsplit("/", 1)[-1]

    # AC-E6: empty note persists as '' with count 0
    row = await _fetch_encounter(encounter_id)
    assert row["clinical_note"] == ""
    assert row["pii_redacted_count"] == 0


# === AC-E9: redaction count surfaces on result page ===

async def test_redaction_count_visible_on_result_page(client: httpx.AsyncClient):
    cookie = await _login_demo(client)
    sharp_jpeg = _make_jpeg(128, sharp=True)
    files = {"image": ("sharp3.jpg", sharp_jpeg, "image/jpeg")}
    r = await client.post(
        "/encounters/create",
        data={"clinical_note": "BN. Nguyen Van Y, ĐT 0912345678."},
        files=files,
        cookies={"dermassist_session": cookie},
        follow_redirects=False,
    )
    assert r.status_code == 303
    detail = await client.get(
        r.headers["location"],
        cookies={"dermassist_session": cookie},
    )
    assert detail.status_code == 200
    # Template renders "ⓘ N thông tin nhận dạng đã được loại bỏ." when count > 0
    assert "thông tin nhận dạng đã được loại bỏ" in detail.text
