"""Image deduplication verification (TIP-011).

Two encounter creates with identical image bytes should:
  - produce 2 encounter rows (each its own encounter)
  - share the SAME image_sha256 value
  - share the SAME on-disk file (only one write)
  - emit an 'image_dedup_hit' audit row for the SECOND upload
"""
from __future__ import annotations

import asyncio
import io
import os
from importlib import reload
from pathlib import Path

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
    reason="Postgres not reachable — skipping dedup tests.",
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


def _make_jpeg(seed: int = 777, size: int = 512) -> bytes:
    rng = np.random.default_rng(seed=seed)
    base = rng.integers(0, 100, size=(size, size, 3), dtype=np.int32)
    arr = (base + 128 - 50).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


async def _login(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        "/auth/login",
        data={"username": "demo", "password": "demo"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    return resp.cookies.get("dermassist_session")


@pytest.mark.asyncio
async def test_same_image_dedups_on_disk_and_audits(
    client: httpx.AsyncClient, mock_diagnose
):
    """AC-B1, AC-B2, AC-C2: posting the same image twice → 2 encounters,
    1 file on disk, audit_log has 'image_dedup_hit' for the 2nd upload."""
    from sqlalchemy.ext.asyncio import create_async_engine

    cookie = await _login(client)
    image_bytes = _make_jpeg(seed=12345)

    # First upload
    r1 = await client.post(
        "/encounters/create",
        cookies={"dermassist_session": cookie},
        files={"image": ("dup.jpg", image_bytes, "image/jpeg")},
        data={"clinical_note": "first"},
        follow_redirects=False,
    )
    assert r1.status_code == 303
    eid1 = r1.headers["location"].rsplit("/", 1)[-1]

    # Second upload — same bytes
    r2 = await client.post(
        "/encounters/create",
        cookies={"dermassist_session": cookie},
        files={"image": ("dup-again.jpg", image_bytes, "image/jpeg")},
        data={"clinical_note": "second"},
        follow_redirects=False,
    )
    assert r2.status_code == 303
    eid2 = r2.headers["location"].rsplit("/", 1)[-1]
    assert eid1 != eid2, "two uploads must produce two distinct encounter rows"

    eng = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with eng.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id::text AS id, image_sha256, image_path "
                        "  FROM encounters "
                        " WHERE id IN (CAST(:e1 AS uuid), CAST(:e2 AS uuid))"
                    ),
                    {"e1": eid1, "e2": eid2},
                )
            ).mappings().all()
            assert len(rows) == 2
            sha_set = {r["image_sha256"] for r in rows}
            assert len(sha_set) == 1, (
                f"both rows should share the same sha256, got {sha_set}"
            )
            sha = next(iter(sha_set))
            paths = {r["image_path"] for r in rows}
            assert len(paths) == 1, "both rows should reference the same path"

        # AC-B1: one file on disk
        repo_root = Path(__file__).resolve().parents[2]
        on_disk = list((repo_root / "data" / "uploads").glob(f"{sha}.*"))
        assert len(on_disk) == 1, f"expected 1 file on disk for sha {sha}, got {on_disk}"

        # AC-B2: audit_log has image_dedup_hit for the 2nd upload's encounter_id
        async with eng.connect() as conn:
            dedup_rows = (
                await conn.execute(
                    text(
                        "SELECT encounter_id::text AS eid, details "
                        "  FROM audit_log "
                        " WHERE event_type = 'image_dedup_hit' "
                        "   AND image_sha256 = :sha "
                        " ORDER BY ts ASC"
                    ),
                    {"sha": sha},
                )
            ).mappings().all()

        # The dedup_hit audit fires on the 2nd upload only (1st created the file).
        assert len(dedup_rows) >= 1, (
            "expected at least one image_dedup_hit audit row for the 2nd upload"
        )
        # Backfill assigns encounter_id; one of the dedup rows should be eid2.
        eids = {r["eid"] for r in dedup_rows}
        assert eid2 in eids, (
            f"dedup audit should be linked to second encounter {eid2}, "
            f"got eids={eids}"
        )
    finally:
        await eng.dispose()
