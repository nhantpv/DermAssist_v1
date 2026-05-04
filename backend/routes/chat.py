"""Chat routes — TIP-010 wire-up.

POST /chat/message:
  1. Verify encounter ownership.
  2. Persist the user turn into chat_messages.
  3. Determine condition_filter from the encounter's primary_condition_key.
  4. Retrieve top-3 RAG chunks scoped to that condition.
  5. Call chat_followup() with prior conversation history + new message.
  6. Persist the assistant turn (content + extracted citations).
  7. Audit-log the chat_turn event (NEW event_type — see TIP-010 report).
  8. Return an HTML fragment containing both messages for HTMX to swap.
"""
from __future__ import annotations

import json
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse
from markupsafe import escape
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import CurrentUser, get_current_user
from backend.db import get_db
from backend.orchestrator import _audit
from backend.retrieval import retrieve
from backend.vlm import DiagnoseError, PriorTurn, chat_followup

router = APIRouter(tags=["chat"])
logger = logging.getLogger(__name__)


@router.post("/chat/message", response_class=HTMLResponse)
async def chat_message(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    encounter_id: UUID = Form(...),
    message: str = Form(..., min_length=1, max_length=2000),
):
    if not message.strip():
        raise HTTPException(status_code=400, detail="Tin nhắn trống.")

    # 1) Ownership + diagnosis lookup
    enc_row = (
        await db.execute(
            text(
                "SELECT id::text AS id, result_json "
                "  FROM encounters "
                " WHERE id = CAST(:eid AS uuid) "
                "   AND doctor_id = CAST(:uid AS uuid) "
                "   AND deleted_at IS NULL"
            ),
            {"eid": str(encounter_id), "uid": user["id"]},
        )
    ).mappings().first()
    if enc_row is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy encounter.")

    diagnosis = enc_row.get("result_json") or {}
    primary_key = diagnosis.get("primary_condition_key")
    condition_filter = (
        [primary_key] if primary_key and primary_key != "other_ood" else None
    )

    # 2) Persist user turn
    await db.execute(
        text(
            "INSERT INTO chat_messages (encounter_id, role, content) "
            "VALUES (CAST(:eid AS uuid), 'user', :c)"
        ),
        {"eid": str(encounter_id), "c": message.strip()},
    )
    await db.commit()

    # 3) Load prior turns (oldest first) for the chat history context
    prior_rows = (
        await db.execute(
            text(
                "SELECT role, content FROM chat_messages "
                " WHERE encounter_id = CAST(:eid AS uuid) "
                "   AND role IN ('user', 'assistant') "
                " ORDER BY created_at ASC"
            ),
            {"eid": str(encounter_id)},
        )
    ).mappings().all()
    # Drop the row we just inserted so it isn't double-fed; chat_followup
    # adds the current_message itself.
    history = [PriorTurn(role=r["role"], content=r["content"]) for r in prior_rows[:-1]]

    # 4) RAG retrieve scoped to encounter's condition (if known)
    chunks = await retrieve(message, k=3, condition_filter=condition_filter)

    # 5) Call the model
    try:
        chat_resp = await chat_followup(
            prior_messages=history,
            current_message=message,
            rag_chunks=chunks,
        )
    except (DiagnoseError, Exception) as e:
        logger.exception("chat_followup failed for encounter %s: %s", encounter_id, e)
        # Persist a graceful assistant turn rather than 500-ing
        fallback_text = (
            "Hệ thống tạm thời không thể trả lời. Vui lòng thử lại trong giây lát."
        )
        await db.execute(
            text(
                "INSERT INTO chat_messages (encounter_id, role, content, citations) "
                "VALUES (CAST(:eid AS uuid), 'assistant', :c, CAST(:cit AS jsonb))"
            ),
            {
                "eid": str(encounter_id),
                "c": fallback_text,
                "cit": json.dumps([]),
            },
        )
        await db.commit()
        return HTMLResponse(_render_pair(message, fallback_text, []))

    # 6) Persist assistant turn
    await db.execute(
        text(
            "INSERT INTO chat_messages "
            "    (encounter_id, role, content, citations) "
            "VALUES (CAST(:eid AS uuid), 'assistant', :c, CAST(:cit AS jsonb))"
        ),
        {
            "eid": str(encounter_id),
            "c": chat_resp.content,
            "cit": json.dumps(chat_resp.citations),
        },
    )
    await db.commit()

    # 7) Audit
    await _audit(
        db,
        encounter_id=str(encounter_id),
        doctor_id=user["id"],
        event_type="chat_turn",
        rag_chunk_ids=chat_resp.chunks_used,
        latency_ms=chat_resp.latency_ms,
        details={
            "message_length": len(message),
            "chunks_used": len(chat_resp.chunks_used),
            "citations_returned": len(chat_resp.citations),
        },
    )

    # 8) Render fragment for HTMX
    return HTMLResponse(_render_pair(message, chat_resp.content, chat_resp.citations))


def _render_pair(user_msg: str, assistant_msg: str, citations: list[str]) -> str:
    """Build the two-bubble HTML fragment HTMX swaps into #chat-messages."""
    safe_user = escape(user_msg)
    safe_assistant = escape(assistant_msg)
    cite_html = ""
    if citations:
        cite_items = " ".join(
            f'<span class="text-xs text-slate-500 mr-1">[{escape(c[:8])}…]</span>'
            for c in citations
        )
        cite_html = f'<div class="mt-1">{cite_items}</div>'
    return (
        '<div class="flex justify-end">'
        '<div class="max-w-[85%] px-4 py-2 rounded-lg text-sm '
        'bg-blue-50 text-blue-900">'
        f"{safe_user}"
        "</div></div>"
        '<div class="flex">'
        '<div class="max-w-[85%] px-4 py-2 rounded-lg text-sm '
        'bg-slate-100 text-slate-800">'
        f'<div class="whitespace-pre-wrap">{safe_assistant}</div>'
        f"{cite_html}"
        "</div></div>"
    )
