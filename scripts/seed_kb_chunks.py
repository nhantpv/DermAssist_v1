"""Load chunks.json into Postgres kb_chunks table.

Run after migrations are applied (TIP-004).

Usage:
    DATABASE_URL=postgresql+asyncpg://dermassist:dermassist_dev@localhost:5432/dermassist \
        python scripts/seed_kb_chunks.py

Idempotent: deletes any existing rows for doc_id='qd-4416-byt-2023'
before inserting, so re-running replaces rather than duplicates.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import asyncpg
from pgvector.asyncpg import register_vector

# Allow either the FastAPI/asyncpg-style URL (postgresql+asyncpg://) or the
# bare libpq URL (postgresql://) — strip the +asyncpg driver tag if present.
DB_URL = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql://"
)
CHUNKS_PATH = Path("data/chunks.json")
DOC_ID = "qd-4416-byt-2023"


async def main() -> None:
    if not DB_URL:
        raise SystemExit("❌ DATABASE_URL env var not set.")
    if not CHUNKS_PATH.exists():
        raise SystemExit(
            f"❌ {CHUNKS_PATH} not found. Run notebooks/02_ocr_pipeline.ipynb "
            "on Colab first to produce it."
        )

    chunks = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))
    if not chunks:
        raise SystemExit(f"❌ {CHUNKS_PATH} is empty.")

    conn = await asyncpg.connect(DB_URL)
    try:
        await register_vector(conn)

        # Idempotency: clear existing rows for this doc_id
        deleted = await conn.execute(
            "DELETE FROM kb_chunks WHERE doc_id = $1", DOC_ID
        )
        print(f"  cleared previous rows: {deleted}")

        inserted = 0
        for c in chunks:
            await conn.execute(
                """
                INSERT INTO kb_chunks
                    (doc_id, source_url, section_title, chunk_index,
                     text, condition_tags, token_count, embedding)
                VALUES ($1, $2, $3, $4, $5, $6::text[], $7, $8::vector)
                """,
                c["doc_id"],
                c["source_url"],
                c["section_title"],
                c["chunk_index"],
                c["text"],
                c["condition_tags"],
                c["token_count"],
                c["embedding"],
            )
            inserted += 1

        # tsvector is auto-populated by the migration trigger.
        verify = await conn.fetchval(
            "SELECT count(*) FROM kb_chunks WHERE doc_id = $1", DOC_ID
        )
        print(f"✓ Inserted {inserted} chunks for doc_id={DOC_ID}")
        print(f"  DB confirms: {verify} rows")
        if verify != inserted:
            raise SystemExit(
                f"❌ Insert/count mismatch: inserted={inserted} db={verify}"
            )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
