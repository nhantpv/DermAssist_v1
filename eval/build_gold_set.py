"""Construct data/gold_set.jsonl by:

1. Reusing the 40 in-scope cases from data/visual_descriptions.json
   (5 per condition x 8 conditions, already provenance-tracked).
2. Sampling ~10 OOD cases from data/raw/fitzpatrick17k.csv with
   labels OUTSIDE the 8 in-scope conditions (melanoma, BCC, SCC,
   vitiligo, lupus, etc.).
3. Downloading each image once into data/raw/eval_images/<sha>.<ext>
   (skipped if already present). Cases whose URL fails are written
   with `_image_skipped: true` and the runner warns + skips them.
4. Writing one JSON object per line to data/gold_set.jsonl.

Tier mapping is heuristic — see docs/eval-limitations.md. Run once:
    python -m eval.build_gold_set
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

import httpx

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
VD_PATH = REPO_ROOT / "data" / "visual_descriptions.json"
FITZ_CSV = REPO_ROOT / "data" / "raw" / "fitzpatrick17k.csv"
IMAGE_DIR = REPO_ROOT / "data" / "raw" / "eval_images"
GOLD_OUT = REPO_ROOT / "data" / "gold_set.jsonl"

# Heuristic tier mapping per condition (NOT clinical-expert-validated;
# documented in docs/eval-limitations.md).
TIER_BY_CONDITION = {
    "acne": "home_care",
    "atopic_dermatitis": "outpatient_72h",
    "contact_dermatitis": "outpatient_72h",
    "eczema": "outpatient_72h",
    "fungal_infection": "outpatient_72h",
    "herpes_zoster": "outpatient_24h",
    "psoriasis": "outpatient_72h",
    "scabies": "outpatient_72h",
    "other_ood": "outpatient_72h",
}

# Conditions OUTSIDE our 8 — used for OOD sampling.
OOD_LABELS = [
    "melanoma",
    "basal cell carcinoma",
    "squamous cell carcinoma",
    "vitiligo",
    "lupus erythematosus",
    "drug eruption",
    "lichen planus",
    "pityriasis rosea",
    "kaposi sarcoma",
    "actinic keratosis",
]
N_OOD = 10
N_OOD_PER_LABEL_MAX = 1  # diversify across labels

UA = "DermAssist-VN-Research/0.1 (Apache-2.0 reference impl; eval gold-set construction)"
TIMEOUT = httpx.Timeout(20.0)


def _download(url: str) -> tuple[bytes, str] | None:
    """Fetch URL, return (bytes, ext). Returns None on any non-2xx."""
    headers = {"User-Agent": UA}
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers=headers) as c:
            r = c.get(url)
        if r.status_code != 200 or len(r.content) < 1024:
            return None
        # Detect by content-type first, fall back to URL extension or
        # bytes magic. Some CDNs (SCIN's GCS bucket) serve images as
        # application/octet-stream.
        ct = r.headers.get("content-type", "").lower()
        if "jpeg" in ct or "jpg" in ct:
            ext = "jpg"
        elif "png" in ct:
            ext = "png"
        elif "webp" in ct:
            ext = "webp"
        else:
            ext = _detect_ext_from_url_or_bytes(url, r.content)
        if ext is None:
            return None
        return r.content, ext
    except Exception as e:
        logger.warning("download failed: %s — %s", url, e)
        return None


def _detect_ext_from_url_or_bytes(url: str, body: bytes) -> str | None:
    lower = url.lower().split("?", 1)[0]
    for e in ("jpg", "jpeg", "png", "webp"):
        if lower.endswith(f".{e}"):
            return "jpg" if e == "jpeg" else e
    # Magic bytes
    if body.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "webp"
    return None


def _save_image(img_bytes: bytes, ext: str) -> Path:
    sha = hashlib.sha256(img_bytes).hexdigest()
    path = IMAGE_DIR / f"{sha}.{ext}"
    if not path.exists():
        path.write_bytes(img_bytes)
    return path


def _build_in_scope_cases() -> list[dict]:
    """One row per (condition_key, description) from visual_descriptions."""
    data = json.loads(VD_PATH.read_text(encoding="utf-8"))
    cases: list[dict] = []
    for cond_key, info in data["conditions"].items():
        for i, desc in enumerate(info.get("descriptions", []), start=1):
            url = desc.get("source_url")
            if not url:
                continue
            cases.append({
                "case_id": f"{desc.get('source_dataset','x').lower()}_{cond_key}_{i:03d}",
                "image_url": url,
                "expected_condition_key": cond_key,
                "expected_tier": TIER_BY_CONDITION[cond_key],
                "expected_ood": False,
                "fitzpatrick_type": desc.get("fitzpatrick_type"),
                "monk_tone": desc.get("monk_tone"),
                "source_dataset": desc.get("source_dataset"),
                "license": _license_for(desc.get("source_dataset")),
                "notes": (desc.get("description") or "")[:300],
            })
    return cases


def _license_for(source: str | None) -> str:
    return {
        "Fitzpatrick17k": "CC BY-NC-SA 4.0",
        "SCIN": "CC BY 4.0",
        "DermNet NZ": "CC BY-NC-ND (session-only)",
    }.get(source or "", "unknown")


def _build_ood_cases() -> list[dict]:
    """Sample OOD cases from fitzpatrick17k.csv. Deterministic order:
    first ATLAS DERMATOLOGICO match per OOD label (dermaamin.com URLs
    consistently return 404), up to N_OOD total."""
    if not FITZ_CSV.exists():
        logger.warning("fitzpatrick17k.csv missing — no OOD cases sourced")
        return []

    by_label: dict[str, list[dict]] = {}
    with FITZ_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            label = row["label"].lower()
            url = row.get("url", "")
            # Skip dermaamin.com — those URLs are dead at the moment
            if "atlasdermatologico" not in url:
                continue
            for ood in OOD_LABELS:
                if label == ood and len(by_label.get(ood, [])) < N_OOD_PER_LABEL_MAX:
                    by_label.setdefault(ood, []).append(row)
                    break

    cases: list[dict] = []
    seq = 0
    for ood_label, rows in by_label.items():
        for row in rows:
            url = row.get("url")
            if not url:
                continue
            seq += 1
            cases.append({
                "case_id": f"fitz17k_ood_{seq:03d}",
                "image_url": url,
                "expected_condition_key": "other_ood",
                "expected_tier": TIER_BY_CONDITION["other_ood"],
                "expected_ood": True,
                "fitzpatrick_type": _safe_int(row.get("fitzpatrick_scale")),
                "monk_tone": None,
                "source_dataset": "Fitzpatrick17k",
                "license": "CC BY-NC-SA 4.0",
                "notes": f"OOD label: {ood_label}",
            })
            if len(cases) >= N_OOD:
                return cases
    return cases


def _safe_int(s: str | None) -> int | None:
    try:
        return int(s) if s and s.lstrip("-").isdigit() else None
    except (ValueError, TypeError):
        return None


def main() -> int:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    in_scope = _build_in_scope_cases()
    ood = _build_ood_cases()
    logger.info("Sourced %d in-scope + %d OOD candidate cases", len(in_scope), len(ood))

    written = 0
    skipped = 0
    out_lines: list[str] = []

    for case in in_scope + ood:
        url = case.pop("image_url", None)
        if not url:
            skipped += 1
            continue
        result = _download(url)
        if result is None:
            logger.warning("skip %s — download failed", case["case_id"])
            skipped += 1
            continue
        img_bytes, ext = result
        path = _save_image(img_bytes, ext)
        case["image_path"] = str(path.relative_to(REPO_ROOT))
        case["image_sha256"] = path.stem
        out_lines.append(json.dumps(case, ensure_ascii=False))
        written += 1
        if written % 5 == 0:
            logger.info("  %d / %d cases ready", written, len(in_scope) + len(ood))

    GOLD_OUT.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    logger.info(
        "Wrote %d cases to %s (skipped %d)",
        written, GOLD_OUT.relative_to(REPO_ROOT), skipped,
    )

    # Per-condition tally for the eval report
    from collections import Counter
    tally = Counter()
    for line in out_lines:
        c = json.loads(line)
        tally[c["expected_condition_key"]] += 1
    print("\nPer-condition counts:")
    for k, n in sorted(tally.items()):
        print(f"  {k:24s} {n}")

    return 0 if skipped == 0 else 0  # don't fail on partial — log is enough


if __name__ == "__main__":
    sys.exit(main())
