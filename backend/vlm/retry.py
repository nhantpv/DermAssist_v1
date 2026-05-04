"""Single-retry wrapper around the VLM call.

Retries only on JSON parse failure or Pydantic validation errors —
i.e. cases where the model produced output we couldn't validate.
HTTP errors (network, 4xx, 5xx) bubble unchanged so callers see the
real failure mode.
"""
from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from backend.retrieval import Chunk
from backend.schemas import DiagnosisOutput, PatientContext
from backend.vlm.client import DiagnoseError, _call_once

logger = logging.getLogger(__name__)


async def diagnose(
    *,
    image_bytes: bytes,
    clinical_note_redacted: str,
    patient_context: PatientContext | dict | None,
    rag_chunks: list[Chunk],
) -> DiagnosisOutput:
    """Public entry point. Calls VLM, validates output. One retry on
    parse/validation failure. Raises DiagnoseError if both attempts
    fail to validate."""
    kwargs = {
        "image_bytes": image_bytes,
        "clinical_note_redacted": clinical_note_redacted,
        "patient_context": patient_context,
        "rag_chunks": rag_chunks,
    }
    try:
        return await _call_once(**kwargs)
    except (json.JSONDecodeError, ValidationError) as e:
        logger.warning(
            "VLM first attempt failed validation (%s: %s). Retrying once.",
            type(e).__name__, e,
        )

    try:
        return await _call_once(**kwargs)
    except (json.JSONDecodeError, ValidationError) as e:
        logger.error(
            "VLM retry also failed validation (%s: %s). Giving up.",
            type(e).__name__, e,
        )
        raise DiagnoseError(
            "Hệ thống không thể tạo chẩn đoán hợp lệ. Vui lòng thử lại."
        ) from e
