"""Vietnamese PII redaction — regex-only, fast, narrow.

Detects four pattern families:
1. Phone numbers (VN mobile + landline)
2. National ID (CMND 9-digit, CCCD 12-digit, passport)
3. Email addresses
4. Personal-name prefixes ("BN. <Name>", "ô. <Name>", "bà <Name>",
   "cô <Name>", "chú <Name>", "anh <Name>", "chị <Name>")
   — narrow patterns; we accept some misses to avoid clinical-term
   false positives.

Returns (redacted_text, redaction_count). Each match → "[PII]".

NOT covered (deferred to V2):
- Vietnamese name detection without prefix
- Address detection
- Date-of-birth patterns
- Health insurance ID patterns

Trade-off: false-negative-favoring. We prefer a leaked PII over
mangled clinical content. Doctors are still instructed in the form
not to enter patient-identifying info.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

REPLACEMENT: Final[str] = "[PII]"

# === Pattern definitions ===

# VN phone: 10-digit mobile (03/05/07/08/09 prefix) or 11-digit
# landline-with-prefix. Allow optional country code, spaces, dashes,
# parentheses around area code.
_PHONE_PATTERNS: Final[list[re.Pattern]] = [
    # Mobile: optional +84 / 0084 / 84, then 9 digits starting with 3/5/7/8/9
    re.compile(r"(?:\+84|0084|84)?[\s\-.]?0?[35789]\d{1}[\s\-.]?\d{3}[\s\-.]?\d{3,4}"),
    # Landline: (0xx) xxxx xxxx — area code in parens, 8 digits
    re.compile(r"\(0\d{1,3}\)[\s\-.]?\d{3,4}[\s\-.]?\d{4}"),
]

# National IDs:
# - CCCD: 12 digits (modern, post-2016)
# - CMND: 9 digits (legacy)
# - Passport: 1-2 letters + 7 digits (e.g., "B12345678")
# Word boundary critical to avoid matching parts of long ID-like strings.
_ID_PATTERNS: Final[list[re.Pattern]] = [
    re.compile(r"\b\d{12}\b"),                     # CCCD
    re.compile(r"\b\d{9}\b"),                      # CMND
    re.compile(r"\b[A-Z]{1,2}\d{7}\b"),            # Passport
]

# Email — standard pattern, case-insensitive
_EMAIL_PATTERN: Final[re.Pattern] = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

# Personal-name prefixes — case-insensitive Vietnamese.
# Match prefix + 1–4 capitalized name tokens. Conservative: requires
# the prefix to anchor the match (we don't try to detect bare names).
# Vietnamese diacritic range: À-ỹ covers most VN letters.
_NAME_PREFIX_PATTERN: Final[re.Pattern] = re.compile(
    r"\b(?:BN\.?|bệnh\s*nhân|ông|bà|cô|chú|anh|chị|em|bác)\s+"
    r"(?:[A-ZÀ-ỹ][a-zÀ-ỹ]+\s*){1,4}",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class RedactionResult:
    text: str
    count: int


def redact_pii(text: str) -> RedactionResult:
    """Apply all four pattern families. Returns redacted text + count.

    Empty / None / non-string input returns ("", 0) — defensive against
    form-handling edge cases.
    """
    if not text or not isinstance(text, str):
        return RedactionResult(text="", count=0)

    count = 0
    out = text

    # Apply in fixed order — phones first (long digit runs), then IDs,
    # then emails, then name prefixes. Each `subn` returns count.
    for patterns in (_PHONE_PATTERNS, _ID_PATTERNS):
        for p in patterns:
            out, n = p.subn(REPLACEMENT, out)
            count += n

    out, n = _EMAIL_PATTERN.subn(REPLACEMENT, out)
    count += n

    out, n = _NAME_PREFIX_PATTERN.subn(REPLACEMENT, out)
    count += n

    return RedactionResult(text=out, count=count)
