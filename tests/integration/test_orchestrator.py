"""Integration tests for backend/orchestrator.py.

Mocks `backend.orchestrator.diagnose` so we stay hermetic. The real
pipeline runs preflight + DB writes + RAG retrieval (against the
seeded DB), but never hits OpenAI."""
from __future__ import annotations

import asyncio
import io
import os

import numpy as np
import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import text


def _db_reachable() -> bool:
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return False

    async def _try() -> bool:
        eng = create_async_engine(db_url, pool_pre_ping=True)
        try:
            async with eng.begin() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
        finally:
            await eng.dispose()

    try:
        return asyncio.run(_try())
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_reachable(),
    reason="Postgres not reachable — skipping orchestrator tests.",
)


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine():
    yield
    from backend.db import engine
    await engine.dispose()


def _make_sharp_jpeg(size: int = 512) -> bytes:
    rng = np.random.default_rng(seed=99)
    base = rng.integers(0, 100, size=(size, size, 3), dtype=np.int32)
    arr = (base + 128 - 50).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _make_blurry_jpeg(size: int = 512) -> bytes:
    arr = np.full((size, size, 3), 128, dtype=np.uint8)
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


async def _demo_user_id() -> str:
    from backend.db import SessionLocal
    async with SessionLocal() as db:
        row = (
            await db.execute(text("SELECT id::text AS id FROM users WHERE username='demo'"))
        ).mappings().first()
    return row["id"]


async def _audit_count(encounter_id: str | None, doctor_id: str) -> int:
    from backend.db import SessionLocal
    async with SessionLocal() as db:
        if encounter_id:
            row = (
                await db.execute(
                    text(
                        "SELECT COUNT(*) AS n FROM audit_log "
                        "WHERE encounter_id = CAST(:eid AS uuid)"
                    ),
                    {"eid": encounter_id},
                )
            ).mappings().first()
        else:
            row = (
                await db.execute(
                    text(
                        "SELECT COUNT(*) AS n FROM audit_log "
                        " WHERE doctor_id = CAST(:uid AS uuid) "
                        "   AND encounter_id IS NULL "
                        "   AND ts >= NOW() - INTERVAL '5 minutes'"
                    ),
                    {"uid": doctor_id},
                )
            ).mappings().first()
        return int(row["n"])


async def _audit_event_types(encounter_id: str) -> list[str]:
    from backend.db import SessionLocal
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT event_type FROM audit_log "
                    "WHERE encounter_id = CAST(:eid AS uuid) "
                    "ORDER BY ts ASC, id ASC"
                ),
                {"eid": encounter_id},
            )
        ).mappings().all()
    return [r["event_type"] for r in rows]


def _fake_diag(**overrides):
    from backend.schemas import DiagnosisOutput
    base = {
        "primary_diagnosis": "Viêm da cơ địa",
        "primary_condition_key": "atopic_dermatitis",
        "confidence": 0.7,
        "differential": [],
        "key_features_observed": ["Da khô", "Vảy"],
        "management_tier": "outpatient_72h",
        "red_flags": [],
        "ood_flag": False,
        "image_quality_notes": "",
        "citations": [],
    }
    base.update(overrides)
    return DiagnosisOutput.model_validate(base)


async def _run(monkeypatch, *, image_bytes, fake_diag_obj=None, raise_diagnose=False):
    from backend.db import SessionLocal
    from backend.orchestrator import run_encounter
    from backend.vlm import DiagnoseError

    if raise_diagnose:
        async def _stub(**kwargs):
            raise DiagnoseError("simulated VLM failure")
    else:
        diag = fake_diag_obj if fake_diag_obj is not None else _fake_diag()
        async def _stub(**kwargs):
            return diag

    monkeypatch.setattr("backend.orchestrator.diagnose", _stub)

    doctor_id = await _demo_user_id()

    async with SessionLocal() as db:
        result = await run_encounter(
            db=db,
            doctor_id=doctor_id,
            image_bytes=image_bytes,
            image_content_type="image/jpeg",
            clinical_note="Phát ban đỏ ngứa nhẹ.",
            patient_context={
                "age_years": 30,
                "sex": "M",
                "symptom_duration_days": 5,
                "prior_treatments": None,
                "relevant_history": None,
            },
        )
    return result, doctor_id


@pytest.mark.asyncio
async def test_pipeline_happy_path_persists_and_audits(monkeypatch):
    """AC-P1: sharp JPEG + valid mocked diagnosis → encounter row has
    real result_json, audit_log has 6+ rows for that encounter_id."""
    result, _ = await _run(monkeypatch, image_bytes=_make_sharp_jpeg())
    assert result.preflight_passed
    assert result.encounter_id is not None
    assert result.diagnosis is not None
    assert result.diagnosis.primary_condition_key == "atopic_dermatitis"

    # audit_log should have ≥ 6 rows for this encounter_id
    types = await _audit_event_types(result.encounter_id)
    assert len(types) >= 6
    assert "vlm_call" in types
    assert "output_validated" in types
    assert "encounter_complete" in types


