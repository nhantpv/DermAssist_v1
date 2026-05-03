"""Unit tests for V1 schema additions (TIP-005-CANONICAL-V1).

Covers PatientContext, ChatTurnRequest, ChatTurnResponse only.
The Blueprint §7.2 schemas (DiagnosisOutput, etc.) remain Blueprint's
test responsibility and are not retested here.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.schemas import ChatTurnRequest, ChatTurnResponse, PatientContext


# === PatientContext ===

def test_patient_context_accepts_all_none():
    """All fields optional — empty model is valid."""
    pc = PatientContext()
    assert pc.age_years is None
    assert pc.sex is None
    assert pc.symptom_duration_days is None
    assert pc.prior_treatments is None
    assert pc.relevant_history is None


def test_patient_context_accepts_full_payload():
    pc = PatientContext(
        age_years=42,
        sex="M",
        symptom_duration_days=14,
        prior_treatments="Đã thử kem bôi steroid 1%",
        relevant_history="Tiền sử viêm da cơ địa từ nhỏ",
    )
    assert pc.age_years == 42
    assert pc.sex == "M"


def test_patient_context_rejects_age_out_of_range_high():
    with pytest.raises(ValidationError):
        PatientContext(age_years=121)


def test_patient_context_rejects_age_out_of_range_low():
    with pytest.raises(ValidationError):
        PatientContext(age_years=-1)


def test_patient_context_rejects_negative_duration():
    with pytest.raises(ValidationError):
        PatientContext(symptom_duration_days=-1)


def test_patient_context_rejects_invalid_sex():
    with pytest.raises(ValidationError):
        PatientContext(sex="male")  # not in literal set {M, F, other, unknown}


# === ChatTurnRequest ===

def test_chat_turn_request_accepts_minimal():
    req = ChatTurnRequest(encounter_id=uuid4(), message="Bệnh nhân có đỡ không?")
    assert req.message.startswith("Bệnh")


def test_chat_turn_request_rejects_empty_message():
    with pytest.raises(ValidationError):
        ChatTurnRequest(encounter_id=uuid4(), message="")


def test_chat_turn_request_rejects_overlong_message():
    with pytest.raises(ValidationError):
        ChatTurnRequest(encounter_id=uuid4(), message="x" * 2001)


def test_chat_turn_request_accepts_max_length_message():
    req = ChatTurnRequest(encounter_id=uuid4(), message="x" * 2000)
    assert len(req.message) == 2000


# === ChatTurnResponse ===

def test_chat_turn_response_accepts_empty_citations():
    resp = ChatTurnResponse(
        content="Theo hướng dẫn QĐ-4416, cần theo dõi thêm.",
        created_at=datetime.now(timezone.utc),
    )
    assert resp.citations == []
    assert resp.role == "assistant"


def test_chat_turn_response_accepts_citations():
    resp = ChatTurnResponse(
        content="Trích từ hướng dẫn.",
        citations=["chunk-a3f", "chunk-d2e"],
        created_at=datetime.now(timezone.utc),
    )
    assert resp.citations == ["chunk-a3f", "chunk-d2e"]


def test_chat_turn_response_role_is_fixed_assistant():
    """role is a Literal["assistant"] — anything else rejected."""
    with pytest.raises(ValidationError):
        ChatTurnResponse(
            role="user",  # type: ignore[arg-type]
            content="x",
            created_at=datetime.now(timezone.utc),
        )
