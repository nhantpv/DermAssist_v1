"""Test config — env-var defaults for backend.config + shared fixtures.

`Settings` is `lru_cache`'d, so once it loads, env-var changes during a
test session won't affect already-cached values. Set fallbacks here.
Real test runs override DATABASE_URL via the local docker-compose
postgres (`postgresql+asyncpg://dermassist:dermassist_dev@localhost:5432/dermassist`).

Shared fixtures (TIP-011):
  mock_diagnose      — replace backend.orchestrator.diagnose with a stub
  mock_chat_followup — replace backend.routes.chat.chat_followup with a stub
"""
import os

import pytest

# Provide a deterministic JWT secret for tests if the user hasn't exported one.
os.environ.setdefault("JWT_SECRET_KEY", "x" * 64)
# Provide a default DATABASE_URL pointing at the docker-compose postgres.
# Integration tests check connectivity and skip on failure; unit tests don't
# touch the DB but still need the URL to satisfy Settings validation.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://dermassist:dermassist_dev@localhost:5432/dermassist",
)


def _default_diagnosis(**overrides):
    """Build a deterministic DiagnosisOutput. Overrides merge in."""
    from backend.schemas import DiagnosisOutput

    base = {
        "primary_diagnosis": "Viêm da cơ địa",
        "primary_condition_key": "atopic_dermatitis",
        "confidence": 0.7,
        "differential": [],
        "key_features_observed": ["Da khô"],
        "management_tier": "outpatient_72h",
        "red_flags": [],
        "ood_flag": False,
        "image_quality_notes": "",
        "citations": [],
    }
    base.update(overrides)
    return DiagnosisOutput.model_validate(base)


@pytest.fixture
def mock_diagnose(monkeypatch):
    """Replace `backend.orchestrator.diagnose` with a stub.

    Returns a setter callable. Call it with no args for the default
    DiagnosisOutput, or with kwargs to override fields. The diagnosis
    can also be replaced wholesale by passing `diagnosis=...`.
    """
    state = {"diagnosis": _default_diagnosis()}

    async def _stub(**kwargs):
        return state["diagnosis"]

    monkeypatch.setattr("backend.orchestrator.diagnose", _stub)

    def _set(diagnosis=None, **overrides):
        if diagnosis is not None:
            state["diagnosis"] = diagnosis
        elif overrides:
            state["diagnosis"] = _default_diagnosis(**overrides)
        return state["diagnosis"]

    return _set


@pytest.fixture
def mock_chat_followup(monkeypatch):
    """Replace `backend.routes.chat.chat_followup` with a stub.

    Returns a setter callable. Call with no args for the default
    ChatResponse, or pass `content=`, `citations=`, etc. to override.
    """
    from backend.vlm.chat import ChatResponse

    state = {
        "response": ChatResponse(
            content="Phản hồi mặc định cho test.",
            citations=[],
            latency_ms=10,
            chunks_used=[],
        )
    }

    async def _stub(*, prior_messages, current_message, rag_chunks):
        # Default behavior: derive chunks_used from the RAG list so the
        # audit row reflects what was actually passed in.
        resp = state["response"]
        return ChatResponse(
            content=resp.content,
            citations=resp.citations,
            latency_ms=resp.latency_ms,
            chunks_used=[c.chunk_id for c in rag_chunks] or resp.chunks_used,
        )

    monkeypatch.setattr("backend.routes.chat.chat_followup", _stub)

    def _set(**fields):
        current = state["response"]
        merged = {
            "content": current.content,
            "citations": current.citations,
            "latency_ms": current.latency_ms,
            "chunks_used": current.chunks_used,
        }
        merged.update(fields)
        state["response"] = ChatResponse(**merged)
        return state["response"]

    return _set
