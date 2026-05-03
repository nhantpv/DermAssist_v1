"""Unit tests for TIP-007-V1 Vietnamese PII redaction."""
from __future__ import annotations

from backend.text.pii import REPLACEMENT, redact_pii


# === Phone numbers ===

def test_redacts_vn_mobile_10_digit():
    r = redact_pii("Liên hệ 0912345678")
    assert REPLACEMENT in r.text
    assert r.count >= 1


def test_redacts_vn_mobile_with_country_code():
    r = redact_pii("Số: +84 912 345 678")
    assert REPLACEMENT in r.text
    assert r.count >= 1


def test_redacts_vn_mobile_with_dashes():
    r = redact_pii("Hotline: 091-234-5678")
    assert REPLACEMENT in r.text
    assert r.count >= 1


# === IDs ===

def test_redacts_cccd_12_digit():
    r = redact_pii("CCCD: 012345678901")
    assert REPLACEMENT in r.text
    assert r.count >= 1


def test_redacts_cmnd_9_digit():
    r = redact_pii("CMND: 123456789")
    assert REPLACEMENT in r.text
    assert r.count >= 1


def test_redacts_passport():
    r = redact_pii("Hộ chiếu: B1234567")
    assert REPLACEMENT in r.text
    assert r.count >= 1


# === Email ===

def test_redacts_email():
    r = redact_pii("Email: nguyen.van.a@example.com")
    assert REPLACEMENT in r.text
    assert r.count >= 1


# === Name prefixes ===

def test_redacts_name_with_bn_prefix():
    r = redact_pii("BN. Nguyen Van A đến khám với triệu chứng đau bụng.")
    assert REPLACEMENT in r.text
    # The clinical content "triệu chứng đau bụng" should remain
    assert "triệu chứng" in r.text


def test_redacts_name_with_ong_prefix():
    r = redact_pii("Ông Trần Văn B, 65 tuổi, có tiền sử cao huyết áp.")
    assert REPLACEMENT in r.text
    assert "tiền sử" in r.text


# === Edge cases ===

def test_no_pii_returns_original():
    text = "Tổn thương đỏ ở mặt gấp khuỷu tay, ngứa nhiều về đêm."
    r = redact_pii(text)
    assert r.text == text
    assert r.count == 0


def test_multiple_patterns_counted():
    r = redact_pii(
        "BN. Nguyen Van C, ĐT 0912345678, "
        "CMND 123456789, mail c@x.com"
    )
    assert r.count >= 4   # 1 name + 1 phone + 1 ID + 1 email


def test_empty_string():
    r = redact_pii("")
    assert r.text == ""
    assert r.count == 0


def test_none_input_safe():
    r = redact_pii(None)  # type: ignore[arg-type]
    assert r.text == ""
    assert r.count == 0


def test_clinical_term_not_false_positive():
    """'10 ngày' should not match phone patterns. 'ICD-10 L20.9' should
    not match anything. These are common clinical phrasings."""
    text = "Triệu chứng 10 ngày, ICD-10 L20.9, độ nặng 3/10."
    r = redact_pii(text)
    assert r.count == 0, f"False positive: {r.text}"
