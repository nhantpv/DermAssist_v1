"""Integration tests for TIP-006 page surface.

Skips if Postgres is not reachable (re-uses the pattern from
test_auth_flow.py).
"""
from __future__ import annotations

import asyncio
import io
import os
from importlib import reload

import httpx
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


def _make_png_bytes(size: tuple[int, int] = (64, 64)) -> bytes:
    img = Image.new("RGB", size, color=(200, 100, 100))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# === Public pages ===

async def test_root_anonymous_redirects_to_login(client: httpx.AsyncClient):
    resp = await client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


async def test_root_authenticated_redirects_to_encounters_new(
    client: httpx.AsyncClient,
):
    cookie = await _login_demo(client)
    resp = await client.get(
        "/",
        cookies={"dermassist_session": cookie},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/encounters/new"


async def test_login_page_renders_html(client: httpx.AsyncClient):
    resp = await client.get("/login")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    assert "DermAssist" in body
    assert "Đăng nhập" in body
    assert "Closed beta" in body
    assert "name=\"username\"" in body


async def test_about_page_renders(client: httpx.AsyncClient):
    resp = await client.get("/about")
    assert resp.status_code == 200
    assert "DermAssist" in resp.text


# === Auth-gated pages ===

async def test_encounters_list_requires_auth(client: httpx.AsyncClient):
    resp = await client.get("/encounters", follow_redirects=False)
    assert resp.status_code == 401


async def test_encounters_new_requires_auth(client: httpx.AsyncClient):
    resp = await client.get("/encounters/new", follow_redirects=False)
    assert resp.status_code == 401


async def test_encounters_list_authenticated_renders(client: httpx.AsyncClient):
    cookie = await _login_demo(client)
    resp = await client.get(
        "/encounters",
        cookies={"dermassist_session": cookie},
    )
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    assert "Lịch sử encounter" in body


async def test_encounters_new_authenticated_renders(client: httpx.AsyncClient):
    cookie = await _login_demo(client)
    resp = await client.get(
        "/encounters/new",
        cookies={"dermassist_session": cookie},
    )
    assert resp.status_code == 200
    body = resp.text
    assert "Phân tích ảnh tổn thương" in body
    assert "name=\"image\"" in body
    assert "name=\"clinical_note\"" in body


# === Encounter create stub ===

async def test_encounter_create_stub_redirects_to_detail(client: httpx.AsyncClient):
    cookie = await _login_demo(client)
    png = _make_png_bytes()
    files = {"image": ("test.png", png, "image/png")}
    data = {
        "clinical_note": "Test note",
        "age_years": "35",
        "sex": "M",
        "symptom_duration_days": "14",
    }
    resp = await client.post(
        "/encounters/create",
        cookies={"dermassist_session": cookie},
        files=files,
        data=data,
        follow_redirects=False,
    )
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("/encounters/")
    encounter_id = location.rsplit("/", 1)[-1]
    assert len(encounter_id) > 10  # UUID-ish

    detail = await client.get(
        location,
        cookies={"dermassist_session": cookie},
    )
    assert detail.status_code == 200
    assert "Chẩn đoán đang được xử lý" in detail.text  # stub state


async def test_encounter_create_rejects_oversized_image(client: httpx.AsyncClient):
    cookie = await _login_demo(client)
    huge = b"\x00" * (8 * 1024 * 1024 + 100)
    files = {"image": ("big.png", huge, "image/png")}
    resp = await client.post(
        "/encounters/create",
        cookies={"dermassist_session": cookie},
        files=files,
        data={"clinical_note": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "quá lớn" in resp.json()["error"]


async def test_encounter_create_rejects_bad_content_type(client: httpx.AsyncClient):
    cookie = await _login_demo(client)
    files = {"image": ("evil.exe", b"\x00\x01\x02", "application/octet-stream")}
    resp = await client.post(
        "/encounters/create",
        cookies={"dermassist_session": cookie},
        files=files,
        data={"clinical_note": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "không hỗ trợ" in resp.json()["error"]


async def test_encounter_detail_404_for_unknown_id(client: httpx.AsyncClient):
    cookie = await _login_demo(client)
    resp = await client.get(
        "/encounters/00000000-0000-0000-0000-000000000000",
        cookies={"dermassist_session": cookie},
        follow_redirects=False,
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "Không tìm thấy encounter."


# === Finalize ===

async def test_finalize_round_trip(client: httpx.AsyncClient):
    cookie = await _login_demo(client)
    # Create encounter
    files = {"image": ("test.png", _make_png_bytes(), "image/png")}
    create_resp = await client.post(
        "/encounters/create",
        cookies={"dermassist_session": cookie},
        files=files,
        data={"clinical_note": "n"},
        follow_redirects=False,
    )
    encounter_url = create_resp.headers["location"]
    encounter_id = encounter_url.rsplit("/", 1)[-1]

    # Finalize
    fin_resp = await client.post(
        f"/encounters/{encounter_id}/finalize",
        cookies={"dermassist_session": cookie},
        data={
            "doctor_diagnosis": "Viêm da cơ địa (xác nhận)",
            "doctor_tier": "outpatient_72h",
            "doctor_notes": "Tái khám 1 tuần.",
        },
        follow_redirects=False,
    )
    assert fin_resp.status_code == 303

    # Detail page should now show finalized block
    detail = await client.get(
        encounter_url,
        cookies={"dermassist_session": cookie},
    )
    assert detail.status_code == 200
    assert "Bác sĩ đã hoàn tất chẩn đoán" in detail.text
    assert "Viêm da cơ địa (xác nhận)" in detail.text


async def test_finalize_rejects_invalid_tier(client: httpx.AsyncClient):
    cookie = await _login_demo(client)
    files = {"image": ("test.png", _make_png_bytes(), "image/png")}
    create_resp = await client.post(
        "/encounters/create",
        cookies={"dermassist_session": cookie},
        files=files,
        data={"clinical_note": ""},
        follow_redirects=False,
    )
    encounter_id = create_resp.headers["location"].rsplit("/", 1)[-1]

    bad = await client.post(
        f"/encounters/{encounter_id}/finalize",
        cookies={"dermassist_session": cookie},
        data={
            "doctor_diagnosis": "X",
            "doctor_tier": "imaginary_tier",
            "doctor_notes": "",
        },
        follow_redirects=False,
    )
    assert bad.status_code == 400
    assert "Tier không hợp lệ." in bad.json()["error"]


# === Chat stub ===

async def test_chat_stub_returns_html_fragment(client: httpx.AsyncClient):
    cookie = await _login_demo(client)
    files = {"image": ("test.png", _make_png_bytes(), "image/png")}
    create_resp = await client.post(
        "/encounters/create",
        cookies={"dermassist_session": cookie},
        files=files,
        data={"clinical_note": ""},
        follow_redirects=False,
    )
    encounter_id = create_resp.headers["location"].rsplit("/", 1)[-1]

    resp = await client.post(
        "/chat/message",
        cookies={"dermassist_session": cookie},
        data={"encounter_id": encounter_id, "message": "Liều acyclovir?"},
    )
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    assert "Liều acyclovir?" in body  # echo
    assert "TIP-010" in body  # placeholder reply


async def test_chat_requires_auth(client: httpx.AsyncClient):
    resp = await client.post(
        "/chat/message",
        data={
            "encounter_id": "00000000-0000-0000-0000-000000000000",
            "message": "hello",
        },
    )
    assert resp.status_code == 401


# === Image serve auth gate ===

async def test_uploads_requires_auth(client: httpx.AsyncClient):
    resp = await client.get("/uploads/anything.png", follow_redirects=False)
    assert resp.status_code == 401


async def test_uploads_rejects_path_traversal(client: httpx.AsyncClient):
    cookie = await _login_demo(client)
    resp = await client.get(
        "/uploads/..%2Fetc%2Fpasswd",
        cookies={"dermassist_session": cookie},
        follow_redirects=False,
    )
    # Either 400 (rejected) or 404 (not found) is acceptable; never 200.
    assert resp.status_code in (400, 404)


# === Static + disclaimer banner ===

async def test_login_page_includes_disclaimer_banner(client: httpx.AsyncClient):
    resp = await client.get("/login")
    body = resp.text
    assert "Closed beta" in body
    assert "KHÔNG thay thế bác sĩ" in body or "Không thay thế bác sĩ" in body


async def test_static_app_css_served(client: httpx.AsyncClient):
    resp = await client.get("/static/app.css")
    assert resp.status_code == 200
    assert "htmx-indicator" in resp.text
