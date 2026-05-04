"""Reciprocal Rank Fusion of BM25 + dense, plus the public retrieve() API.

RRF formula: score(d) = Σ_r 1 / (k + rank_r(d)) over each retriever r.
k=60 is the paper-default constant (Cormack 2009). We don't tune it.
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import SessionLocal
from backend.retrieval.bm25 import bm25_search
from backend.retrieval.dense import dense_search
from backend.retrieval.embed import embed_query
from backend.retrieval.models import Chunk

logger = logging.getLogger(__name__)

RRF_K = 60
DEFAULT_CANDIDATES = 20
DEFAULT_TOP_K = 5


def fuse_rrf(
    bm25_results: list[tuple[str, float]],
    dense_results: list[tuple[str, float]],
    *,
    rrf_k: int = RRF_K,
) -> list[tuple[str, float]]:
    """Pure RRF fusion. Inputs are (chunk_id, original_score) lists,
    each already sorted desc by score. Returns (chunk_id, rrf_score)
    sorted desc by rrf_score.
    """
    rrf_scores: dict[str, float] = {}

    for rank, (cid, _) in enumerate(bm25_results, start=1):
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (rrf_k + rank)

    for rank, (cid, _) in enumerate(dense_results, start=1):
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (rrf_k + rank)

    return sorted(rrf_scores.items(), key=lambda kv: kv[1], reverse=True)


async def _hydrate_chunks(
    db: AsyncSession,
    chunk_ids: list[str],
    rrf_score_by_id: dict[str, float],
) -> list[Chunk]:
    """Bulk-fetch chunk rows by id, return Chunk dataclasses in
    rrf-score order."""
    if not chunk_ids:
        return []

    rows = (
        await db.execute(
            text(
                "SELECT id::text AS chunk_id, doc_id, section_title, text, "
                "       chunk_index, condition_tags, source_url "
                "  FROM kb_chunks "
                " WHERE id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": chunk_ids},
        )
    ).mappings().all()

    by_id = {r["chunk_id"]: r for r in rows}
    out: list[Chunk] = []
    for cid in chunk_ids:
        r = by_id.get(cid)
        if r is None:
            logger.warning("RRF returned chunk_id %s not found in DB", cid)
            continue
        out.append(
            Chunk(
                chunk_id=r["chunk_id"],
                doc_id=r["doc_id"],
                section_title=r["section_title"],
                text=r["text"],
                chunk_index=r["chunk_index"],
                condition_tags=list(r["condition_tags"] or []),
                source_url=r.get("source_url"),
                score=rrf_score_by_id[cid],
            )
        )
    return out


async def retrieve(
    query: str,
    *,
    k: int = DEFAULT_TOP_K,
    condition_filter: list[str] | None = None,
    candidates_per_retriever: int = DEFAULT_CANDIDATES,
) -> list[Chunk]:
    """Hybrid retrieve. Public API consumed by TIP-010.

    Embeds query, runs BM25 + dense in series (Postgres pool handles
    concurrency), fuses via RRF, returns top-K hydrated Chunks.

    Empty query → empty list. No exceptions raised.
    """
    if not query or not query.strip():
        return []

    try:
        query_vec = embed_query(query)
    except Exception as e:
        logger.exception("Query embedding failed: %s", e)
        query_vec = None

    async with SessionLocal() as db:
        bm25 = await bm25_search(
            db, query, limit=candidates_per_retriever,
            condition_filter=condition_filter,
        )
        if query_vec is not None:
            dense = await dense_search(
                db, query_vec, limit=candidates_per_retriever,
                condition_filter=condition_filter,
            )
        else:
            dense = []

        fused = fuse_rrf(bm25, dense)
        top = fused[:k]
        if not top:
            return []

        rrf_by_id = dict(top)
        chunk_ids_in_order = [cid for cid, _ in top]

        return await _hydrate_chunks(db, chunk_ids_in_order, rrf_by_id)
