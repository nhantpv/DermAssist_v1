"""Integration tests for the wired /chat/message route.

Mocks `chat_followup` so the test stays hermetic. Verifies persistence
into chat_messages, condition_filter routing through retrieve(), and
the rendered HTML fragment."""
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
    reason="Postgres not reachable — skipping wired chat tests.",
)


def _make_sharp_jpeg(size: int = 512) -> bytes:
    rng = np.random.default_rng(seed=7)
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


async def _login_demo(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        "/auth/login",
        data={"username": "demo", "password": "demo"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    return resp.cookies.get("dermassist_session")


def _patch_diagnose(monkeypatch, *, primary_condition_key: str):
    """Mock the orchestrator's diagnose() so creating an encounter
    doesn't hit OpenAI."""
    from backend.schemas import DiagnosisOutput

    diag = DiagnosisOutput(
        primary_diagnosis="Zona thần kinh",
        primary_condition_key=primary_condition_key,
        confidence=0.85,
        differential=[],
        key_features_observed=["Mụn nước theo dermatome"],
        management_tier="outpatient_24h",
        red_flags=[],
        ood_flag=False,
        image_quality_notes="",
        citations=[],
    )

    async def _stub(**kwargs):
        return diag

    monkeypatch.setattr("backend.orchestrator.diagnose", _stub)


async def _create_encounter(client, cookie) -> str:
    files = {"image": ("test.jpg", _make_sharp_jpeg(), "image/jpeg")}
    resp = await client.post(
        "/encounters/create",
        cookies={"dermassist_session": cookie},
        files=files,
        data={"clinical_note": "Phát ban đau rát một bên ngực."},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    return resp.headers["location"].rsplit("/", 1)[-1]


@pytest.mark.asyncio
async def test_chat_persists_user_and_assistant_turns(
    client: httpx.AsyncClient, monkeypatch
):
    """AC-C1: post a message → 2 rows in chat_messages, assistant has
    citations populated, returned HTML contains both messages."""
    from backend.db import SessionLocal
    from backend.vlm.chat import ChatResponse

    _patch_diagnose(monkeypatch, primary_condition_key="herpes_zoster")

    captured: dict = {}

    async def _fake_chat(*, prior_messages, current_message, rag_chunks):
        captured["prior_count"] = len(prior_messages)
        captured["current_message"] = current_message
        captured["rag_count"] = len(rag_chunks)
        return ChatResponse(
            content="Acyclovir 800mg, 5 lần/ngày trong 7 ngày. [chunk:abc-123]",
            citations=["abc-123"],
            latency_ms=120,
            chunks_used=[c.chunk_id for c in rag_chunks],
        )

    monkeypatch.setattr("backend.routes.chat.chat_followup", _fake_chat)

    cookie = await _login_demo(client)
    encounter_id = await _create_encounter(client, cookie)

    resp = await client.post(
        "/chat/message",
        cookies={"dermassist_session": cookie},
        data={"encounter_id": encounter_id, "message": "Liều acyclovir cho 70kg?"},
    )
    assert resp.status_code == 200
    body = resp.text
    assert "Liều acyclovir cho 70kg?" in body
    assert "Acyclovir 800mg" in body

    # 2 rows in chat_messages
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT role, content, citations FROM chat_messages "
                    " WHERE encounter_id = CAST(:eid AS uuid) "
                    " ORDER BY created_at ASC"
                ),
                {"eid": encounter_id},
            )
        ).mappings().all()
    assert len(rows) == 2
    assert rows[0]["role"] == "user"
    assert rows[1]["role"] == "assistant"
    assert rows[1]["citations"] == ["abc-123"]

    # First call: no prior turns (the inserted user turn is dropped)
    assert captured["prior_count"] == 0


@pytest.mark.asyncio
async def test_chat_uses_condition_filter_from_diagnosis(
    client: httpx.AsyncClient, monkeypatch
):
    """AC-C2: encounter result_json has primary_condition_key='herpes_zoster',
    chat retrieve() must pass condition_filter=['herpes_zoster']."""
    from backend.vlm.chat import ChatResponse

    _patch_diagnose(monkeypatch, primary_condition_key="herpes_zoster")

    captured: dict = {}

    async def _fake_retrieve(query, *, k=5, condition_filter=None):
        captured["condition_filter"] = condition_filter
        captured["k"] = k
        captured["query"] = query
        return []

    async def _fake_chat(**kwargs):
        return ChatResponse(content="reply", citations=[], latency_ms=1, chunks_used=[])

    monkeypatch.setattr("backend.routes.chat.retrieve", _fake_retrieve)
    monkeypatch.setattr("backend.routes.chat.chat_followup", _fake_chat)

    cookie = await _login_demo(client)
    encounter_id = await _create_encounter(client, cookie)

    resp = await client.post(
        "/chat/message",
        cookies={"dermassist_session": cookie},
        data={"encounter_id": encounter_id, "message": "Tác dụng phụ?"},
    )
    assert resp.status_code == 200
    assert captured["condition_filter"] == ["herpes_zoster"]
    assert captured["k"] == 3


@pytest.mark.asyncio
async def test_chat_no_filter_when_diagnosis_is_ood(
    client: httpx.AsyncClient, monkeypatch
):
    """primary_condition_key='other_ood' → no condition_filter (None)."""
    from backend.vlm.chat import ChatResponse

    _patch_diagnose(monkeypatch, primary_condition_key="other_ood")

    captured: dict = {}

    async def _fake_retrieve(query, *, k=5, condition_filter=None):
        captured["condition_filter"] = condition_filter
        return []

    async def _fake_chat(**kwargs):
        return ChatResponse(content="ok", citations=[], latency_ms=1, chunks_used=[])

    monkeypatch.setattr("backend.routes.chat.retrieve", _fake_retrieve)
    monkeypatch.setattr("backend.routes.chat.chat_followup", _fake_chat)

    cookie = await _login_demo(client)
    encounter_id = await _create_encounter(client, cookie)

    await client.post(
        "/chat/message",
        cookies={"dermassist_session": cookie},
        data={"encounter_id": encounter_id, "message": "Hello?"},
    )
    assert captured["condition_filter"] is None
