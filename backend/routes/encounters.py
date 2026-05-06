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
from backend.citations import enrich_citations
from backend.db import get_db
from backend.orchestrator import run_encounter

router = APIRouter(tags=["encounters"])

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_UPLOADS_DIR = _PROJECT_ROOT / "data" / "uploads"
_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
_VALID_TIERS = {"home_care", "outpatient_72h", "outpatient_24h", "emergency"}


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
                " ORDER BY created_at DESC "
                " LIMIT 50"
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
async def encounter_create(
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
    """Run the full TIP-010 pipeline: preflight → save → redact →
    retrieve → diagnose → persist. On preflight fail, re-renders the
    form with a flash. On success or VLM-fallback, redirects to the
    result page."""
    image_bytes = await image.read()

    if len(image_bytes) == 0:
        raise HTTPException(status_code=400, detail="File ảnh trống.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Ảnh quá lớn (tối đa 8 MB).")
    if image.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Định dạng ảnh không hỗ trợ.")

    patient_context = {
        "age_years": age_years,
        "sex": sex if sex else None,
        "symptom_duration_days": symptom_duration_days,
        "prior_treatments": prior_treatments,
        "relevant_history": relevant_history,
    }

    result = await run_encounter(
        db=db,
        doctor_id=user["id"],
        image_bytes=image_bytes,
        image_content_type=image.content_type,
        clinical_note=clinical_note,
        patient_context=patient_context,
    )

    if not result.preflight_passed:
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
                "flash": {"kind": "error", "message": result.preflight_failure},
                "current_user_username": user["username"],
            },
            status_code=400,
        )

    return RedirectResponse(
        url=f"/encounters/{result.encounter_id}", status_code=303
    )


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
    chat_messages = [dict(m) for m in chat_rows]

    # Enrich each assistant message's citations once so the template
    # can render friendly doc names instead of bare UUIDs.
    all_ids: list[str] = []
    for m in chat_messages:
        for cid in (m.get("citations") or []):
            if cid not in all_ids:
                all_ids.append(cid)
    enriched_all = await enrich_citations(db, all_ids)
    by_id = {e["chunk_id"]: e for e in enriched_all}
    for m in chat_messages:
        m["enriched_citations"] = [
            by_id[cid] for cid in (m.get("citations") or []) if cid in by_id
        ]
    record["chat_messages"] = chat_messages

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


@router.post("/encounters/{encounter_id}/delete")
async def encounter_delete(
    encounter_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Soft-delete an encounter belonging to the current doctor.

    Sets deleted_at = NOW(); does NOT remove the image file or audit
    rows. Returns 404 (not 403) for missing/already-deleted/cross-
    doctor rows so existence isn't probeable.
    """
    deleted = (
        await db.execute(
            text(
                "UPDATE encounters "
                "   SET deleted_at = NOW() "
                " WHERE id = CAST(:eid AS uuid) "
                "   AND doctor_id = CAST(:uid AS uuid) "
                "   AND deleted_at IS NULL "
                "RETURNING id::text AS id"
            ),
            {"eid": str(encounter_id), "uid": user["id"]},
        )
    ).first()
    if deleted is None:
        raise HTTPException(
            status_code=404,
            detail="Encounter không tồn tại hoặc đã bị xoá.",
        )
    await db.commit()

    await db.execute(
        text(
            "INSERT INTO audit_log "
            "  (encounter_id, doctor_id, event_type, details) "
            "VALUES (CAST(:eid AS uuid), CAST(:uid AS uuid), "
            "        'encounter_deleted', CAST(:det AS jsonb))"
        ),
        {
            "eid": str(encounter_id),
            "uid": user["id"],
            "det": '{"soft_delete": true}',
        },
    )
    await db.commit()

    return RedirectResponse(url="/encounters", status_code=303)


@router.get("/uploads/{filename}")
async def serve_upload(
    filename: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Auth-gated AND ownership-gated image serve.

    The filename is `<sha256>.<ext>`. Verify the requesting doctor owns
    at least one encounter with this image_sha256 before serving the
    bytes. Returns 404 (never 403) so existence isn't probeable across
    doctors.
    """
    if "/" in filename or ".." in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Tên file không hợp lệ.")
    sha = filename.split(".", 1)[0]
    if len(sha) != 64 or not all(c in "0123456789abcdef" for c in sha):
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh.")

    owns = (
        await db.execute(
            text(
                "SELECT 1 FROM encounters "
                " WHERE image_sha256 = :sha "
                "   AND doctor_id = CAST(:uid AS uuid) "
                "   AND deleted_at IS NULL "
                " LIMIT 1"
            ),
            {"sha": sha, "uid": user["id"]},
        )
    ).first()
    if owns is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh.")

    path = _UPLOADS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh.")
    return FileResponse(path)
