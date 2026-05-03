"""Chat routes — STUB for TIP-006. Real wiring in TIP-010.

The encounter result page uses HTMX with `hx-swap="beforeend"` against
`#chat-messages`, so this endpoint returns an HTML fragment containing
the user's echo bubble plus a placeholder assistant reply.
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse
from markupsafe import escape

from backend.auth import CurrentUser, get_current_user

router = APIRouter(tags=["chat"])

_STUB_REPLY = (
    "Chatbot chưa được kích hoạt — endpoint sẽ được wire trong TIP-010 "
    "(RAG + VLM follow-up Q&A)."
)


@router.post("/chat/message", response_class=HTMLResponse)
async def chat_message_stub(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    encounter_id: UUID = Form(...),
    message: str = Form(..., min_length=1, max_length=2000),
):
    """STUB: echoes the user message and returns a fixed assistant
    placeholder. Does NOT persist to chat_messages — TIP-010 owns that.
    """
    if not message.strip():
        raise HTTPException(status_code=400, detail="Tin nhắn trống.")

    safe_msg = escape(message)
    safe_reply = escape(_STUB_REPLY)

    fragment = (
        '<div class="flex justify-end">'
        '<div class="max-w-[85%] px-4 py-2 rounded-lg text-sm '
        'bg-blue-50 text-blue-900">'
        f"{safe_msg}"
        "</div></div>"
        '<div class="flex">'
        '<div class="max-w-[85%] px-4 py-2 rounded-lg text-sm '
        'bg-slate-100 text-slate-800 italic">'
        f"{safe_reply}"
        "</div></div>"
    )
    return HTMLResponse(fragment)
