"""Pydantic models — DermAssist VN.

Source of truth:
- BLUEPRINT.md §7.2 (the original V1 schemas)
- BLUEPRINT-AMENDMENT-001.md §3.3 (V1 amendment additions: PatientContext,
  ChatTurnRequest, ChatTurnResponse, and the `patient_context` field on
  EncounterCreateRequest).
"""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# === Enums ===
ManagementTier = Literal["home_care", "outpatient_72h", "outpatient_24h", "emergency"]

CONDITION_KEYS = Literal[
    "atopic_dermatitis", "fungal_infection", "herpes_zoster",
    "acne", "contact_dermatitis", "eczema", "psoriasis", "scabies",
    "other_ood",  # always available; sentinel for OOD
]


# === Patient context (Amendment §3.3) ===
class PatientContext(BaseModel):
    """Structured intake — doctor enters on patient's behalf."""
    age_years: int | None = Field(None, ge=0, le=120)
    sex: Literal["M", "F", "other", "unknown"] | None = None
    symptom_duration_days: int | None = Field(None, ge=0)
    prior_treatments: str | None = Field(None, max_length=1000)
    relevant_history: str | None = Field(None, max_length=2000)


# === API Request Models ===
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=4)


class EncounterCreateRequest(BaseModel):
    """V1 encounter intake. Image arrives as multipart upload, not in this model."""
    clinical_note: str = Field("", max_length=5000)
    # Amendment §3.3 addition: structured patient context. Optional so the
    # demo / minimal flow still works without it.
    patient_context: PatientContext | None = None


class DoctorFinalizeRequest(BaseModel):
    """Risk E — optional post-hoc input"""
    doctor_final_dx: str | None = Field(None, max_length=500)
    doctor_final_tier: ManagementTier | None = None
    doctor_notes: str | None = Field(None, max_length=2000)


# === Chat (Amendment §3.3) ===
class ChatTurnRequest(BaseModel):
    encounter_id: UUID
    message: str = Field(..., min_length=1, max_length=2000)


class ChatTurnResponse(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str
    citations: list[str] = Field(default_factory=list)
    created_at: datetime


# === VLM Output (the contract Qwen2.5-VL / OpenAI must produce) ===
class DifferentialItem(BaseModel):
    condition: str       # human-readable VN name
    condition_key: CONDITION_KEYS  # machine key for matching
    probability: float = Field(..., ge=0.0, le=1.0)


class DiagnosisOutput(BaseModel):
    primary_diagnosis: str = Field(..., max_length=128)
    primary_condition_key: CONDITION_KEYS
    confidence: float = Field(..., ge=0.0, le=1.0)
    differential: list[DifferentialItem] = Field(default_factory=list, max_length=5)
    key_features_observed: list[str] = Field(default_factory=list, max_length=8)
    management_tier: ManagementTier
    red_flags: list[str] = Field(default_factory=list, max_length=5)
    ood_flag: bool
    image_quality_notes: str = Field("", max_length=500)
    citations: list[str] = Field(default_factory=list)  # chunk_ids

    @field_validator("differential")
    @classmethod
    def differential_sums_le_1(cls, v):
        total = sum(d.probability for d in v)
        if total > 1.05:  # tolerance for float jitter
            raise ValueError(f"Differential probabilities sum to {total} > 1.0")
        return v


# === Composite OOD rule (REQ-SAF-008) ===
def compute_final_ood(out: DiagnosisOutput) -> bool:
    return (
        out.ood_flag
        or out.confidence < 0.4
        or out.primary_condition_key == "other_ood"
    )


# === Encounter response (returned to UI) ===
class EncounterResponse(BaseModel):
    id: str
    created_at: datetime
    image_url: str                       # signed Supabase Storage URL
    clinical_note: str                   # post-redaction (UI shows redaction count)
    pii_redacted_count: int
    preflight_passed: bool
    preflight_failure: str | None
    diagnosis: DiagnosisOutput | None    # null if preflight failed
    final_ood: bool                      # composite per compute_final_ood
    doctor_final_dx: str | None
    doctor_final_tier: ManagementTier | None
    doctor_notes: str | None
