"""Map kb_chunks doc_id → friendly Vietnamese display name + URL.

V1 has one corpus (QĐ-4416). V2 expands; this mapping grows accordingly.
Shared by orchestrator and chat for enriching citation chunk_ids into
display-friendly dicts before they reach the template.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DOC_ID_TO_NAME: dict[str, str] = {
    "qd-4416-byt-2023": "Quyết định 4416/QĐ-BYT 2023",
}

DOC_ID_TO_URL: dict[str, str | None] = {
    "qd-4416-byt-2023": None,
}


def friendly_name(doc_id: str) -> str:
    """Return the Vietnamese display name for a doc_id, or the doc_id
    itself if not in the map (fallback)."""
    return DOC_ID_TO_NAME.get(doc_id, doc_id)


def doc_url(doc_id: str) -> str | None:
    """Return the public URL for the document if known."""
    return DOC_ID_TO_URL.get(doc_id)


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


async def enrich_citations(
    db: AsyncSession, chunk_ids: list[str]
) -> list[dict]:
    """Look up chunks by id and return display-friendly citation dicts.

    Each dict has: chunk_id, doc_name, section, url. Order preserves the
    input list. Non-UUID or unknown ids fall back to the chunk_id string
    as doc_name (defensive — kb_chunks.id is uuid).
    """
    if not chunk_ids:
        return []
    valid_ids = [c for c in chunk_ids if _is_uuid(c)]
    by_id: dict[str, dict] = {}
    if valid_ids:
        rows = (
            await db.execute(
                text(
                    "SELECT id::text AS chunk_id, doc_id, section_title "
                    "  FROM kb_chunks "
                    " WHERE id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": valid_ids},
            )
        ).mappings().all()
        by_id = {r["chunk_id"]: dict(r) for r in rows}

    out: list[dict] = []
    for cid in chunk_ids:
        r = by_id.get(cid)
        if r is None:
            out.append(
                {"chunk_id": cid, "doc_name": cid, "section": "—", "url": None}
            )
            continue
        out.append(
            {
                "chunk_id": cid,
                "doc_name": friendly_name(r["doc_id"]),
                "section": r["section_title"] or "—",
                "url": doc_url(r["doc_id"]),
            }
        )
    return out
