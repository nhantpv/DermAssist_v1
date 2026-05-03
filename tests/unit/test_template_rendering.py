"""Smoke test that templates parse and render with the contexts the
routes pass them. Doesn't require the DB."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.templating import Jinja2Templates


@pytest.fixture
def templates() -> Jinja2Templates:
    backend_root = Path(__file__).resolve().parents[2] / "backend"
    return Jinja2Templates(directory=str(backend_root / "templates"))


def _fake_request(cookies: dict | None = None) -> MagicMock:
    request = MagicMock()
    request.cookies = cookies or {}
    request.url = SimpleNamespace(path="/")
    return request


def test_login_template_renders(templates: Jinja2Templates):
    request = _fake_request()
    resp = templates.TemplateResponse(
        request,
        "login.html",
        {"google_oauth_enabled": False, "flash": None},
    )
    body = bytes(resp.body).decode()
    assert "DermAssist" in body
    assert "Đăng nhập" in body
    assert "Closed beta" in body
    assert "name=\"username\"" in body
    assert "name=\"password\"" in body


def test_login_template_renders_google_button_when_enabled(
    templates: Jinja2Templates,
):
    request = _fake_request()
    resp = templates.TemplateResponse(
        request,
        "login.html",
        {"google_oauth_enabled": True, "flash": None},
    )
    body = bytes(resp.body).decode()
    assert "/auth/google" in body
    assert "Đăng nhập với Google" in body


def test_encounters_list_empty(templates: Jinja2Templates):
    request = _fake_request(cookies={"dermassist_session": "x"})
    resp = templates.TemplateResponse(
        request,
        "encounters_list.html",
        {"records": [], "current_user_username": "demo"},
    )
    body = bytes(resp.body).decode()
    assert "Chưa có encounter nào" in body
    assert "Tạo encounter đầu tiên" in body


def test_encounters_list_with_rows(templates: Jinja2Templates):
    request = _fake_request(cookies={"dermassist_session": "x"})
    rows = [
        {
            "id": "abcd1234-0000-0000-0000-000000000000",
            "created_at": datetime(2026, 5, 1, 10, 30),
            "primary_diagnosis": "Viêm da cơ địa",
            "management_tier": "outpatient_72h",
            "doctor_finalized": False,
        },
        {
            "id": "ffff5678-0000-0000-0000-000000000000",
            "created_at": datetime(2026, 5, 2, 11, 0),
            "primary_diagnosis": None,
            "management_tier": None,
            "doctor_finalized": True,
        },
    ]
    resp = templates.TemplateResponse(
        request,
        "encounters_list.html",
        {"records": rows, "current_user_username": "demo"},
    )
    body = bytes(resp.body).decode()
    assert "Viêm da cơ địa" in body
    assert "Khám trong 3 ngày" in body  # tier label
    assert "Đã hoàn tất" in body
    assert "đang xử lý" in body  # placeholder for None primary_diagnosis


def test_encounter_new_form_renders(templates: Jinja2Templates):
    request = _fake_request(cookies={"dermassist_session": "x"})
    resp = templates.TemplateResponse(
        request,
        "encounter_new.html",
        {
            "recent_encounters": [],
            "flash": None,
            "current_user_username": "demo",
        },
    )
    body = bytes(resp.body).decode()
    assert "Phân tích ảnh tổn thương" in body
    assert "name=\"image\"" in body
    assert "name=\"clinical_note\"" in body
    assert "name=\"age_years\"" in body
    assert "name=\"sex\"" in body
    assert "Phân tích" in body  # submit button


def test_encounter_result_stub_state(templates: Jinja2Templates):
    request = _fake_request(cookies={"dermassist_session": "x"})
    record = {
        "id": "abcd1234-0000-0000-0000-000000000000",
        "id_short": "abcd1234",
        "created_at": datetime(2026, 5, 1, 10, 30),
        "diagnosis": {"_stub": True},
        "image_url": None,
        "clinical_note": None,
        "doctor_finalized": False,
        "chat_messages": [],
    }
    resp = templates.TemplateResponse(
        request,
        "encounter_result.html",
        {"record": record, "current_user_username": "demo"},
    )
    body = bytes(resp.body).decode()
    assert "Chẩn đoán đang được xử lý" in body


def test_encounter_result_populated(templates: Jinja2Templates):
    request = _fake_request(cookies={"dermassist_session": "x"})
    record = {
        "id": "abcd1234-0000-0000-0000-000000000000",
        "id_short": "abcd1234",
        "created_at": datetime(2026, 5, 1, 10, 30),
        "image_url": "/uploads/abc.jpg",
        "clinical_note": "Nam, 35 tuổi, ngứa cẳng tay 2 tuần.",
        "pii_redacted_count": 0,
        "doctor_finalized": False,
        "chat_messages": [],
        "diagnosis": {
            "primary_diagnosis": "Viêm da cơ địa",
            "confidence": 0.62,
            "management_tier": "outpatient_72h",
            "ood_flag": False,
            "differential": [
                {"condition": "Chàm", "probability": 0.21},
                {"condition": "Viêm da tiếp xúc", "probability": 0.12},
            ],
            "key_features_observed": ["Da đỏ", "Vảy mỏng"],
            "red_flags": ["Theo dõi nhiệt độ"],
            "citations": ["chunk-a3f"],
        },
    }
    resp = templates.TemplateResponse(
        request,
        "encounter_result.html",
        {"record": record, "current_user_username": "demo"},
    )
    body = bytes(resp.body).decode()
    assert "Viêm da cơ địa" in body
    assert "62%" in body
    assert "Khám trong 3 ngày" in body
    assert "Chàm" in body
    assert "21%" in body
    assert "Da đỏ" in body
    assert "chunk-a3f" in body
    assert "Hỏi tiếp" in body  # chat panel header
    assert "Chẩn đoán cuối cùng" in body  # finalize form


def test_encounter_result_ood_state(templates: Jinja2Templates):
    request = _fake_request(cookies={"dermassist_session": "x"})
    record = {
        "id": "abcd1234-0000-0000-0000-000000000000",
        "id_short": "abcd1234",
        "created_at": datetime(2026, 5, 1, 10, 30),
        "image_url": None,
        "clinical_note": None,
        "doctor_finalized": False,
        "chat_messages": [],
        "diagnosis": {
            "primary_diagnosis": "Không xác định",
            "confidence": 0.18,
            "management_tier": "outpatient_24h",
            "ood_flag": True,
            "differential": [],
            "red_flags": [],
        },
    }
    resp = templates.TemplateResponse(
        request,
        "encounter_result.html",
        {"record": record, "current_user_username": "demo"},
    )
    body = bytes(resp.body).decode()
    assert "Ngoài phạm vi 8 bệnh hỗ trợ" in body


def test_encounter_result_finalized(templates: Jinja2Templates):
    request = _fake_request(cookies={"dermassist_session": "x"})
    record = {
        "id": "abcd1234-0000-0000-0000-000000000000",
        "id_short": "abcd1234",
        "created_at": datetime(2026, 5, 1, 10, 30),
        "image_url": None,
        "clinical_note": None,
        "doctor_finalized": True,
        "doctor_diagnosis": "Viêm da cơ địa (xác nhận)",
        "doctor_tier": "outpatient_72h",
        "doctor_notes": "Tái khám sau 1 tuần.",
        "chat_messages": [],
        "diagnosis": {
            "primary_diagnosis": "Viêm da cơ địa",
            "confidence": 0.62,
            "management_tier": "outpatient_72h",
            "ood_flag": False,
        },
    }
    resp = templates.TemplateResponse(
        request,
        "encounter_result.html",
        {"record": record, "current_user_username": "demo"},
    )
    body = bytes(resp.body).decode()
    assert "Bác sĩ đã hoàn tất chẩn đoán" in body
    assert "Viêm da cơ địa (xác nhận)" in body
    assert "Tái khám sau 1 tuần." in body
