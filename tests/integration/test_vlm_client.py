"""Integration tests for the VLM client with mocked HTTP transport.

The transport is replaced via httpx.MockTransport, so no network is
hit. Verifies the happy path, the single-retry path on validation
failure, and the failure path after both attempts fail."""
from __future__ import annotations

import json
import logging

import httpx
import pytest

from backend.vlm import DiagnoseError, diagnose
from backend.vlm import client as vlm_client


def _valid_json_payload() -> dict:
    """A DiagnosisOutput-shaped dict that should validate."""
    return {
        "primary_diagnosis": "Zona thần kinh",
        "primary_condition_key": "herpes_zoster",
        "confidence": 0.78,
        "differential": [
            {
                "condition": "Zona thần kinh",
                "condition_key": "herpes_zoster",
                "probability": 0.78,
            },
            {
                "condition": "Viêm da tiếp xúc",
                "condition_key": "contact_dermatitis",
                "probability": 0.12,
            },
        ],
        "key_features_observed": [
            "Mụn nước cụm theo dermatome",
            "Nền da đỏ",
        ],
        "management_tier": "outpatient_24h",
        "red_flags": [],
        "ood_flag": False,
        "image_quality_notes": "",
        "citations": ["abc-123"],
    }


def _wrap_in_chat_response(content_obj: dict | str) -> dict:
    """Wrap a payload in the OpenAI Chat Completions response envelope."""
    content = (
        json.dumps(content_obj)
        if isinstance(content_obj, dict)
        else content_obj
    )
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


def _install_mock_transport(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[dict | str],
) -> list[int]:
    """Patch httpx.AsyncClient so each call returns the next response
    from the list. Returns a [counter] list whose [0] tracks call count."""
    counter = [0]

    def _handler(request: httpx.Request) -> httpx.Response:
        idx = counter[0]
        counter[0] += 1
        if idx >= len(responses):
            raise AssertionError(
                f"VLM client made {idx + 1} HTTP calls; only "
                f"{len(responses)} mock responses queued"
            )
        body = responses[idx]
        if isinstance(body, str):
            return httpx.Response(200, content=body)
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(_handler)
    real_client = httpx.AsyncClient

    def _patched(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(vlm_client.httpx, "AsyncClient", _patched)
    return counter


@pytest.fixture(autouse=True)
def _vlm_settings(monkeypatch: pytest.MonkeyPatch):
    """Force vlm_provider=openai and a dummy api_key for these tests."""
    from backend.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "vlm_provider", "openai")
    monkeypatch.setattr(settings, "vlm_api_key", "sk-test-dummy")
    monkeypatch.setattr(settings, "vlm_model", "gpt-4o-mini")
    monkeypatch.setattr(settings, "vlm_endpoint", "https://api.openai.com/v1")


@pytest.mark.asyncio
async def test_diagnose_happy_path(monkeypatch):
    counter = _install_mock_transport(
        monkeypatch,
        [_wrap_in_chat_response(_valid_json_payload())],
    )

    result = await diagnose(
        image_bytes=b"\xff\xd8\xff\xe0fakejpegbytes",
        clinical_note_redacted="Phát ban đau rát một bên ngực",
        patient_context=None,
        rag_chunks=[],
    )

    assert result.primary_condition_key == "herpes_zoster"
    assert 0 < result.confidence <= 1.0
    assert result.management_tier == "outpatient_24h"
    assert counter[0] == 1, "happy path should call HTTP exactly once"


@pytest.mark.asyncio
async def test_diagnose_retry_on_invalid_then_valid(monkeypatch, caplog):
    """First call returns malformed JSON; second returns valid.
    Diagnose() should succeed and log a warning."""
    counter = _install_mock_transport(
        monkeypatch,
        [
            _wrap_in_chat_response("this is not json {{{ "),
            _wrap_in_chat_response(_valid_json_payload()),
        ],
    )

    with caplog.at_level(logging.WARNING, logger="backend.vlm.retry"):
        result = await diagnose(
            image_bytes=b"img",
            clinical_note_redacted="",
            patient_context=None,
            rag_chunks=[],
        )

    assert result.primary_condition_key == "herpes_zoster"
    assert counter[0] == 2, "should retry exactly once"
    assert any(
        "Retrying once" in rec.message
        for rec in caplog.records
    ), "expected warning about retry; got: " + ", ".join(r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_diagnose_raises_after_two_failures(monkeypatch):
    """Two malformed responses → DiagnoseError with VN message."""
    _install_mock_transport(
        monkeypatch,
        [
            _wrap_in_chat_response("garbage {{{"),
            _wrap_in_chat_response("still garbage }}}"),
        ],
    )

    with pytest.raises(DiagnoseError) as exc_info:
        await diagnose(
            image_bytes=b"img",
            clinical_note_redacted="",
            patient_context=None,
            rag_chunks=[],
        )
    assert "không thể tạo chẩn đoán" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_non_openai_provider_raises_not_implemented(monkeypatch):
    """AC-S3: vlm_provider != 'openai' fails loudly."""
    from backend.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "vlm_provider", "anthropic")

    with pytest.raises(NotImplementedError):
        await diagnose(
            image_bytes=b"img",
            clinical_note_redacted="",
            patient_context=None,
            rag_chunks=[],
        )
