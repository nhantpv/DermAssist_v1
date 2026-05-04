"""BM25 retrieval via Postgres tsvector.

The kb_chunks.text_tsv column is auto-populated by a trigger using
the 'simple' tokenizer (pg_catalog.simple). Vietnamese-aware enough
for closed beta; calibration is V2.

Returns ranked list of (chunk_id, score) where score is ts_rank.
Larger = more relevant (we'll convert to ranks in RRF).
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def bm25_search(
    db: AsyncSession,
    query: str,
    *,
    limit: int = 20,
    condition_filter: list[str] | None = None,
) -> list[tuple[str, float]]:
    """Top-N chunks by BM25 (ts_rank). Returns [(chunk_id, score)] desc."""
    if not query.strip():
        return []

    if condition_filter:
        sql = """
            SELECT id::text AS chunk_id,
                   ts_rank(text_tsv, plainto_tsquery('simple', :q)) AS score
              FROM kb_chunks
             WHERE text_tsv @@ plainto_tsquery('simple', :q)
               AND condition_tags && CAST(:tags AS text[])
             ORDER BY score DESC
             LIMIT :lim
        """
        params = {"q": query, "tags": condition_filter, "lim": limit}
    else:
        sql = """
            SELECT id::text AS chunk_id,
                   ts_rank(text_tsv, plainto_tsquery('simple', :q)) AS score
              FROM kb_chunks
             WHERE text_tsv @@ plainto_tsquery('simple', :q)
             ORDER BY score DESC
             LIMIT :lim
        """
        params = {"q": query, "lim": limit}

    rows = (await db.execute(text(sql), params)).mappings().all()
    return [(r["chunk_id"], float(r["score"])) for r in rows]
