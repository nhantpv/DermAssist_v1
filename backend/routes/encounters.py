"""Encounter routes: list, new form, create, detail, finalize, image serve.

NOTE on schema: the TIP-006 spec assumed column names that differ from
TIP-004's actual `encounters` schema. Mapping used below:
    TIP-006 expected           Actual (migration 001 + 005)
    -----------------------    ----------------------------------
    diagnosis_json             result_json
    clinical_note_raw          clinical_note      (post-redaction column)
    clinical_note_redacted     clinical_note      (same — only one column exists)
    pii_redaction_count        pii_redacted_count
    patient_context_json       patient_context    (added in migration 005)
    doctor_finalized           derived as (doctor_completed_at IS NOT NULL)
    doctor_diagnosis           doctor_final_dx
    doctor_tier                doctor_final_tier
    doctor_finalized_at        doctor_completed_at

TIP-007-V1: image preflight (blur + dimension) and Vietnamese-aware PII
redaction now run inline in /encounters/create. Failed preflight
re-renders the form with a flash error and creates no row. Successful
preflight redacts the clinical note before persisting.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import CurrentUser, get_current_user
from backend.db import get_db
from backend.preflight import check_image
from backend.text.pii import redact_pii

router = APIRouter(tags=["encounters"])

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_UPLOADS_DIR = _PROJECT_ROOT / "data" / "uploads"
_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
_EXT_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
_VALID_TIERS = {"home_care", "outpatient_72h", "outpatient_24h", "emergency"}


def _save_image(image_bytes: bytes, content_type: str) -> tuple[str, str]:
    """Write image to data/uploads/<sha256>.<ext> if absent. Returns
    (sha256_hex, relative_filename_only)."""
    sha = hashlib.sha256(image_bytes).hexdigest()
    ext = _EXT_BY_CONTENT_TYPE[content_type]
    filename = f"{sha}{ext}"
    path = _UPLOADS_DIR / filename
    if not path.exists():
        path.write_bytes(image_bytes)
    return sha, filename


def _row_to_record(row: dict) -> dict:
    """Normalize a DB row into the dict shape templates expect."""
    record = dict(row)
    record["id_short"] = record["id"][:8] if record.get("id") else ""
    record["doctor_finalized"] = record.get("doctor_completed_at") is not None
    record["doctor_diagnosis"] = record.get("doctor_final_dx")
    record["doctor_tier"] = record.get("doctor_final_tier")
    record["image_url"] = (
        f"/uploads/{Path(record['image_path']).name}"
        if record.get("image_path")
        else None
    )
    record["diagnosis"] = record.get("result_json") or {}
    return record


@router.get("/encounters", response_class=HTMLResponse)
async def encounters_list(
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    rows = (
        await db.execute(
            text(
                "SELECT id::text AS id, created_at, primary_diagnosis, "
                "       management_tier, "
                "       (doctor_completed_at IS NOT NULL) AS doctor_finalized "
                "  FROM encounters "
                " WHERE doctor_id = CAST(:uid AS uuid) AND deleted_at IS NULL "
                " ORDER BY created_at DESC"
            ),
            {"uid": user["id"]},
        )
    ).mappings().all()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "encounters_list.html",
        {
            "records": [dict(r) for r in rows],
            "current_user_username": user["username"],
        },
    )


@router.get("/encounters/new", response_class=HTMLResponse)
async def encounter_new_form(
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    rows = (
        await db.execute(
            text(
                "SELECT id::text AS id, created_at, primary_diagnosis, "
                "       management_tier "
                "  FROM encounters "
                " WHERE doctor_id = CAST(:uid AS uuid) AND deleted_at IS NULL "
                " ORDER BY created_at DESC LIMIT 5"
            ),
            {"uid": user["id"]},
        )
    ).mappings().all()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "encounter_new.html",
        {
            "recent_encounters": [dict(r) for r in rows],
            "flash": None,
            "current_user_username": user["username"],
        },
    )


@router.post("/encounters/create")
async def encounter_create_stub(
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    image: UploadFile = File(...),
    clinical_note: str = Form(""),
    age_years: int | None = Form(None),
    sex: str | None = Form(None),
    symptom_duration_days: int | None = Form(None),
    prior_treatments: str | None = Form(None),
    relevant_history: str | None = Form(None),
):
    """Saves image + form data, runs preflight + PII redaction, persists
    an encounter row with result_json={'_stub': true}. The downstream
    pipeline (RAG → VLM → orchestrator) wires in TIP-008–010 and
    TIP-011 will replace the stub result_json with real diagnosis output.
    """
    image_bytes = await image.read()

    if len(image_bytes) == 0:
        raise HTTPException(status_code=400, detail="File ảnh trống.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Ảnh quá lớn (tối đa 8 MB).")
    if image.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Định dạng ảnh không hỗ trợ.")

    # === TIP-007: preflight ===
    preflight = check_image(image_bytes)

    if not preflight.passed:
        # Don't create an encounter row, don't save the image.
        # Re-render the form with a flash error.
        recent_rows = (
            await db.execute(
                text(
                    "SELECT id::text AS id, created_at, "
                    "       primary_diagnosis, management_tier "
                    "  FROM encounters "
                    " WHERE doctor_id = CAST(:uid AS uuid) AND deleted_at IS NULL "
                    " ORDER BY created_at DESC LIMIT 5"
                ),
                {"uid": user["id"]},
            )
        ).mappings().all()
        templates = request.app.state.templates
        return templates.TemplateResponse(
            request,
            "encounter_new.html",
            {
                "recent_encounters": [dict(r) for r in recent_rows],
                "flash": {"kind": "error", "message": preflight.failure_reason},
                "current_user_username": user["username"],
            },
            status_code=400,
        )

    image_sha, image_filename = _save_image(image_bytes, image.content_type)
    image_path = f"data/uploads/{image_filename}"

    # === TIP-007: PII redaction on clinical_note ===
    redacted = redact_pii(clinical_note or "")

    patient_context = {
        "age_years": age_years,
        "sex": sex if sex else None,
        "symptom_duration_days": symptom_duration_days,
        "prior_treatments": prior_treatments,
        "relevant_history": relevant_history,
    }

    result = await db.execute(
        text(
            "INSERT INTO encounters "
            "    (doctor_id, image_path, image_sha256, image_size_bytes, "
            "     clinical_note, pii_redacted_count, "
            "     preflight_passed, preflight_blur_score, "
            "     preflight_brightness, preflight_failure, "
            "     patient_context, result_json, created_at) "
            "VALUES (CAST(:uid AS uuid), :path, :sha, :sz, "
            "        :note, :pii_n, "
            "        TRUE, :blur, :bright, NULL, "
            "        CAST(:pc AS jsonb), CAST(:dj AS jsonb), NOW()) "
            "RETURNING id::text AS id"
        ),
        {
            "uid": user["id"],
            "path": image_path,
            "sha": image_sha,
            "sz": len(image_bytes),
            "note": redacted.text,
            "pii_n": redacted.count,
            "blur": preflight.blur_score,
            "bright": preflight.brightness,
            "pc": json.dumps(patient_context),
            "dj": json.dumps({"_stub": True}),
        },
    )
    new_id = result.mappings().first()["id"]
    await db.commit()
    return RedirectResponse(url=f"/encounters/{new_id}", status_code=303)


@router.get("/encounters/{encounter_id}", response_class=HTMLResponse)
async def encounter_detail(
    request: Request,
    encounter_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    row = (
        await db.execute(
            text(
                "SELECT id::text AS id, created_at, image_sha256, image_path, "
                "       clinical_note, pii_redacted_count, "
                "       preflight_passed, preflight_failure, "
                "       result_json, ood_flag, primary_diagnosis, "
                "       confidence, management_tier, "
                "       doctor_final_dx, doctor_final_tier, doctor_notes, "
                "       doctor_completed_at "
                "  FROM encounters "
                " WHERE id = CAST(:eid AS uuid) "
                "   AND doctor_id = CAST(:uid AS uuid) "
                "   AND deleted_at IS NULL"
            ),
            {"eid": str(encounter_id), "uid": user["id"]},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy encounter.")

    chat_rows = (
        await db.execute(
            text(
                "SELECT role, content, citations FROM chat_messages "
                "WHERE encounter_id = CAST(:eid AS uuid) "
                "ORDER BY created_at ASC"
            ),
            {"eid": str(encounter_id)},
        )
    ).mappings().all()

    record = _row_to_record(dict(row))
    record["chat_messages"] = [dict(m) for m in chat_rows]

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "encounter_result.html",
        {"record": record, "current_user_username": user["username"]},
    )


@router.post("/encounters/{encounter_id}/finalize")
async def encounter_finalize(
    encounter_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    doctor_diagnosis: str = Form(...),
    doctor_tier: str = Form(...),
    doctor_notes: str = Form(""),
):
    if doctor_tier not in _VALID_TIERS:
        raise HTTPException(status_code=400, detail="Tier không hợp lệ.")

    result = await db.execute(
        text(
            "UPDATE encounters "
            "   SET doctor_final_dx = :dx, "
            "       doctor_final_tier = :tier, "
            "       doctor_notes = :notes, "
            "       doctor_completed_at = NOW() "
            " WHERE id = CAST(:eid AS uuid) "
            "   AND doctor_id = CAST(:uid AS uuid) "
            "   AND deleted_at IS NULL"
        ),
        {
            "eid": str(encounter_id),
            "uid": user["id"],
            "dx": doctor_diagnosis,
            "tier": doctor_tier,
            "notes": doctor_notes or None,
        },
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Không tìm thấy encounter.")
    await db.commit()
    return RedirectResponse(url=f"/encounters/{encounter_id}", status_code=303)


@router.get("/uploads/{filename}")
async def serve_upload(
    filename: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
):
    """Auth-gated image serve."""
    if "/" in filename or ".." in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Tên file không hợp lệ.")
    path = _UPLOADS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh.")
    return FileResponse(path)
