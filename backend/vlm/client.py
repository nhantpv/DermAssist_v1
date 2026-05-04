"""HTTP client for VLM chat-completions calls.

Single-call entry point: _call_once(...). Wrapped by retry.diagnose()
for the public API.

This module deliberately uses raw httpx rather than the openai SDK so
that swapping providers (Anthropic, vLLM) in V2 is a matter of swapping
this file's body, not a different transport layer.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx
from pydantic import ValidationError

from backend.config import get_settings
from backend.retrieval import Chunk
from backend.schemas import DiagnosisOutput, PatientContext
from backend.vlm.prompt import SYSTEM_PROMPT, build_user_content

logger = logging.getLogger(__name__)


class DiagnoseError(Exception):
    """Raised when the VLM call fails after retry, or the provider is
    not implemented. Carries a Vietnamese message safe to surface to
    the doctor (routes layer renders this directly)."""


_TIMEOUT = httpx.Timeout(60.0)


async def _call_once(
    *,
    image_bytes: bytes,
    clinical_note_redacted: str,
    patient_context: PatientContext | dict | None,
    rag_chunks: list[Chunk],
) -> DiagnosisOutput:
    """One end-to-end VLM call. Raises ValidationError /
    json.JSONDecodeError on parse failure; httpx errors bubble.

    Caller (retry.py) decides whether to retry on parse failure.
    """
    settings = get_settings()

    if settings.vlm_provider != "openai":
        raise NotImplementedError(
            f"VLM provider '{settings.vlm_provider}' not implemented. "
            "Only 'openai' is supported in V1."
        )
    if not settings.vlm_api_key:
        raise DiagnoseError("Lỗi cấu hình: chưa cấu hình VLM_API_KEY.")

    image_b64 = base64.b64encode(image_bytes).decode("ascii")

    user_content = build_user_content(
        image_b64=image_b64,
        clinical_note=clinical_note_redacted,
        patient_context=patient_context,
        rag_chunks=rag_chunks,
    )

    body: dict[str, Any] = {
        "model": settings.vlm_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
        "max_tokens": 1500,
    }

    headers = {
        "Authorization": f"Bearer {settings.vlm_api_key}",
        "Content-Type": "application/json",
    }
    url = f"{settings.vlm_endpoint.rstrip('/')}/chat/completions"

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        payload = resp.json()

    raw = payload["choices"][0]["message"]["content"] or "{}"
    parsed = json.loads(raw)
    return DiagnosisOutput.model_validate(parsed)
