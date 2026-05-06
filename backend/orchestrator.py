"""End-to-end pipeline: preflight → save → redact → retrieve → diagnose
→ persist + audit.

`run_encounter()` is the single entry-point for both the HTTP route
and integration tests. Each pipeline step writes one audit_log row;
the function returns an `OrchestratorResult` describing what happened.

Audit event_type vocabulary (Blueprint §7.1 lines 110-117) used here:
    encounter_create_start, preflight_pass, preflight_fail,
    pii_redacted, rag_retrieve, vlm_call, vlm_fallback_ood,
    output_validated, encounter_complete, chat_turn (NEW — see report).
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.citations import enrich_citations
from backend.preflight import check_image
from backend.retrieval import Chunk, retrieve
from backend.schemas import DiagnosisOutput, compute_final_ood
from backend.text.pii import redact_pii
from backend.vlm import DiagnoseError, diagnose

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_UPLOADS_DIR = _PROJECT_ROOT / "data" / "uploads"
_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

_EXT_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

_MODEL_VERSION = "gpt-4o-mini-v1"
_PROMPT_VERSION = "v1.0.0"

_FALLBACK_OUTPUT: dict[str, Any] = {
    "primary_diagnosis": "Không thể phân tích",
    "primary_condition_key": "other_ood",
    "confidence": 0.0,
    "differential": [],
    "key_features_observed": [],
    "management_tier": "outpatient_72h",
    "red_flags": ["Khuyến nghị hội chẩn chuyên khoa da liễu để đánh giá thêm"],
    "ood_flag": True,
    "image_quality_notes": "Lỗi hệ thống — không thể tạo chẩn đoán. Vui lòng thử lại.",
    "citations": [],
}


@dataclass
class OrchestratorResult:
    encounter_id: str | None
    diagnosis: DiagnosisOutput | None
    preflight_passed: bool
    preflight_failure: str | None
    pii_redacted_count: int
    rag_chunk_ids: list[str] = field(default_factory=list)
    final_ood: bool = False
    latency_ms: int = 0


# === Helpers ===

def _save_image(image_bytes: bytes, content_type: str) -> tuple[str, str, bool]:
    """Write image to data/uploads/<sha256>.<ext> if absent. Returns
    (sha256_hex, relative_filename_only, dedup_hit) — dedup_hit is True
    when an identical file already existed and the write was skipped."""
    sha = hashlib.sha256(image_bytes).hexdigest()
    ext = _EXT_BY_CONTENT_TYPE[content_type]
    filename = f"{sha}{ext}"
    path = _UPLOADS_DIR / filename
    dedup_hit = path.exists()
    if not dedup_hit:
        path.write_bytes(image_bytes)
    return sha, filename, dedup_hit


async def _audit(
    db: AsyncSession,
    *,
    encounter_id: str | None,
    doctor_id: str,
    event_type: str,
    details: dict | None = None,
    rag_chunk_ids: list[str] | None = None,
    latency_ms: int | None = None,
    image_sha256: str | None = None,
    output_sha256: str | None = None,
) -> None:
    await db.execute(
        text(
            "INSERT INTO audit_log "
            "  (encounter_id, doctor_id, event_type, "
            "   model_version, prompt_version, "
            "   rag_chunk_ids, image_sha256, output_sha256, "
            "   latency_ms, details) "
            "VALUES "
            "  (CAST(:eid AS uuid), CAST(:uid AS uuid), :evt, "
            "   :mv, :pv, "
            "   CAST(:rcids AS text[]), :img_sha, :out_sha, "
            "   :lat, CAST(:det AS jsonb))"
        ),
        {
            "eid": encounter_id,
            "uid": doctor_id,
            "evt": event_type,
            "mv": _MODEL_VERSION,
            "pv": _PROMPT_VERSION,
            "rcids": rag_chunk_ids,
            "img_sha": image_sha256,
            "out_sha": output_sha256,
            "lat": latency_ms,
            "det": json.dumps(details) if details else None,
        },
    )
    await db.commit()


def _build_rag_query(clinical_note: str, patient_context: dict | None) -> str:
    """Concat clinical note + relevant patient context, capped at 500 chars."""
    parts = [clinical_note.strip()] if clinical_note else []
    if patient_context:
        for key in ("relevant_history", "prior_treatments"):
            v = patient_context.get(key)
            if v:
                parts.append(str(v).strip())
    out = " ".join(p for p in parts if p)
    return out[:500]


def _sanitize_diagnosis(out: DiagnosisOutput) -> tuple[DiagnosisOutput, bool]:
    """Apply TIP-009 cleanup rules. Returns (sanitized, fallback_echo)."""
    data = out.model_dump()

    # Drop differential entries with condition_key='other_ood' when ood_flag=False
    if not data["ood_flag"] and data.get("differential"):
        data["differential"] = [
            d for d in data["differential"]
            if d.get("condition_key") != "other_ood"
        ]

    # Clear image_quality_notes when ood_flag=False
    if not data["ood_flag"]:
        data["image_quality_notes"] = ""

    fallback_echo = (
        data["primary_diagnosis"] == "Không thể phân tích"
        and data["confidence"] == 0.0
        and not data["differential"]
    )

    return DiagnosisOutput.model_validate(data), fallback_echo


# === Public API ===

async def run_encounter(
    *,
    db: AsyncSession,
    doctor_id: str,
    image_bytes: bytes,
    image_content_type: str,
    clinical_note: str,
    patient_context: dict,
) -> OrchestratorResult:
    """Run the full pipeline. Persists encounter row + audit_log entries.
    Raises only for unrecoverable errors (DB down, etc.). VLM/preflight
    failures are returned in the result, not raised."""
    t_start = time.monotonic()
    image_sha = hashlib.sha256(image_bytes).hexdigest()

    # 1) Pre-encounter audit
    await _audit(
        db,
        encounter_id=None,
        doctor_id=doctor_id,
        event_type="encounter_create_start",
        image_sha256=image_sha,
        details={
            "image_size_bytes": len(image_bytes),
            "content_type": image_content_type,
        },
    )

    # 2) Preflight
    preflight = check_image(image_bytes)
    if not preflight.passed:
        await _audit(
            db,
            encounter_id=None,
            doctor_id=doctor_id,
            event_type="preflight_fail",
            image_sha256=image_sha,
            details={
                "failure_reason": preflight.failure_reason,
                "blur_score": preflight.blur_score,
                "brightness": preflight.brightness,
            },
        )
        return OrchestratorResult(
            encounter_id=None,
            diagnosis=None,
            preflight_passed=False,
            preflight_failure=preflight.failure_reason,
            pii_redacted_count=0,
            latency_ms=int((time.monotonic() - t_start) * 1000),
        )

    await _audit(
        db,
        encounter_id=None,
        doctor_id=doctor_id,
        event_type="preflight_pass",
        image_sha256=image_sha,
        details={
            "blur_score": preflight.blur_score,
            "brightness": preflight.brightness,
        },
    )

    # 3) Save image (dedup by sha256)
    _, image_filename, dedup_hit = _save_image(image_bytes, image_content_type)
    image_path = f"data/uploads/{image_filename}"
    if dedup_hit:
        await _audit(
            db,
            encounter_id=None,
            doctor_id=doctor_id,
            event_type="image_dedup_hit",
            image_sha256=image_sha,
            details={"image_sha256": image_sha, "matched_existing": True},
        )

    # 4) Redact PII
    redacted = redact_pii(clinical_note or "")
    if redacted.count > 0:
        await _audit(
            db,
            encounter_id=None,
            doctor_id=doctor_id,
            event_type="pii_redacted",
            image_sha256=image_sha,
            details={"count": redacted.count},
        )

    # 5+6) Build RAG query and retrieve
    rag_query = _build_rag_query(redacted.text, patient_context)
    rag_chunks: list[Chunk] = []
    if rag_query:
        rag_chunks = await retrieve(rag_query, k=5)

    rag_chunk_ids = [c.chunk_id for c in rag_chunks]
    await _audit(
        db,
        encounter_id=None,
        doctor_id=doctor_id,
        event_type="rag_retrieve",
        image_sha256=image_sha,
        rag_chunk_ids=rag_chunk_ids,
        details={
            "query_length": len(rag_query),
            "chunks_returned": len(rag_chunks),
        },
    )

    # 7) Insert encounter row (initial state, result_json NULL)
    insert_row = (
        await db.execute(
            text(
                "INSERT INTO encounters "
                "  (doctor_id, image_path, image_sha256, image_size_bytes, "
                "   clinical_note, pii_redacted_count, "
                "   preflight_passed, preflight_blur_score, "
                "   preflight_brightness, preflight_failure, "
                "   patient_context, result_json, created_at) "
                "VALUES (CAST(:uid AS uuid), :path, :sha, :sz, "
                "        :note, :pii_n, "
                "        TRUE, :blur, :bright, NULL, "
                "        CAST(:pc AS jsonb), NULL, NOW()) "
                "RETURNING id::text AS id"
            ),
            {
                "uid": doctor_id,
                "path": image_path,
                "sha": image_sha,
                "sz": len(image_bytes),
                "note": redacted.text,
                "pii_n": redacted.count,
                "blur": preflight.blur_score,
                "bright": preflight.brightness,
                "pc": json.dumps(patient_context),
            },
        )
    ).mappings().first()
    encounter_id: str = insert_row["id"]
    await db.commit()

    # Backfill encounter_id on pre-insert audit rows so the full
    # pipeline trace is queryable by encounter_id.
    await db.execute(
        text(
            "UPDATE audit_log "
            "   SET encounter_id = CAST(:eid AS uuid) "
            " WHERE encounter_id IS NULL "
            "   AND doctor_id = CAST(:uid AS uuid) "
            "   AND image_sha256 = :sha "
            "   AND ts >= NOW() - INTERVAL '5 minutes'"
        ),
        {"eid": encounter_id, "uid": doctor_id, "sha": image_sha},
    )
    await db.commit()

    # 8) VLM call
    vlm_t0 = time.monotonic()
    diagnosis: DiagnosisOutput | None = None
    vlm_error: str | None = None
    try:
        diagnosis = await diagnose(
            image_bytes=image_bytes,
            clinical_note_redacted=redacted.text,
            patient_context=patient_context,
            rag_chunks=rag_chunks,
        )
    except DiagnoseError as e:
        vlm_error = str(e)
        logger.warning("VLM diagnose failed for encounter %s: %s", encounter_id, e)

    vlm_latency_ms = int((time.monotonic() - vlm_t0) * 1000)

    if diagnosis is None:
        # 8a) VLM failure → use fallback
        await _audit(
            db,
            encounter_id=encounter_id,
            doctor_id=doctor_id,
            event_type="vlm_call",
            image_sha256=image_sha,
            rag_chunk_ids=rag_chunk_ids,
            latency_ms=vlm_latency_ms,
            details={"error": vlm_error},
        )
        diagnosis = DiagnosisOutput.model_validate(_FALLBACK_OUTPUT)
        result_json = diagnosis.model_dump()
        result_json["enriched_citations"] = []
    else:
        # 9) Sanitize success
        diagnosis, fallback_echo = _sanitize_diagnosis(diagnosis)
        result_json = diagnosis.model_dump()
        result_json["enriched_citations"] = await enrich_citations(
            db, list(diagnosis.citations)
        )

        out_sha = hashlib.sha256(
            json.dumps(result_json, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        await _audit(
            db,
            encounter_id=encounter_id,
            doctor_id=doctor_id,
            event_type="vlm_call",
            image_sha256=image_sha,
            output_sha256=out_sha,
            rag_chunk_ids=rag_chunk_ids,
            latency_ms=vlm_latency_ms,
            details={"success": True},
        )

        if fallback_echo:
            await _audit(
                db,
                encounter_id=encounter_id,
                doctor_id=doctor_id,
                event_type="vlm_fallback_ood",
                image_sha256=image_sha,
                details={"fallback_detected": True},
            )

    # 10) Composite OOD
    final_ood = compute_final_ood(diagnosis)

    # 11) UPDATE encounter row with sanitized result
    await db.execute(
        text(
            "UPDATE encounters "
            "   SET result_json = CAST(:rj AS jsonb), "
            "       ood_flag = :ood, "
            "       primary_diagnosis = :pd, "
            "       confidence = :conf, "
            "       management_tier = :tier "
            " WHERE id = CAST(:eid AS uuid)"
        ),
        {
            "rj": json.dumps(result_json, ensure_ascii=False),
            "ood": final_ood,
            "pd": diagnosis.primary_diagnosis,
            "conf": diagnosis.confidence,
            "tier": diagnosis.management_tier,
            "eid": encounter_id,
        },
    )
    await db.commit()

    await _audit(
        db,
        encounter_id=encounter_id,
        doctor_id=doctor_id,
        event_type="output_validated",
        image_sha256=image_sha,
        details={"final_ood": final_ood},
    )

    # 12) Final audit
    total_ms = int((time.monotonic() - t_start) * 1000)
    await _audit(
        db,
        encounter_id=encounter_id,
        doctor_id=doctor_id,
        event_type="encounter_complete",
        image_sha256=image_sha,
        latency_ms=total_ms,
        details={"latency_ms": total_ms},
    )

    return OrchestratorResult(
        encounter_id=encounter_id,
        diagnosis=diagnosis,
        preflight_passed=True,
        preflight_failure=None,
        pii_redacted_count=redacted.count,
        rag_chunk_ids=rag_chunk_ids,
        final_ood=final_ood,
        latency_ms=total_ms,
    )
