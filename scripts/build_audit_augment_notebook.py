"""
Build notebooks/04b_audit_augment.ipynb (TIP-001A).

Same convention as scripts/build_dataset_audit_notebook.py: assemble a
clean, output-cleared .ipynb so the cell layout is reviewable as Python.
"""

from __future__ import annotations

import nbformat as nbf

NB = nbf.v4.new_notebook()


def md(src: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(src.strip("\n"))


def code(src: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(src.strip("\n"))


CELLS: list[nbf.NotebookNode] = []

CELLS.append(md("""
# 04b — Dataset Audit AUGMENT (TIP-001A)

**Why this notebook exists:** TIP-001 found three in-scope conditions
with **0 samples** in Fitzpatrick17k + HAM10000:

- `atopic_dermatitis`
- `fungal_infection`
- `herpes_zoster` (DANGEROUS — REQ-EVAL-001 ship-blocker)

This amendment adds two more datasets and applies an **augment-then-drop
policy**: if any of the 3 still has fewer than `THRESHOLD = 20` samples
after augmentation, it is dropped from Blueprint §1.1.

**Datasets added in this notebook:**

| Dataset | License | What we pull |
|---|---|---|
| SCIN (Google Health, 2024) | CC BY 4.0 | `scin_labels.csv` + `scin_cases.csv` from public GCS |
| DermNet NZ | Per-image (CC BY-NC-ND-style) | Topic-page **scrape** for image URLs + counts only — NO image bytes |

**Outputs:**

- `data/dataset_audit.json` bumped to `version="v2"` with new datasets
- `data/condition_scope.json` (NEW) — authoritative in-scope list after augment
- `docs/dermnet_attribution.md` (NEW) — attribution + non-redistribution notice
- Conditional update to BLUEPRINT.md §1.1 if any condition is dropped

**Run on Colab or local — no GPU required.**
"""))

CELLS.append(md("""
## Cell 1 — Setup

We reuse `IN_SCOPE_CONDITIONS` and `map_label()` from TIP-001 by re-defining
them here. (Alternative: `%run notebooks/04_dataset_audit.ipynb` — but that
re-fetches the v1 datasets, slower.) The augment additions are clearly
marked `# +TIP-001A`.
"""))

CELLS.append(code("""
try:
    import pandas as pd
    import requests  # noqa: F401  (we use urllib.request, but keep available)
except ModuleNotFoundError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q",
                           "pandas", "requests"])
    import pandas as pd
    import requests  # noqa: F401

import ast, csv, json, os, re, sys, time, urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError

REPO_ROOT = Path.cwd()
if REPO_ROOT.name == "notebooks":
    REPO_ROOT = REPO_ROOT.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
DATA_DIR = REPO_ROOT / "data"
DOCS_DIR = REPO_ROOT / "docs"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# Polite User-Agent per TIP constraint
USER_AGENT = (
    "DermAssist-VN-Research/0.1 "
    "(Apache-2.0 reference impl; non-commercial, dataset audit only)"
)

print("Repo root:", REPO_ROOT)
print("Raw dir:  ", RAW_DIR, "(gitignored)")
"""))

CELLS.append(md("""
## Cell 2 — Re-define taxonomy and mapper

Copied from TIP-001 with **TIP-001A additions** marked `# +TIP-001A`.
"""))

CELLS.append(code("""
IN_SCOPE_CONDITIONS = {
    "atopic_dermatitis": [
        "atopic dermatitis", "atopic-dermatitis", "eczema atopic",
        "atopic",  # +TIP-001A — SCIN often writes just "Atopic Dermatitis"
    ],
    "fungal_infection": [
        "tinea", "tinea corporis", "tinea pedis", "tinea cruris",
        "onychomycosis", "fungal infection", "candidiasis", "dermatophytosis",
        "dermatophyte", "ringworm",  # +TIP-001A
    ],
    "herpes_zoster": [
        "herpes zoster", "shingles", "zoster",
        "varicella zoster",  # +TIP-001A — VZV reactivation
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

DANGEROUS_OOD = [
    "melanoma", "cellulitis", "stevens-johnson", "sjs",
    "necrotizing", "necrotizing fasciitis", "lyell",
    "toxic epidermal necrolysis", "ten",
]

THRESHOLD = 20

# Order matters: more specific first (so 'atopic dermatitis' wins over 'eczema').
SPECIFICITY_ORDER = [
    "atopic_dermatitis", "herpes_zoster", "fungal_infection",
    "contact_dermatitis", "psoriasis", "scabies",
    "acne", "eczema",
]
assert set(SPECIFICITY_ORDER) == set(IN_SCOPE_CONDITIONS.keys())

HAM10000_DX = {
    "nv": "other_ood", "mel": "other_ood_dangerous", "bkl": "other_ood",
    "bcc": "other_ood_dangerous", "akiec": "other_ood_dangerous",
    "vasc": "other_ood", "df": "other_ood",
}

def map_label(label_str: str) -> str:
    if not label_str:
        return "unknown"
    label_lower = label_str.lower().strip()
    if label_lower in HAM10000_DX:
        return HAM10000_DX[label_lower]
    for key in SPECIFICITY_ORDER:
        for alias in IN_SCOPE_CONDITIONS[key]:
            if alias in label_lower:
                return key
    for term in DANGEROUS_OOD:
        if term in label_lower:
            return "other_ood_dangerous"
    return "other_ood"


# Sanity test
for inp, expected in {
    "atopic dermatitis": "atopic_dermatitis",
    "Atopic": "atopic_dermatitis",
    "tinea corporis": "fungal_infection",
    "ringworm": "fungal_infection",
    "Herpes Zoster": "herpes_zoster",
    "varicella zoster": "herpes_zoster",
    "Eczema": "eczema",
}.items():
    assert map_label(inp) == expected, f"map_label({inp!r}) failed"
print("✓ map_label sanity OK")
"""))

CELLS.append(md("""
## Cell 3 — SCIN dataset

SCIN ("Skin Condition Image Network", Google Health, 2024) is published
under CC BY 4.0. The `scin_labels.csv` file holds dermatologist-assigned
weighted labels per case; each case may have up to 3 conditions.

**Schema verification** (per TIP constraint — Google may have changed
columns since this TIP was written): we print the columns first and adapt
to the actual schema.

**Mapping decision:** SCIN labels are list-string values like
`"['Eczema', 'Allergic Contact Dermatitis']"`. We count each case under
its **first** label (the most-weighted dermatologist assignment) to
avoid double-counting. We also report the per-case multi-label
distribution as `multi_label_cases` for transparency.
"""))

CELLS.append(code("""
SCIN_LABELS_URL = "https://storage.googleapis.com/dx-scin-public-data/dataset/scin_labels.csv"
SCIN_CASES_URL = "https://storage.googleapis.com/dx-scin-public-data/dataset/scin_cases.csv"

SCIN_LABELS_LOCAL = RAW_DIR / "scin_labels.csv"
SCIN_CASES_LOCAL = RAW_DIR / "scin_cases.csv"

scin_total = 0
scin_by_condition = Counter()
scin_columns_actual = []
scin_label_col = None
scin_multi_label_cases = 0
scin_skipped_empty = 0

try:
    if not SCIN_LABELS_LOCAL.exists():
        print("Downloading SCIN labels...")
        urllib.request.urlretrieve(SCIN_LABELS_URL, SCIN_LABELS_LOCAL)
    if not SCIN_CASES_LOCAL.exists():
        print("Downloading SCIN cases...")
        urllib.request.urlretrieve(SCIN_CASES_URL, SCIN_CASES_LOCAL)

    labels_df = pd.read_csv(SCIN_LABELS_LOCAL)
    cases_df = pd.read_csv(SCIN_CASES_LOCAL)
    scin_columns_actual = list(labels_df.columns)
    print(f"SCIN labels rows: {len(labels_df):,}")
    print(f"Schema: {scin_columns_actual[:6]}...")

    # The expected column name (per TIP). If Google renamed it we adapt.
    candidates = [
        "dermatologist_skin_condition_on_label_name",
        "dermatologist_skin_condition_label",
        "weighted_skin_condition_label",
    ]
    for c in candidates:
        if c in labels_df.columns:
            scin_label_col = c
            break
    if scin_label_col is None:
        raise RuntimeError(
            f"SCIN: no expected label column in {scin_columns_actual}. "
            "Schema may have changed — escalate to Chủ thầu."
        )
    print(f"Using label column: {scin_label_col}")

    def first_label_of(raw):
        # raw is a string like "['Eczema', 'Allergic Contact Dermatitis']", "[]", or NaN
        if not isinstance(raw, str) or not raw.strip():
            return None
        try:
            parsed = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return raw.strip()
        if not isinstance(parsed, list) or not parsed:
            return None
        return str(parsed[0]) if parsed[0] else None

    for raw in labels_df[scin_label_col].fillna(""):
        scin_total += 1
        first = first_label_of(raw)
        if first is None:
            scin_skipped_empty += 1
            continue
        # Detect multi-label cases for the audit report
        try:
            parsed = ast.literal_eval(raw) if isinstance(raw, str) else None
            if isinstance(parsed, list) and len(parsed) > 1:
                scin_multi_label_cases += 1
        except (ValueError, SyntaxError):
            pass
        scin_by_condition[map_label(first)] += 1

    print(f"SCIN: {scin_total:,} cases ({scin_skipped_empty:,} empty-labels)")
    print(f"  multi-label cases: {scin_multi_label_cases:,}")
    print()
    print("Mapped (using first/most-weighted label per case):")
    for k in list(IN_SCOPE_CONDITIONS) + ["other_ood_dangerous", "other_ood", "unknown"]:
        n = scin_by_condition.get(k, 0)
        print(f"  {k:30s} {n:>5d}")
except (HTTPError, URLError, OSError, RuntimeError) as e:
    print(f"⚠ SCIN unavailable: {e}")
"""))

CELLS.append(md("""
## Cell 4 — DermNet NZ scrape (label + URL only, polite)

DermNet has no API; we fetch a curated list of topic pages and count the
clinical images linked from each. **No image bytes are downloaded** in
this notebook.

**License:** DermNet images are © DermNet NZ, individually licensed
(typically CC BY-NC-ND with caveats). Per TIP-001A constraint, we record
**URLs and counts only** for non-commercial research / eval reference;
we do not redistribute images. See `docs/dermnet_attribution.md`.

**Rate limiting:** 1.0 s between requests, with the project User-Agent.

**Slug discovery:** Two TIP-suggested slugs (`onychomycosis`,
`cutaneous-candidiasis`) returned 404. We substitute the actual DermNet
slugs found via probing: `fungal-nail-infections` and
`chronic-mucocutaneous-candidiasis`. This deviation is documented in the
Completion Report.
"""))

CELLS.append(code("""
DERMNET_TOPICS = {
    "atopic_dermatitis": [
        "https://dermnetnz.org/topics/atopic-dermatitis",
    ],
    "fungal_infection": [
        "https://dermnetnz.org/topics/tinea-corporis",
        "https://dermnetnz.org/topics/tinea-pedis",
        "https://dermnetnz.org/topics/tinea-cruris",
        # Substitutes for TIP slugs that 404'd:
        "https://dermnetnz.org/topics/fungal-nail-infections",
        "https://dermnetnz.org/topics/chronic-mucocutaneous-candidiasis",
    ],
    "herpes_zoster": [
        "https://dermnetnz.org/topics/herpes-zoster",
    ],
}

HEADERS = {"User-Agent": USER_AGENT}

def fetch_topic(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="replace")

# DermNet uses RELATIVE paths like /assets/Uploads/...jpg or
# /assets/collection-O/.../...jpg for clinical images. The simple
# https://dermnetnz.org/... pattern matches almost nothing.
DERMNET_BASE = "https://dermnetnz.org"
IMG_PAT = re.compile(
    r'<img[^>]+src="(/assets/[^"]+\\.(?:jpg|jpeg|png)|https?://[^"]*dermnetnz\\.org/[^"]*\\.(?:jpg|jpeg|png))"',
    re.IGNORECASE,
)

# Exclude site-chrome assets that aren't clinical photos.
EXCLUDE_SUBSTRINGS = (
    "logo", "icon", "avatar", "banner", "favicon",
    "home-page-pro-waitlist", "magnifying-glass", "/svg/",
)

def count_images_on_page(html: str) -> list[str]:
    urls = IMG_PAT.findall(html)
    # Resolve relative paths to absolute, then dedupe + filter chrome.
    absolute = []
    for u in urls:
        if u.startswith("/"):
            absolute.append(DERMNET_BASE + u)
        else:
            absolute.append(u)
    return sorted(set(
        u for u in absolute
        if not any(skip in u.lower() for skip in EXCLUDE_SUBSTRINGS)
    ))

dermnet_counts = {}
dermnet_urls = {}
dermnet_topic_status = {}

for cond_key, urls in DERMNET_TOPICS.items():
    all_imgs = []
    for u in urls:
        time.sleep(1.0)  # polite
        try:
            html = fetch_topic(u)
            imgs = count_images_on_page(html)
            all_imgs.extend(imgs)
            dermnet_topic_status[u] = f"OK ({len(imgs)} images)"
        except (HTTPError, URLError, OSError) as e:
            dermnet_topic_status[u] = f"FAIL: {type(e).__name__}: {e}"
            print(f"⚠ {u} failed: {e}")
    dermnet_counts[cond_key] = len(set(all_imgs))
    dermnet_urls[cond_key] = sorted(set(all_imgs))

print()
print("DermNet NZ counts (per gap condition):")
for k, v in dermnet_counts.items():
    print(f"  {k:20s} {v:>4d} unique images")
print()
print("Per-topic status:")
for u, status in dermnet_topic_status.items():
    print(f"  {status:35s} {u}")
"""))

CELLS.append(md("""
## Cell 5 — Reload v1 audit, merge augmentation

Read the existing `data/dataset_audit.json` (v1 from TIP-001), preserve
its v1 datasets and v1 totals untouched, append the two new datasets,
and re-aggregate `summary.in_scope_total` across all four datasets.

**Why preserve v1 totals:** per TIP-001A constraint we do not alter
Fitzpatrick17k or HAM10000 counts — only ADD datasets.
"""))

CELLS.append(code("""
audit_path = DATA_DIR / "dataset_audit.json"
audit = json.loads(audit_path.read_text(encoding="utf-8"))
print(f"Loaded v1 audit. Datasets: {list(audit['datasets'].keys())}")
print(f"v1 in_scope_total:")
for k, v in audit["summary"]["in_scope_total"].items():
    print(f"  {k:25s} {v:>5d}")
"""))

CELLS.append(code("""
# +TIP-001A: insert SCIN
audit["datasets"]["scin"] = {
    "license": "CC BY 4.0",
    "source_url": SCIN_LABELS_URL,
    "schema_columns": scin_columns_actual,
    "label_column_used": scin_label_col,
    "total_samples": int(scin_total),
    "empty_label_cases": int(scin_skipped_empty),
    "multi_label_cases": int(scin_multi_label_cases),
    "by_condition": {k: int(v) for k, v in scin_by_condition.items()},
    "mapping_note": (
        "Each case has up to 3 dermatologist-assigned weighted labels; "
        "we count under the first/most-weighted label only to avoid "
        "double-counting. multi_label_cases reports how many cases had >1 "
        "label."
    ),
}

# +TIP-001A: insert DermNet NZ (URLs and counts; NO image bytes)
audit["datasets"]["dermnet_nz"] = {
    "license": "Per-image (CC BY-NC-ND-style); not redistributed",
    "source_url": "https://dermnetnz.org",
    "by_condition": {k: int(v) for k, v in dermnet_counts.items()},
    "image_urls_per_condition": dermnet_urls,
    "topic_status": dermnet_topic_status,
    "scrape_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "user_agent": USER_AGENT,
    "license_note": (
        "Image URLs are recorded for non-commercial research/eval reference. "
        "Image bytes are © DermNet NZ and are NOT redistributed. "
        "See docs/dermnet_attribution.md."
    ),
}

# Bump version + record augmentation timestamp
audit["version"] = "v2"
audit["augmented_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# Re-aggregate summary.in_scope_total across all 4 datasets
v1_in_scope = dict(audit["summary"]["in_scope_total"])
new_in_scope = {}
for cond_key in IN_SCOPE_CONDITIONS:
    total = 0
    for ds_name, ds_data in audit["datasets"].items():
        total += int(ds_data.get("by_condition", {}).get(cond_key, 0))
    new_in_scope[cond_key] = total

audit["summary"]["in_scope_total_v1"] = v1_in_scope  # for traceability
audit["summary"]["in_scope_total"] = new_in_scope

# Re-compute gaps
audit["gaps"] = [
    {"condition": k, "available": v, "threshold": THRESHOLD,
     "still_below_after_augment": True}
    for k, v in new_in_scope.items() if v < THRESHOLD
]

audit_path.write_text(
    json.dumps(audit, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print(f"Wrote {audit_path} (v2)")
print()
print("v2 in_scope_total (all datasets aggregated):")
for k in IN_SCOPE_CONDITIONS:
    v1 = v1_in_scope.get(k, 0)
    v2 = new_in_scope[k]
    delta = v2 - v1
    flag = " ⚠ STILL GAP" if v2 < THRESHOLD else ""
    print(f"  {k:25s} v1={v1:>5d}  v2={v2:>5d}  (Δ +{delta}){flag}")
"""))

CELLS.append(md("""
## Cell 6 — Apply drop rule, write `condition_scope.json`

Per TIP-001A, the augment-then-drop rule is:

> If a condition still has fewer than `THRESHOLD = 20` samples after
> augmentation, it is **dropped** from Blueprint §1.1.

`THRESHOLD == 20` is exact; a count of exactly 20 keeps the condition.

`data/condition_scope.json` is the **authoritative** source of which
conditions remain in scope. Blueprint §1.1 references it.
"""))

CELLS.append(code("""
condition_scope = {
    "version": "v2",
    "decision_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "rule": (
        f"Drop condition if total samples < {THRESHOLD} after augmenting "
        "with DermNet NZ + SCIN (TIP-001A, augment-then-drop policy)."
    ),
    "in_scope": [],
    "dropped": [],
    "rationale_per_condition": {},
    "samples_per_condition": new_in_scope,
}

for cond_key, count in new_in_scope.items():
    if count >= THRESHOLD:
        condition_scope["in_scope"].append(cond_key)
        condition_scope["rationale_per_condition"][cond_key] = (
            f"KEPT — {count} samples available across datasets."
        )
    else:
        condition_scope["dropped"].append(cond_key)
        condition_scope["rationale_per_condition"][cond_key] = (
            f"DROPPED — {count} samples (< {THRESHOLD} threshold) after "
            f"augmentation. Cannot certify REQ-EVAL-001 sensitivity."
        )

scope_path = DATA_DIR / "condition_scope.json"
scope_path.write_text(
    json.dumps(condition_scope, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print(f"Wrote {scope_path}")
print()
print(f"In-scope ({len(condition_scope['in_scope'])} of 8):")
for k in condition_scope["in_scope"]:
    print(f"  ✓ {k:25s} {new_in_scope[k]:>5d} samples")
print(f"Dropped ({len(condition_scope['dropped'])} of 8):")
for k in condition_scope["dropped"]:
    print(f"  ✗ {k:25s} {new_in_scope[k]:>5d} samples")
"""))

CELLS.append(md("""
## Cell 7 — Done

The audit JSON v2 and `condition_scope.json` are written. The Builder
will (outside the notebook):

- Update Blueprint §1.1 if `condition_scope.dropped` is non-empty
  (mark dropped conditions with `~~strikethrough~~ (DROPPED — see TIP-001A)`
  and add a note pointing at `data/condition_scope.json`).
- Author `docs/dermnet_attribution.md` (NEW file required by TIP-001A
  for license compliance).
- Commit all three files together: this notebook, the data files, and
  any Blueprint amendment.

The single bottom-line summary printed below is what should appear in
the Completion Report's TEST RESULTS.
"""))

CELLS.append(code("""
print("=" * 72)
print("TIP-001A — AUGMENTED DATASET AUDIT — DermAssist VN")
print("=" * 72)
print(f"Augmented at: {audit['augmented_at']}")
print()
print(f"Datasets: {list(audit['datasets'].keys())}")
print()
print(f"Per-condition counts (v1 → v2):")
print(f"  {'condition':25s}  {'v1':>5s}  {'v2':>5s}  decision")
print("  " + "-" * 56)
for k in IN_SCOPE_CONDITIONS:
    v1 = v1_in_scope.get(k, 0)
    v2 = new_in_scope[k]
    decision = "KEEP" if v2 >= THRESHOLD else "DROP"
    print(f"  {k:25s}  {v1:>5d}  {v2:>5d}  {decision}")
print()
print(f"Final in-scope: {len(condition_scope['in_scope'])} of 8")
if condition_scope["dropped"]:
    print(f"Dropped: {condition_scope['dropped']}")
    print()
    print("→ Builder should update BLUEPRINT.md §1.1 to mark dropped conditions.")
else:
    print("All 8 conditions retained — BLUEPRINT.md §1.1 unchanged.")
"""))

# ---------------------------------------------------------------------------
NB["cells"] = CELLS
NB["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3.11"},
}

OUT = "notebooks/04b_audit_augment.ipynb"
with open(OUT, "w", encoding="utf-8") as f:
    nbf.write(NB, f)

print(f"Wrote {OUT} — {len(CELLS)} cells")
