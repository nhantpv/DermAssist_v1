"""Dense retrieval via pgvector cosine search.

Uses HNSW index (idx_kb_chunks_emb). Cosine distance via the <=>
operator: smaller = more similar. We negate to get a "score" where
larger = more similar, matching BM25 convention for RRF.
"""
from __future__ import annotations

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def dense_search(
    db: AsyncSession,
    query_vec: np.ndarray,
    *,
    limit: int = 20,
    condition_filter: list[str] | None = None,
) -> list[tuple[str, float]]:
    """Top-N chunks by cosine similarity to query_vec.

    Returns [(chunk_id, score)] where score = 1 - cosine_distance,
    in [0, 1] range with 1 = identical.
    """
    if query_vec.shape != (384,):
        raise ValueError(f"Expected 384-dim vector, got shape {query_vec.shape}")

    vec_literal = "[" + ",".join(f"{x:.6f}" for x in query_vec.tolist()) + "]"

    if condition_filter:
        sql = """
            SELECT id::text AS chunk_id,
                   1 - (embedding <=> CAST(:vec AS vector)) AS score
              FROM kb_chunks
             WHERE condition_tags && CAST(:tags AS text[])
             ORDER BY embedding <=> CAST(:vec AS vector)
             LIMIT :lim
        """
        params = {"vec": vec_literal, "tags": condition_filter, "lim": limit}
    else:
        sql = """
            SELECT id::text AS chunk_id,
                   1 - (embedding <=> CAST(:vec AS vector)) AS score
              FROM kb_chunks
             ORDER BY embedding <=> CAST(:vec AS vector)
             LIMIT :lim
        """
        params = {"vec": vec_literal, "lim": limit}

    rows = (await db.execute(text(sql), params)).mappings().all()
    return [(r["chunk_id"], float(r["score"])) for r in rows]
