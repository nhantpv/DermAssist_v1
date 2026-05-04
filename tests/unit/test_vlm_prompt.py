"""Unit tests for VLM prompt assembly. No network."""
from __future__ import annotations

from backend.retrieval.models import Chunk
from backend.schemas import PatientContext
from backend.vlm.prompt import (
    CONDITION_VN_NAMES,
    SYSTEM_PROMPT,
    build_user_content,
)


def test_system_prompt_lists_all_8_conditions():
    """All 8 condition keys + Vietnamese names appear in the system prompt."""
    for key, vn in CONDITION_VN_NAMES.items():
        assert key in SYSTEM_PROMPT, f"missing condition key: {key}"
        assert vn in SYSTEM_PROMPT.lower() or vn in SYSTEM_PROMPT, (
            f"missing VN name: {vn}"
        )
    assert "other_ood" in SYSTEM_PROMPT
    assert len(CONDITION_VN_NAMES) == 8


def test_system_prompt_loads_few_shot_examples():
    """At least one description from visual_descriptions.json is in
    the VISUAL_CONTEXT block."""
    import json
    from pathlib import Path

    path = Path("data/visual_descriptions.json")
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    descs = data["conditions"]["atopic_dermatitis"]["descriptions"]
    sample = descs[0]["description"].strip()[:60]
    assert sample in SYSTEM_PROMPT, (
        "Sample description from visual_descriptions.json missing in "
        "system prompt — few-shot loading is broken"
    )


def test_user_content_includes_patient_context_when_present():
    pc = PatientContext(
        age_years=35,
        sex="M",
        symptom_duration_days=7,
        prior_treatments="Đã thử kem dưỡng ẩm",
    )
    content = build_user_content(
        image_b64="ZmFrZQ==",
        clinical_note="Phát ban ngứa cánh tay",
        patient_context=pc,
        rag_chunks=[],
    )
    text_part = next(p["text"] for p in content if p["type"] == "text")
    assert "Tuổi: 35" in text_part
    assert "Nam" in text_part
    assert "7 ngày" in text_part
    assert "kem dưỡng ẩm" in text_part
    assert "Phát ban ngứa cánh tay" in text_part


def test_user_content_omits_null_patient_fields():
    pc = PatientContext(age_years=40)  # only age set
    content = build_user_content(
        image_b64="ZmFrZQ==",
        clinical_note="note",
        patient_context=pc,
        rag_chunks=[],
    )
    text_part = next(p["text"] for p in content if p["type"] == "text")
    assert "Tuổi: 40" in text_part
    assert "Giới:" not in text_part
    assert "Thời gian triệu chứng:" not in text_part


def test_user_content_includes_rag_chunks_with_markers():
    chunks = [
        Chunk(
            chunk_id="abc-123",
            doc_id="qd-4416",
            section_title="3.2.3 Điều trị",
            text="Acyclovir 800mg uống 5 lần/ngày trong 7 ngày.",
            chunk_index=0,
            condition_tags=["herpes_zoster"],
            score=0.5,
        ),
        Chunk(
            chunk_id="def-456",
            doc_id="qd-4416",
            section_title="2.4 Chẩn đoán",
            text="Tổn thương dạng mụn nước theo dermatome.",
            chunk_index=1,
            condition_tags=["herpes_zoster"],
            score=0.4,
        ),
    ]
    content = build_user_content(
        image_b64="ZmFrZQ==",
        clinical_note="",
        patient_context=None,
        rag_chunks=chunks,
    )
    text_part = next(p["text"] for p in content if p["type"] == "text")
    assert "[chunk:abc-123]" in text_part
    assert "[chunk:def-456]" in text_part
    assert "Acyclovir" in text_part
    assert "3.2.3 Điều trị" in text_part


def test_user_content_handles_empty_rag_gracefully():
    content = build_user_content(
        image_b64="ZmFrZQ==",
        clinical_note="note",
        patient_context=None,
        rag_chunks=[],
    )
    text_part = next(p["text"] for p in content if p["type"] == "text")
    assert "RAG_CONTEXT" in text_part
    assert "Không có trích đoạn nào liên quan" in text_part


def test_user_content_image_part_has_data_uri():
    content = build_user_content(
        image_b64="ZmFrZWltYWdl",
        clinical_note="x",
        patient_context=None,
        rag_chunks=[],
    )
    image_part = next(p for p in content if p["type"] == "image_url")
    assert image_part["image_url"]["url"] == "data:image/jpeg;base64,ZmFrZWltYWdl"


def test_user_content_caps_rag_at_top_n():
    """rag_top_n=3 by default; passing 5 chunks should only render 3."""
    chunks = [
        Chunk(
            chunk_id=f"id-{i}",
            doc_id="qd-4416",
            section_title=None,
            text=f"text {i}",
            chunk_index=i,
            condition_tags=[],
            score=0.0,
        )
        for i in range(5)
    ]
    content = build_user_content(
        image_b64="x",
        clinical_note="",
        patient_context=None,
        rag_chunks=chunks,
    )
    text_part = next(p["text"] for p in content if p["type"] == "text")
    assert "[chunk:id-0]" in text_part
    assert "[chunk:id-2]" in text_part
    assert "[chunk:id-3]" not in text_part
    assert "[chunk:id-4]" not in text_part
