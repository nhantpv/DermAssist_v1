"""
Build notebooks/04_dataset_audit.ipynb from the cell definitions below.

This script is a build-time helper, not part of runtime. Run from repo root:

    python scripts/build_dataset_audit_notebook.py

It produces a clean, output-cleared .ipynb that the Colab user (or local user
with stdlib + pandas) can run top-to-bottom.

The notebook itself is the authoritative spec; this builder simply assembles
markdown + code cells in the right order. We use this script (not jupytext or
manual JSON) so the cell layout is reviewable as Python.
"""

from __future__ import annotations

import nbformat as nbf

NB = nbf.v4.new_notebook()

# Convenience helpers
def md(src: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(src.strip("\n"))


def code(src: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(src.strip("\n"))


# ----------------------------------------------------------------------------
# Cells
# ----------------------------------------------------------------------------

CELLS: list[nbf.NotebookNode] = []

CELLS.append(md("""
# 04 — Dataset Audit (Risk C mitigation)

**TIP-001** — DermAssist VN MVP.

This notebook audits public dermatology datasets to determine how much
labeled data we have for each of our 8 in-scope conditions, plus how many
out-of-distribution (OOD) samples we have for the OOD-detection eval
(Blueprint REQ-EVAL-003 target ≥ 85% recall).

It produces `data/dataset_audit.json` with per-dataset and aggregate counts.

**This audit is metadata-only.** No images are downloaded.  TIP-003 (visual
descriptions) and TIP-012 (eval) handle image fetches, filtered to what's
actually needed.

**Threshold:** REQ-EVAL-005 requires ≥ 20 samples per condition in the eval
set. Anything below that is flagged in the `gaps` field for Chủ thầu to
review (per TIP-001 reporting requirements, this is a Level-2 escalation).

## Datasets in scope

| Dataset | License | Source | Role |
|---|---|---|---|
| Fitzpatrick17k | CC BY-NC-SA 4.0 | mattgroh/fitzpatrick17k on GitHub | Primary — covers many in-scope conditions, includes Fitzpatrick scale |
| HAM10000 | CC BY-NC | Harvard Dataverse | Secondary — mostly neoplasms (OOD for our 8) |
| ISIC Archive | Mixed (mostly CC-0/CC-BY) | api.isic-archive.com | OOD pool — melanoma, BCC, SCC counts |
| PAD-UFES-20 | CC BY 4.0 | Mendeley | Optional — Brazilian smartphone photos for distribution-shift eval |
| DermNet NZ scrape | Per-image | dermnetnz.org | Last resort — only if a condition is below threshold |
| DDI (Stanford) | Restricted | — | Skipped (access difficult) |
"""))

CELLS.append(md("""
## Cell 1 — Setup

Lightweight only. We use stdlib `csv` to keep the notebook portable; pandas
is a convenience and falls back gracefully.
"""))

CELLS.append(code("""
# Colab convenience — pip-installs pandas/requests if not present.
# Local users with stdlib only also work; pandas use is optional.
try:
    import pandas as pd  # noqa: F401
    import requests       # noqa: F401
except ModuleNotFoundError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q",
                           "pandas", "requests"])
    import pandas as pd  # noqa: F401
    import requests       # noqa: F401

import csv, io, json, os, sys, urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Where this notebook writes its output
REPO_ROOT = Path.cwd()
# When run from /notebooks (Colab default after %cd or git clone), step up one.
if REPO_ROOT.name == "notebooks":
    REPO_ROOT = REPO_ROOT.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
DATA_DIR = REPO_ROOT / "data"
RAW_DIR.mkdir(parents=True, exist_ok=True)

print("Repo root:", REPO_ROOT)
print("Raw dir:  ", RAW_DIR, "(gitignored)")
print("Data dir: ", DATA_DIR)
"""))

CELLS.append(md("""
## Cell 2 — In-scope condition definitions

These are the 8 conditions the system is trained for (Blueprint §1.1). The
alias lists are used by `map_label()` below — they are **substring matches
on a lowercased label**, which works well for the messy labels in
Fitzpatrick17k (which include subspecies like "tinea pedis" and historical
names).

The DANGEROUS_OOD list covers conditions we explicitly want OOD-recall on:
these are dangerous skin conditions outside our 8 that the system MUST flag
as OOD rather than try to diagnose (REQ-SAF-010).
"""))

CELLS.append(code("""
IN_SCOPE_CONDITIONS = {
    "atopic_dermatitis": [
        "atopic dermatitis", "atopic-dermatitis", "eczema atopic",
    ],
    "fungal_infection": [
        "tinea", "tinea corporis", "tinea pedis", "tinea cruris",
        "onychomycosis", "fungal infection", "candidiasis", "dermatophytosis",
    ],
    "herpes_zoster": [
        "herpes zoster", "shingles", "zoster",
    ],
    "acne": [
        "acne", "acne vulgaris", "acne-vulgaris",
    ],
    "contact_dermatitis": [
        "contact dermatitis", "allergic contact dermatitis",
        "irritant contact dermatitis", "urticaria",
    ],
    "eczema": [
        "eczema", "dyshidrotic eczema", "nummular eczema",
    ],
    "psoriasis": [
        "psoriasis", "psoriasis vulgaris", "guttate psoriasis",
    ],
    "scabies": [
        "scabies",
    ],
}

# Conditions outside our 8 that we still care about — REQ-SAF-010 says the
# system MUST flag these as OOD rather than diagnose them. Useful as an
# explicit OOD test set.
DANGEROUS_OOD = [
    "melanoma", "cellulitis", "stevens-johnson", "sjs",
    "necrotizing", "necrotizing fasciitis", "lyell",
    "toxic epidermal necrolysis", "ten",
]

# REQ-EVAL-005 minimum samples per in-scope condition for eval.
THRESHOLD = 20

# REQ-EVAL-003 OOD recall target requires sufficient OOD samples.
OOD_MIN = 50

# Order matters because some aliases (e.g. "eczema atopic") would match both
# "eczema" and "atopic_dermatitis". We try the more-specific first.
SPECIFICITY_ORDER = [
    "atopic_dermatitis", "herpes_zoster", "fungal_infection",
    "contact_dermatitis", "psoriasis", "scabies",
    "acne", "eczema",  # generic — last
]
assert set(SPECIFICITY_ORDER) == set(IN_SCOPE_CONDITIONS.keys())
"""))

CELLS.append(md("""
## Cell 3 — Fuzzy label mapper

Maps a free-form label (`"atopic-dermatitis-spongiotic-dermatitis"`,
`"tinea pedis"`, `"melanoma"`, `"vitiligo"`) to one of:

- one of the 8 in-scope condition keys
- `"other_ood_dangerous"` — for melanoma, cellulitis, SJS, etc. (REQ-SAF-010)
- `"other_ood"` — anything else
- `"unknown"` — empty/null label

Why fuzzy matching: Fitzpatrick17k labels are clinical names with
subspecies (e.g. "tinea pedis" should map to fungal_infection); HAM10000
uses 7 short codes (akiec/bcc/bkl/df/mel/nv/vasc) — most are OOD for us.
"""))

CELLS.append(code("""
def map_label(label_str: str) -> str:
    if not label_str:
        return "unknown"
    label_lower = label_str.lower().strip()

    # HAM10000-specific short codes
    HAM10000_DX = {
        "nv":   "other_ood",            # nevus — benign, OOD for us
        "mel":  "other_ood_dangerous",  # melanoma — REQ-SAF-010
        "bkl":  "other_ood",            # benign keratosis
        "bcc":  "other_ood_dangerous",  # basal cell carcinoma — cancer
        "akiec": "other_ood_dangerous", # actinic keratosis / SCC in situ
        "vasc": "other_ood",            # vascular
        "df":   "other_ood",            # dermatofibroma
    }
    if label_lower in HAM10000_DX:
        return HAM10000_DX[label_lower]

    # Specificity-ordered substring match for in-scope conditions
    for key in SPECIFICITY_ORDER:
        for alias in IN_SCOPE_CONDITIONS[key]:
            if alias in label_lower:
                return key

    # Dangerous OOD (we want a separate count for these)
    for term in DANGEROUS_OOD:
        if term in label_lower:
            return "other_ood_dangerous"

    return "other_ood"


# Sanity check the mapper
test_cases = {
    "atopic dermatitis":         "atopic_dermatitis",
    "tinea corporis":            "fungal_infection",
    "Acne Vulgaris":             "acne",
    "psoriasis vulgaris":        "psoriasis",
    "scabies":                   "scabies",
    "herpes zoster":             "herpes_zoster",
    "shingles":                  "herpes_zoster",
    "allergic contact dermatitis": "contact_dermatitis",
    "dyshidrotic eczema":        "eczema",
    "melanoma":                  "other_ood_dangerous",
    "mel":                       "other_ood_dangerous",
    "nv":                        "other_ood",
    "vitiligo":                  "other_ood",
    "":                          "unknown",
}
for inp, expected in test_cases.items():
    got = map_label(inp)
    assert got == expected, f"map_label({inp!r}) = {got!r}, want {expected!r}"
print("✓ map_label sanity OK across", len(test_cases), "cases")
"""))

CELLS.append(md("""
## Cell 4 — Fitzpatrick17k

Source: https://github.com/mattgroh/fitzpatrick17k (CC BY-NC-SA 4.0).

We pull `fitzpatrick17k.csv` from the GitHub raw URL — it's metadata only
(md5 hash, label, Fitzpatrick scale, image URL).  Per TIP-001 constraint
we only fetch metadata.  Raw CSV lands in `data/raw/` (gitignored).

Note: the `fitzpatrick_scale` column has values `1..6` for valid Fitzpatrick
types and `-1` for unrated — we report both.
"""))

CELLS.append(code("""
FITZ_URL = "https://raw.githubusercontent.com/mattgroh/fitzpatrick17k/main/fitzpatrick17k.csv"
FITZ_LOCAL = RAW_DIR / "fitzpatrick17k.csv"

if not FITZ_LOCAL.exists():
    print("Downloading Fitzpatrick17k metadata...")
    urllib.request.urlretrieve(FITZ_URL, FITZ_LOCAL)
print("Fitzpatrick17k CSV:", FITZ_LOCAL.stat().st_size, "bytes")

fitz_total = 0
fitz_by_condition = Counter()
fitz_by_cond_skin = defaultdict(Counter)  # mapped_key -> {fitz_scale -> count}
fitz_skin_distribution = Counter()
fitz_unmapped_labels = Counter()

with open(FITZ_LOCAL) as f:
    rdr = csv.DictReader(f)
    for row in rdr:
        fitz_total += 1
        label = row.get("label", "")
        scale = row.get("fitzpatrick_scale", "")
        mapped = map_label(label)
        fitz_by_condition[mapped] += 1
        fitz_by_cond_skin[mapped][scale] += 1
        fitz_skin_distribution[scale] += 1
        if mapped == "other_ood":
            fitz_unmapped_labels[label.lower().strip()] += 1

print(f"Fitzpatrick17k: {fitz_total:,} samples")
print()
print("By mapped condition:")
for k in list(IN_SCOPE_CONDITIONS) + ["other_ood_dangerous", "other_ood", "unknown"]:
    print(f"  {k:30s} {fitz_by_condition.get(k, 0):>5d}")

print()
print("Fitzpatrick scale distribution:")
for scale in sorted(fitz_skin_distribution, key=lambda s: (s == '-1', s)):
    print(f"  scale {scale:>3s}: {fitz_skin_distribution[scale]:>5d}")
"""))

CELLS.append(md("""
## Cell 5 — HAM10000

Source: Harvard Dataverse (DOI 10.7910/DVN/DBW86T), file `HAM10000_metadata.csv`
(datafile id 3172582). License CC BY-NC.

HAM10000 is mostly skin neoplasms (nevus, melanoma, BCC, etc.) — mostly OOD
for our 8 conditions. Useful primarily for the OOD test set.
"""))

CELLS.append(code("""
HAM_URL = "https://dataverse.harvard.edu/api/access/datafile/3172582"
HAM_LOCAL = RAW_DIR / "HAM10000_metadata.csv"

if not HAM_LOCAL.exists():
    print("Downloading HAM10000 metadata from Harvard Dataverse...")
    try:
        urllib.request.urlretrieve(HAM_URL, HAM_LOCAL)
    except Exception as e:
        print(f"  WARN: HAM10000 fetch failed ({e}). Skipping.")

ham_total = 0
ham_by_condition = Counter()
ham_dx_raw = Counter()

if HAM_LOCAL.exists() and HAM_LOCAL.stat().st_size > 100:
    print("HAM10000 CSV:", HAM_LOCAL.stat().st_size, "bytes")
    # Harvard Dataverse serves it tab-separated with quoted fields
    with open(HAM_LOCAL) as f:
        rdr = csv.DictReader(f, delimiter="\\t")
        for row in rdr:
            ham_total += 1
            dx_raw = row.get("dx", "").strip('"').strip()
            ham_dx_raw[dx_raw] += 1
            ham_by_condition[map_label(dx_raw)] += 1

    print(f"HAM10000: {ham_total:,} samples")
    print()
    print("Raw dx codes:")
    for dx, n in ham_dx_raw.most_common():
        print(f"  {dx:8s} {n:>5d}")
    print()
    print("Mapped:")
    for k in list(IN_SCOPE_CONDITIONS) + ["other_ood_dangerous", "other_ood", "unknown"]:
        print(f"  {k:30s} {ham_by_condition.get(k, 0):>5d}")
else:
    print("HAM10000: skipped (metadata not retrievable in this environment)")
"""))

CELLS.append(md("""
## Cell 6 — ISIC Archive (count only)

The ISIC archive (https://api.isic-archive.com) hosts ~550k dermatology
images with mixed licenses. For audit purposes we only need a total count
to report as available OOD pool. Detailed per-diagnosis filtering via the
public API is non-trivial (the simple `?diagnosis=...` filter is not
documented to work) and is deferred to TIP-012 if needed.
"""))

CELLS.append(code("""
ISIC_API = "https://api.isic-archive.com/api/v2/images/?limit=1"
isic_total = None
try:
    with urllib.request.urlopen(ISIC_API, timeout=15) as resp:
        payload = json.load(resp)
        isic_total = payload.get("count")
        print(f"ISIC archive total images: {isic_total:,}")
        print("(Most are dermoscopic — mostly OOD for our 8 clinical-photo conditions.)")
except Exception as e:
    print(f"  WARN: ISIC API call failed ({e}). Skipping.")
"""))

CELLS.append(md("""
## Cell 7 — PAD-UFES-20 (skipped: requires Mendeley download)

The PAD-UFES-20 dataset (Brazilian smartphone-photo dermatology, 6 classes,
~2300 images) is an excellent distribution-shift eval source. License is
CC BY 4.0.

Direct fetch from Mendeley's S3 cache requires either an interactive
download (browser) or knowledge of the file UUID, neither of which is
reliable in a non-interactive build environment. We mark this as
**deferred to TIP-012** when the eval suite is built — at that point a
Homeowner-driven manual download from the Mendeley UI is a one-time
preparation step.
"""))

CELLS.append(code("""
PAD_NOTE = (
    "PAD-UFES-20 not fetched programmatically. "
    "Manual download required from "
    "https://data.mendeley.com/datasets/zr7vgbcyr2/1 — defer to TIP-012."
)
print(PAD_NOTE)
"""))

CELLS.append(md("""
## Cell 8 — Aggregate, gap analysis, write `dataset_audit.json`

Identify any in-scope condition with fewer than `THRESHOLD` (20) total
samples across the audited datasets. Each such gap is a Level-2
escalation per TIP-001 — Chủ thầu must decide whether to:

1. Augment from DermNet NZ (per-image license), or
2. Drop the condition from MVP scope, or
3. Accept the gap and document the limitation in `eval-limitations.md`.
"""))

CELLS.append(code("""
in_scope_total = Counter()
for src in (fitz_by_condition, ham_by_condition):
    for k in IN_SCOPE_CONDITIONS:
        in_scope_total[k] += src.get(k, 0)

ood_total = (
    fitz_by_condition.get("other_ood", 0)
    + fitz_by_condition.get("other_ood_dangerous", 0)
    + ham_by_condition.get("other_ood", 0)
    + ham_by_condition.get("other_ood_dangerous", 0)
)
ood_dangerous_total = (
    fitz_by_condition.get("other_ood_dangerous", 0)
    + ham_by_condition.get("other_ood_dangerous", 0)
)

# Fitzpatrick III–V coverage on Fitzpatrick17k specifically
iii_iv_v = sum(fitz_skin_distribution.get(s, 0) for s in ("3", "4", "5"))
fitz_iii_iv_v_pct = (iii_iv_v / fitz_total * 100.0) if fitz_total else 0.0

# Gaps
gaps = []
for k in IN_SCOPE_CONDITIONS:
    n = in_scope_total[k]
    if n < THRESHOLD:
        gaps.append({
            "condition": k,
            "available": n,
            "threshold": THRESHOLD,
            "recommendation": (
                "Augment from DermNet NZ (per-image license) "
                "or drop from MVP scope. Escalation to Chủ thầu."
            ),
        })

audit = {
    "schema_version": "1",
    "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "thresholds": {"per_condition_min": THRESHOLD, "ood_min_for_recall": OOD_MIN},
    "datasets": {
        "fitzpatrick17k": {
            "license": "CC BY-NC-SA 4.0",
            "source_url": FITZ_URL,
            "total_samples": fitz_total,
            "by_condition": dict(fitz_by_condition),
            "by_condition_and_skin_tone": {
                k: dict(v) for k, v in fitz_by_cond_skin.items()
            },
            "skin_tone_distribution": dict(fitz_skin_distribution),
            "unmapped_top_labels": dict(fitz_unmapped_labels.most_common(20)),
        },
        "ham10000": {
            "license": "CC BY-NC",
            "source_url": HAM_URL,
            "total_samples": ham_total,
            "raw_dx_codes": dict(ham_dx_raw),
            "by_condition": dict(ham_by_condition),
        },
        "isic_archive": {
            "license": "Mixed (mostly CC-0/CC-BY)",
            "source_url": "https://api.isic-archive.com",
            "total_samples": isic_total,
            "note": "Counted via API. Detailed per-diagnosis filtering deferred to TIP-012.",
        },
        "pad_ufes_20": {
            "license": "CC BY 4.0",
            "source_url": "https://data.mendeley.com/datasets/zr7vgbcyr2/1",
            "total_samples": None,
            "note": PAD_NOTE,
        },
    },
    "summary": {
        "in_scope_total": dict(in_scope_total),
        "ood_total": ood_total,
        "ood_dangerous_total": ood_dangerous_total,
    },
    "gaps": gaps,
    "fitzpatrick_skew": {
        "iii_iv_v_total": iii_iv_v,
        "iii_iv_v_pct": round(fitz_iii_iv_v_pct, 2),
        "target_pct": 30.0,
        "meets_target": fitz_iii_iv_v_pct >= 30.0,
    },
}

audit_path = DATA_DIR / "dataset_audit.json"
with open(audit_path, "w", encoding="utf-8") as f:
    json.dump(audit, f, indent=2, ensure_ascii=False)

print(f"Wrote {audit_path}")
print(f"Size: {audit_path.stat().st_size:,} bytes")
print()
print("In-scope totals:")
for k, n in in_scope_total.most_common():
    flag = " ⚠️ GAP" if n < THRESHOLD else ""
    print(f"  {k:30s} {n:>5d}{flag}")
print(f"\\nOOD total: {ood_total:,} (of which dangerous: {ood_dangerous_total:,})")
print(f"Fitz III–V: {iii_iv_v:,} ({fitz_iii_iv_v_pct:.1f}%)")
"""))

CELLS.append(md("""
## Cell 9 — Findings summary

The next two cells print a human-readable summary of `dataset_audit.json`
suitable for pasting into a Completion Report.
"""))

CELLS.append(code("""
print("=" * 64)
print("DATASET AUDIT — TIP-001 — DermAssist VN")
print("=" * 64)
print(f"Generated: {audit['generated_at']}")
print()

print("Per-condition coverage (in-scope, ≥{} required):".format(THRESHOLD))
print("-" * 64)
for k in IN_SCOPE_CONDITIONS:
    n = in_scope_total[k]
    status = "OK   " if n >= THRESHOLD else "GAP  "
    print(f"  [{status}] {k:25s} {n:>5d}")

print()
print("OOD coverage (≥{} required for REQ-EVAL-003 recall test):".format(OOD_MIN))
print("-" * 64)
print(f"  total OOD samples:    {ood_total:>6d}")
print(f"  dangerous OOD:        {ood_dangerous_total:>6d}")
print(f"  OOD threshold met:    {'YES' if ood_total >= OOD_MIN else 'NO'}")

print()
print("Skin-tone diversity (Fitzpatrick17k, ≥30% III–V required):")
print("-" * 64)
print(f"  III–V samples:        {iii_iv_v:>6d}")
print(f"  III–V %:              {fitz_iii_iv_v_pct:>6.1f}%")
print(f"  Meets target:         {'YES' if fitz_iii_iv_v_pct >= 30.0 else 'NO'}")

print()
print("Gaps (REQ-EVAL-005 violations — escalate to Chủ thầu):")
print("-" * 64)
if not gaps:
    print("  None — all in-scope conditions meet the {} threshold.".format(THRESHOLD))
else:
    for g in gaps:
        print(f"  ⚠️ {g['condition']}: {g['available']} samples (need {g['threshold']})")
"""))

CELLS.append(md("""
## Cell 10 — Done

`data/dataset_audit.json` is the committed artifact. Raw CSVs in
`data/raw/` are gitignored (license terms).

**Next steps:**

- TIP-002 (RAG corpus) — independent of this audit.
- TIP-003 (visual descriptions) — selects 5 reference images per in-scope
  condition. Will draw from Fitzpatrick17k (skin-tone-balanced) per the
  numbers above.
- TIP-012 (eval) — uses the gap report to decide which conditions need
  augmentation, and which datasets to draw the OOD test set from.

Any condition flagged in `gaps` is a **Level-2 escalation**: Chủ thầu
must rule on whether to (1) augment from DermNet NZ, (2) drop from MVP
scope, or (3) accept and document the limitation.
"""))


# ----------------------------------------------------------------------------
# Assemble + save
# ----------------------------------------------------------------------------

NB["cells"] = CELLS
NB["metadata"] = {
    "kernelspec": {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    },
    "language_info": {
        "name": "python",
        "version": "3.11",
    },
}

OUT = "notebooks/04_dataset_audit.ipynb"
with open(OUT, "w", encoding="utf-8") as f:
    nbf.write(NB, f)

print(f"Wrote {OUT} — {len(CELLS)} cells")
