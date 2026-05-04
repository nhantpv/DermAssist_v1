"""Integration tests for hybrid retrieval. Requires DB seeded with
QĐ-4416 chunks (run scripts/seed_kb_chunks.py first)."""
from __future__ import annotations

import asyncio
import os
from importlib import reload

import pytest
import pytest_asyncio
from sqlalchemy import text

pytest.importorskip("sentence_transformers")


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
        "Postgres not reachable — skipping retrieval integration tests. "
        "Start it with `docker compose up -d` and seed via "
        "`python scripts/seed_kb_chunks.py`."
    ),
)


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine():
    """Dispose the async engine after each test so the next test's
    new event loop gets a fresh connection pool. Without this the
    engine's pool stays bound to the first loop and later tests hit
    'Event loop is closed' on connection ping."""
    yield
    from backend.db import engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_retrieve_returns_chunks():
    from backend.retrieval import retrieve
    results = await retrieve("điều trị zona thần kinh", k=5)
    assert isinstance(results, list)
    assert 0 < len(results) <= 5
    for chunk in results:
        assert chunk.chunk_id
        assert chunk.text
        assert chunk.score > 0


@pytest.mark.asyncio
async def test_retrieve_empty_query_returns_empty():
    from backend.retrieval import retrieve
    assert await retrieve("") == []
    assert await retrieve("   ") == []


@pytest.mark.asyncio
async def test_retrieve_respects_condition_filter():
    """Filtered query should only return chunks tagged with the filter."""
    from backend.retrieval import retrieve
    results = await retrieve(
        "điều trị",
        k=10,
        condition_filter=["herpes_zoster"],
    )
    if results:
        for chunk in results:
            assert "herpes_zoster" in chunk.condition_tags, (
                f"Chunk {chunk.chunk_id} has tags {chunk.condition_tags}, "
                f"expected herpes_zoster"
            )


@pytest.mark.asyncio
async def test_retrieve_relevant_to_query():
    """Sanity check: query about acyclovir should surface zoster-related
    chunks, since acyclovir is the standard zoster treatment."""
    from backend.retrieval import retrieve
    results = await retrieve("acyclovir liều dùng", k=5)
    assert len(results) > 0
    text_blob = " ".join(c.text.lower() for c in results)
    assert ("zona" in text_blob or
            "acyclovir" in text_blob or
            "herpes" in text_blob), (
        "No retrieved chunk mentions zoster/acyclovir/herpes — "
        "check seed quality and BM25 vs dense balance"
    )


@pytest.mark.asyncio
async def test_retrieve_top_k_distinct():
    """Top-K results should have unique chunk_ids."""
    from backend.retrieval import retrieve
    results = await retrieve("chẩn đoán da liễu", k=10)
    ids = [c.chunk_id for c in results]
    assert len(ids) == len(set(ids))


@pytest.mark.asyncio
async def test_retrieve_rrf_ordering():
    """Score should be monotonically non-increasing."""
    from backend.retrieval import retrieve
    results = await retrieve("viêm da", k=10)
    if len(results) >= 2:
        scores = [c.score for c in results]
        assert scores == sorted(scores, reverse=True), (
            f"RRF results not in score-desc order: {scores}"
        )


@pytest.mark.asyncio
async def test_retrieve_falls_back_to_bm25_when_embedder_fails(monkeypatch):
    """AC-Q1: if embedder raises, retrieve still returns BM25-only results."""
    from backend.retrieval import rrf as rrf_mod

    def _broken_embed(_text):
        raise RuntimeError("simulated embedder failure")

    monkeypatch.setattr(rrf_mod, "embed_query", _broken_embed)
    results = await rrf_mod.retrieve("zona thần kinh", k=5)
    assert isinstance(results, list)
    assert len(results) > 0, "BM25 fallback should still produce results"