@pytest.mark.asyncio
async def test_preflight_fail_no_encounter(monkeypatch):
    """AC-P2: blurry JPEG → 0 encounters, 2 audit rows (start + preflight_fail)."""
    from backend.db import SessionLocal

    doctor_id = await _demo_user_id()
    async with SessionLocal() as db:
        before = (
            await db.execute(
                text(
                    "SELECT COUNT(*) AS n FROM encounters "
                    "WHERE doctor_id = CAST(:uid AS uuid)"
                ),
                {"uid": doctor_id},
            )
        ).mappings().first()["n"]

    result, _ = await _run(monkeypatch, image_bytes=_make_blurry_jpeg())

    assert not result.preflight_passed
    assert result.encounter_id is None
    assert result.diagnosis is None

    # Encounters count unchanged
    async with SessionLocal() as db:
        after = (
            await db.execute(
                text(
                    "SELECT COUNT(*) AS n FROM encounters "
                    "WHERE doctor_id = CAST(:uid AS uuid)"
                ),
                {"uid": doctor_id},
            )
        ).mappings().first()["n"]
    assert after == before, "preflight fail must not create an encounter row"


@pytest.mark.asyncio
async def test_vlm_failure_uses_fallback(monkeypatch):
    """AC-P3: diagnose() raises DiagnoseError → encounter row created
    with fallback result_json, audit_log shows 'vlm_call' with error."""
    from backend.db import SessionLocal

    result, _ = await _run(
        monkeypatch, image_bytes=_make_sharp_jpeg(), raise_diagnose=True
    )
    assert result.encounter_id is not None
    assert result.diagnosis is not None
    assert result.diagnosis.primary_diagnosis == "Không thể phân tích"
    assert result.diagnosis.ood_flag is True

    # Check audit row has the error
    async with SessionLocal() as db:
        row = (
            await db.execute(
                text(
                    "SELECT details FROM audit_log "
                    "WHERE encounter_id = CAST(:eid AS uuid) "
                    "  AND event_type = 'vlm_call'"
                ),
                {"eid": result.encounter_id},
            )
        ).mappings().first()
    assert row is not None
    assert "error" in row["details"]
    assert "simulated" in row["details"]["error"].lower()


@pytest.mark.asyncio
async def test_sanitize_drops_other_ood_differential_when_not_ood(monkeypatch):
    """AC-P4: differential entry with condition_key='other_ood' AND
    ood_flag=False → entry removed in result_json."""
    diag = _fake_diag(
        ood_flag=False,
        differential=[
            {
                "condition": "viêm da cơ địa",
                "condition_key": "atopic_dermatitis",
                "probability": 0.6,
            },
            {
                "condition": "khác",
                "condition_key": "other_ood",
                "probability": 0.2,
            },
        ],
    )
    result, _ = await _run(monkeypatch, image_bytes=_make_sharp_jpeg(), fake_diag_obj=diag)
    assert result.diagnosis is not None
    keys = [d.condition_key for d in result.diagnosis.differential]
    assert "other_ood" not in keys
    assert "atopic_dermatitis" in keys


@pytest.mark.asyncio
async def test_sanitize_clears_image_quality_notes_when_not_ood(monkeypatch):
    diag = _fake_diag(ood_flag=False, image_quality_notes="leftover note")
    result, _ = await _run(monkeypatch, image_bytes=_make_sharp_jpeg(), fake_diag_obj=diag)
    assert result.diagnosis is not None
    assert result.diagnosis.image_quality_notes == ""


@pytest.mark.asyncio
async def test_fallback_echo_detection(monkeypatch):
    """AC-P5: model returns FALLBACK shape → audit_log has vlm_fallback_ood event."""
    from backend.db import SessionLocal

    diag = _fake_diag(
        primary_diagnosis="Không thể phân tích",
        primary_condition_key="other_ood",
        confidence=0.0,
        differential=[],
        key_features_observed=[],
        management_tier="outpatient_72h",
        red_flags=["Khuyến nghị hội chẩn chuyên khoa da liễu để đánh giá thêm"],
        ood_flag=True,
        image_quality_notes="(any text)",
        citations=[],
    )
    result, _ = await _run(monkeypatch, image_bytes=_make_sharp_jpeg(), fake_diag_obj=diag)
    assert result.encounter_id is not None
    types = await _audit_event_types(result.encounter_id)
    assert "vlm_fallback_ood" in types
