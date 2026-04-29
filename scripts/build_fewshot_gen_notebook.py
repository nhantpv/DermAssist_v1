"""
Build notebooks/03_fewshot_gen.ipynb (TIP-003).

Same convention as the other build helpers: assemble a clean,
output-cleared .ipynb so the cell layout is reviewable as Python.

Run:  python scripts/build_fewshot_gen_notebook.py
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
# 03 — Few-shot Visual Descriptions (TIP-003)

**Goal:** generate Vietnamese descriptions of skin condition images
using Qwen2.5-VL-7B-Instruct-AWQ (the same model that will serve at
runtime), and write them to `data/visual_descriptions.json` for use
as the `VISUAL_CONTEXT` block in the system prompt (Blueprint §8).

**Why Qwen self-describe (not GPT-4o):**
- Apache 2.0 cleanliness (Risk B Approach 3 decision).
- Full reproducibility — same model that serves runtime.
- Few-shot examples align with model's own perception.

**Source dataset:** Fitzpatrick17k (CC BY-NC-SA 4.0, attribution
required, no redistribution of raw images).

**Run on Colab T4** (or any machine with CUDA + ≥ 13 GB VRAM).
Determinism is required (`temperature=0`, `seed=42`); a re-run must
produce identical descriptions.

**Acceptance hooks:**

- Qwen2.5-VL-7B-Instruct-AWQ loads under 13 GB VRAM
- Per condition: `descriptions` length = `min(5, available)`
- Each description: Vietnamese, 3–5 sentences (≤200 tokens)
- `validation.diagnostic_term_violations ≤ 2`
- Same notebook re-run → identical output
- Total runtime < 30 min on T4

## Coverage caveat (escalation flagged in Completion Report)

Per TIP-001's audit, three in-scope conditions have **zero**
Fitzpatrick17k images: `atopic_dermatitis`, `fungal_infection`,
`herpes_zoster`. TIP-001A's augment-then-keep policy closed those
gaps via SCIN + DermNet NZ, but TIP-003's spec says Fitzpatrick17k
only.

This notebook implements **strict TIP-003 by default**: those three
conditions will end up with `n_descriptions = 0`. A SCIN-fallback
path is provided as a single boolean flag at the top of Cell 4:
flip `ENABLE_SCIN_FALLBACK = True` to fill the gaps from SCIN
(license CC BY 4.0, public images on GCS). Default is `False` per
TIP-003 spec.
"""))

CELLS.append(md("""
## Cell 1 — Setup

vLLM and Pillow are the heavy installs. `requests` for image fetches.
"""))

CELLS.append(code("""
import importlib.util, subprocess, sys

def ensure(*pkgs: str) -> None:
    missing = [p for p in pkgs
               if importlib.util.find_spec(p.split('==')[0].split('[')[0]) is None]
    if missing:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', *missing])

ensure('vllm', 'pillow', 'requests')

import csv, hashlib, json, os, random, ssl, time
import urllib.request, urllib.error
from collections import Counter, defaultdict
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from PIL import Image

REPO_ROOT = Path.cwd()
if REPO_ROOT.name == 'notebooks':
    REPO_ROOT = REPO_ROOT.parent
RAW_DIR = REPO_ROOT / 'data' / 'raw'
DATA_DIR = REPO_ROOT / 'data'
IMAGES_DIR = RAW_DIR / 'fitz_selected'
RAW_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# Polite, identifying UA for image fetches
USER_AGENT = ('DermAssist-VN-Research/0.1 '
              '(Apache-2.0 reference impl; non-commercial)')

print('Repo root:', REPO_ROOT)
print('Raw dir:  ', RAW_DIR, '(gitignored)')
"""))

CELLS.append(md("""
## Cell 2 — (Colab only) Mount Drive for cache persistence

Skip on local. On Colab, mount Drive so the model weights and image
cache survive runtime restarts.

```python
from google.colab import drive
drive.mount('/content/drive')

PROJECT_DIR = Path('/content/drive/MyDrive/DermAssist')
RAW_DIR = PROJECT_DIR / 'data' / 'raw'
DATA_DIR = PROJECT_DIR / 'data'
IMAGES_DIR = RAW_DIR / 'fitz_selected'
for p in (RAW_DIR, IMAGES_DIR):
    p.mkdir(parents=True, exist_ok=True)
print('Using Drive:', RAW_DIR)
```

(Code-comment so the cell doesn't error outside Colab.)
"""))

CELLS.append(code("""
# from google.colab import drive
# drive.mount('/content/drive')
# PROJECT_DIR = Path('/content/drive/MyDrive/DermAssist')
# RAW_DIR = PROJECT_DIR / 'data' / 'raw'
# DATA_DIR = PROJECT_DIR / 'data'
# IMAGES_DIR = RAW_DIR / 'fitz_selected'
# for p in (RAW_DIR, IMAGES_DIR):
#     p.mkdir(parents=True, exist_ok=True)
# print('Using Drive:', RAW_DIR)
"""))

CELLS.append(md("""
## Cell 3 — Load Qwen2.5-VL-7B-Instruct-AWQ

The HF model id `Qwen/Qwen2.5-VL-7B-Instruct-AWQ` is the AWQ INT4
quantized variant — should fit in ~6 GB VRAM with room for KV cache
on T4 (16 GB total). If that exact id 404s on HF, the alternatives
to try (in order) are:

- `Qwen/Qwen2.5-VL-7B-Instruct` (full FP16; needs L4/A100, NOT T4)
- A community AWQ port (search HF for `Qwen2.5-VL-7B AWQ`)

vLLM auto-detects vision support from the model config.
"""))

CELLS.append(code("""
from vllm import LLM, SamplingParams

QWEN_MODEL = 'Qwen/Qwen2.5-VL-7B-Instruct-AWQ'

llm = LLM(
    model=QWEN_MODEL,
    quantization='awq',
    dtype='float16',
    max_model_len=4096,
    gpu_memory_utilization=0.85,
    trust_remote_code=True,
    seed=42,
)
print(f'✓ Loaded {QWEN_MODEL}')
"""))

CELLS.append(md("""
## Cell 4 — Constants + condition mapping

The 8 in-scope conditions and their Vietnamese names. Same taxonomy
as TIP-001 / TIP-002. `ENABLE_SCIN_FALLBACK` is the one toggle for
Chủ thầu — see the coverage caveat at the top of this notebook.
"""))

CELLS.append(code("""
CONDITIONS = [
    'atopic_dermatitis', 'fungal_infection', 'herpes_zoster', 'acne',
    'contact_dermatitis', 'eczema', 'psoriasis', 'scabies',
]

CONDITION_VN = {
    'atopic_dermatitis':  'Viêm da cơ địa',
    'fungal_infection':   'Nấm da',
    'herpes_zoster':      'Zona thần kinh',
    'acne':               'Mụn trứng cá',
    'contact_dermatitis': 'Viêm da tiếp xúc & Mề đay',
    'eczema':             'Chàm',
    'psoriasis':          'Vảy nến',
    'scabies':            'Bệnh ghẻ',
}

# Same alias map as TIP-001 / TIP-002 — single source of truth duplicated
# here for notebook self-containment.
IN_SCOPE_CONDITIONS = {
    'atopic_dermatitis':  ['atopic dermatitis', 'atopic-dermatitis', 'eczema atopic',
                           'atopic'],
    'fungal_infection':   ['tinea', 'tinea corporis', 'tinea pedis', 'tinea cruris',
                           'onychomycosis', 'fungal infection', 'candidiasis',
                           'dermatophytosis', 'dermatophyte', 'ringworm'],
    'herpes_zoster':      ['herpes zoster', 'shingles', 'zoster',
                           'varicella zoster'],
    'acne':               ['acne', 'acne vulgaris'],
    'contact_dermatitis': ['contact dermatitis', 'allergic contact dermatitis',
                           'irritant contact dermatitis', 'urticaria'],
    'eczema':             ['eczema', 'dyshidrotic eczema', 'nummular eczema'],
    'psoriasis':          ['psoriasis', 'psoriasis vulgaris', 'guttate psoriasis'],
    'scabies':            ['scabies'],
}
SPECIFICITY_ORDER = [
    'atopic_dermatitis', 'herpes_zoster', 'fungal_infection',
    'contact_dermatitis', 'psoriasis', 'scabies', 'acne', 'eczema',
]
assert set(SPECIFICITY_ORDER) == set(IN_SCOPE_CONDITIONS.keys())

def map_label(label_str: str) -> str | None:
    if not label_str:
        return None
    s = label_str.lower().strip()
    for key in SPECIFICITY_ORDER:
        for alias in IN_SCOPE_CONDITIONS[key]:
            if alias in s:
                return key
    return None

# Selection knobs
N_PER_CONDITION = 5
N_CANDIDATES = 30           # try up to this many per condition; take first 5 OK
DOWNLOAD_TIMEOUT = 12       # seconds per image
MIN_IMAGE_BYTES = 10_000    # reject tiny / placeholder images

# Toggle: when True, fall back to SCIN GCS images for conditions where
# Fitzpatrick17k yields fewer than 5 successful downloads. Off by default
# to match TIP-003 spec strictly.
ENABLE_SCIN_FALLBACK = False

# Polite seed for selection determinism
SELECTION_SEED = 42

# vLLM determinism settings
QWEN_SAMPLING = SamplingParams(temperature=0.0, max_tokens=200, seed=42)

# Forbidden terms in descriptions (REQ — descriptions must not name diseases)
FORBIDDEN_TERMS = [
    'chẩn đoán', 'bệnh', 'atopic', 'psoriasis', 'viêm da', 'nấm',
    'zona', 'trứng cá', 'eczema', 'chàm', 'vảy nến', 'ghẻ', 'mề đay',
]
"""))

CELLS.append(md("""
## Cell 5 — Image selection from Fitzpatrick17k

Selection algorithm:

1. Read `data/raw/fitzpatrick17k.csv` (download metadata if missing).
2. For each in-scope condition: filter rows whose `label` maps to the
   key. Prefer rows with `qc=1` (quality-checked) and Fitzpatrick
   types 3/4/5 (relevant skin tones for VN).
3. Shuffle deterministically (`SELECTION_SEED`).
4. Try-fetch up to `N_CANDIDATES` per condition; keep first 5 that
   succeed (200 OK + image bytes > `MIN_IMAGE_BYTES` + PIL-decodable).
5. Cache to `IMAGES_DIR / {condition}/{md5}.jpg` so re-runs skip
   already-downloaded files.

**Why so much defense:** Fitzpatrick17k links to dermaamin.com and
atlasdermatologico.com.br; ~90% of dermaamin URLs are dead by 2026.
Atlas is much more reliable (~93% live) but heavily under-represented
for some conditions.
"""))

CELLS.append(code("""
FITZ_URL = 'https://raw.githubusercontent.com/mattgroh/fitzpatrick17k/main/fitzpatrick17k.csv'
FITZ_LOCAL = RAW_DIR / 'fitzpatrick17k.csv'

if not FITZ_LOCAL.exists():
    print('Downloading Fitzpatrick17k metadata...')
    urllib.request.urlretrieve(FITZ_URL, FITZ_LOCAL)
print(f'Fitzpatrick17k metadata: {FITZ_LOCAL.stat().st_size:,} bytes')


def candidates_for(condition_key: str) -> list[dict]:
    \"\"\"Return list of {url, fitz_scale, qc, label} candidates for a condition,
    sorted with priority: III–V skin tones first, then qc=1, then atlas
    domain (more reliable), then random shuffle.\"\"\"
    rng = random.Random(SELECTION_SEED + hash(condition_key) % 10_000)
    rows = []
    with open(FITZ_LOCAL) as f:
        for row in csv.DictReader(f):
            if map_label(row.get('label', '')) == condition_key:
                rows.append({
                    'url': row['url'],
                    'fitz_scale': row.get('fitzpatrick_scale', ''),
                    'qc': row.get('qc', ''),
                    'label': row['label'],
                })
    # Stable sort with priority key
    def priority(r):
        atlas = 'atlas' in r['url'].lower()  # atlas more reliable
        in_band = r['fitz_scale'] in ('3', '4', '5')
        # Lower numbers = higher priority
        return (
            0 if in_band else 1,
            0 if atlas else 1,
            0 if str(r.get('qc')).strip() == '1' else 1,
            rng.random(),
        )
    rows.sort(key=priority)
    return rows


def fetch_image(url: str, timeout: int = DOWNLOAD_TIMEOUT) -> bytes | None:
    \"\"\"GET an image with browser-ish UA. Returns bytes or None on failure.\"\"\"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # some derma sites have stale certs
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            data = resp.read()
            if len(data) < MIN_IMAGE_BYTES:
                return None
            return data
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return None


def select_images_for(condition_key: str, n: int = N_PER_CONDITION) -> list[dict]:
    \"\"\"Try up to N_CANDIDATES URLs; keep first n that fetch + decode.

    Returns list of {path: Path, fitz_scale: str, source_url: str,
    label: str, source_dataset: str}.
    \"\"\"
    out_dir = IMAGES_DIR / condition_key
    out_dir.mkdir(parents=True, exist_ok=True)

    cands = candidates_for(condition_key)[:N_CANDIDATES]
    print(f'\\n{condition_key}: {len(cands)} candidates (need {n})')

    kept: list[dict] = []
    for c in cands:
        if len(kept) >= n:
            break
        # Idempotent cache
        h = hashlib.md5(c['url'].encode()).hexdigest()[:16]
        out_path = out_dir / f'{h}.jpg'
        if not out_path.exists():
            data = fetch_image(c['url'])
            if data is None:
                continue
            try:
                img = Image.open(BytesIO(data)).convert('RGB')
                img.save(out_path, format='JPEG', quality=85)
            except Exception:
                continue
            time.sleep(0.5)  # polite
        try:
            with Image.open(out_path) as im:
                im.verify()
        except Exception:
            out_path.unlink(missing_ok=True)
            continue
        kept.append({
            'path': out_path,
            'fitz_scale': c['fitz_scale'],
            'source_url': c['url'],
            'label': c['label'],
            'source_dataset': 'Fitzpatrick17k',
        })
    print(f'  → {len(kept)}/{n} successful')
    return kept


def select_scin_fallback(condition_key: str, n: int) -> list[dict]:
    \"\"\"Fallback for conditions Fitzpatrick17k lacks.

    SCIN labels CSV has `dermatologist_skin_condition_on_label_name` (a
    list-string of conditions) and `case_id`. Image paths live in
    `scin_cases.csv` under `image_1_path` / `image_2_path` / `image_3_path`,
    pointing at GCS `gs://dx-scin-public-data/dataset/images/...`.

    Public HTTP equivalent: https://storage.googleapis.com/dx-scin-public-data/dataset/images/<case_id>_0.png
    (verify schema if it changed since TIP-001A).
    \"\"\"
    import ast
    SCIN_LABELS = RAW_DIR / 'scin_labels.csv'
    SCIN_CASES = RAW_DIR / 'scin_cases.csv'
    if not SCIN_LABELS.exists():
        urllib.request.urlretrieve(
            'https://storage.googleapis.com/dx-scin-public-data/dataset/scin_labels.csv',
            SCIN_LABELS,
        )
    if not SCIN_CASES.exists():
        urllib.request.urlretrieve(
            'https://storage.googleapis.com/dx-scin-public-data/dataset/scin_cases.csv',
            SCIN_CASES,
        )

    # Build case_id → image_paths
    image_paths: dict[str, list[str]] = {}
    with open(SCIN_CASES) as f:
        for row in csv.DictReader(f):
            paths = [row.get(c) for c in ('image_1_path', 'image_2_path', 'image_3_path')
                     if row.get(c)]
            if paths:
                image_paths[row['case_id']] = paths

    # Pick cases whose primary label maps to condition_key
    rng = random.Random(SELECTION_SEED + hash(f'scin_{condition_key}') % 10_000)
    matched = []
    with open(SCIN_LABELS) as f:
        for row in csv.DictReader(f):
            try:
                lbls = ast.literal_eval(row.get('dermatologist_skin_condition_on_label_name', '[]'))
            except (ValueError, SyntaxError):
                continue
            if not isinstance(lbls, list) or not lbls:
                continue
            if map_label(str(lbls[0])) == condition_key:
                cid = row['case_id']
                if cid in image_paths:
                    matched.append((cid, image_paths[cid][0]))
    rng.shuffle(matched)

    out_dir = IMAGES_DIR / condition_key
    out_dir.mkdir(parents=True, exist_ok=True)
    SCIN_BASE = 'https://storage.googleapis.com/dx-scin-public-data/'
    kept = []
    for cid, gcs_path in matched[:N_CANDIDATES]:
        if len(kept) >= n:
            break
        # gs://dx-scin-public-data/dataset/images/foo.jpg → https://...
        if gcs_path.startswith('dataset/'):
            url = SCIN_BASE + gcs_path
        else:
            url = SCIN_BASE + 'dataset/' + gcs_path.lstrip('/')
        h = hashlib.md5(url.encode()).hexdigest()[:16]
        out_path = out_dir / f'scin_{h}.jpg'
        if not out_path.exists():
            data = fetch_image(url)
            if data is None:
                continue
            try:
                Image.open(BytesIO(data)).convert('RGB').save(
                    out_path, format='JPEG', quality=85)
            except Exception:
                continue
            time.sleep(0.5)
        kept.append({
            'path': out_path,
            'fitz_scale': '',  # SCIN uses Monk skin tones, not Fitzpatrick
            'source_url': url,
            'label': f'SCIN case {cid}',
            'source_dataset': 'SCIN',
        })
    print(f'  → SCIN fallback: {len(kept)}/{n}')
    return kept


selected: dict[str, list[dict]] = {}
for key in CONDITIONS:
    selected[key] = select_images_for(key)
    if ENABLE_SCIN_FALLBACK and len(selected[key]) < N_PER_CONDITION:
        need = N_PER_CONDITION - len(selected[key])
        selected[key].extend(select_scin_fallback(key, need))

print('\\n=== Selection summary ===')
for k in CONDITIONS:
    by_src = Counter(s['source_dataset'] for s in selected[k])
    print(f'  {k:25s} {len(selected[k])}/{N_PER_CONDITION}  ({dict(by_src)})')
"""))

CELLS.append(md("""
## Cell 6 — Vietnamese describe prompt + sampling params

Deterministic settings: `temperature=0.0`, `seed=42`. The prompt
explicitly forbids diagnostic terms — descriptions must be
observational only. The `validation` step in Cell 8 catches any
leakage.
"""))

CELLS.append(code("""
DESCRIBE_PROMPT_VI = \"\"\"Bạn là người hỗ trợ mô tả ảnh, KHÔNG phải bác sĩ.

Mô tả khách quan các đặc điểm hình ảnh bạn nhìn thấy trên ảnh tổn thương da:
- Màu sắc tổn thương
- Hình dạng và kích thước
- Bề mặt (vảy, mụn nước, loét, phẳng, gồ ghề...)
- Ranh giới với da lành (rõ hay mờ)
- Phân bố (tập trung, rải rác, đối xứng)

QUAN TRỌNG:
- CHỈ mô tả những gì thực sự nhìn thấy
- KHÔNG chẩn đoán
- KHÔNG đề cập tên bệnh
- Trả lời bằng tiếng Việt, 3-4 câu, ngắn gọn\"\"\"

PROMPT_VERSION = 'describe-v1.0'
"""))

CELLS.append(md("""
## Cell 7 — Generate descriptions

vLLM's `llm.chat(...)` API accepts vision messages with PIL images.
The exact message shape for Qwen2.5-VL through vLLM is:

```python
[{
  'role': 'user',
  'content': [
    {'type': 'image', 'image': pil_image},
    {'type': 'text',  'text': prompt},
  ],
}]
```

If the installed vLLM version uses a different shape (e.g.,
`{'image_url': {'url': ...}}` for OpenAI-compatible APIs), adapt the
`describe_image()` body and document in the Completion Report.
"""))

CELLS.append(code("""
def describe_image(image: Image.Image) -> str:
    messages = [{
        'role': 'user',
        'content': [
            {'type': 'image', 'image': image},
            {'type': 'text', 'text': DESCRIBE_PROMPT_VI},
        ],
    }]
    output = llm.chat(messages, sampling_params=QWEN_SAMPLING)
    return output[0].outputs[0].text.strip()


visual_db: dict[str, dict] = {}
peak_vram_gb = None

# Try to record peak VRAM usage
try:
    import torch
    torch.cuda.reset_peak_memory_stats()
except Exception:
    torch = None

for key in CONDITIONS:
    descriptions = []
    for i, sel in enumerate(selected[key]):
        with Image.open(sel['path']).convert('RGB') as img:
            desc = describe_image(img)
        descriptions.append({
            'image_index': i,
            'fitzpatrick_type': sel['fitz_scale'] or None,
            'source_dataset': sel['source_dataset'],
            'source_url': sel['source_url'],
            'description': desc,
        })
    visual_db[key] = {
        'name_vi': CONDITION_VN[key],
        'name_en': key.replace('_', ' ').title(),
        'n_descriptions': len(descriptions),
        'descriptions': descriptions,
    }
    print(f'✓ {CONDITION_VN[key]:30s} {len(descriptions)} descriptions')

if torch is not None and torch.cuda.is_available():
    peak_vram_gb = round(torch.cuda.max_memory_allocated() / 1024**3, 2)
    print(f'\\nPeak VRAM during inference: {peak_vram_gb} GB')
"""))

CELLS.append(md("""
## Cell 8 — Validate (forbidden terms check)

Per TIP-003 AC: descriptions must NOT mention diagnostic terms.
≤ 2 violations is acceptable; > 2 fails the AC and the Completion
Report must explain.
"""))

CELLS.append(code("""
flagged: list[dict] = []
for key, data in visual_db.items():
    for d in data['descriptions']:
        text_lower = d['description'].lower()
        hits = [term for term in FORBIDDEN_TERMS if term in text_lower]
        if hits:
            flagged.append({
                'key': key,
                'image_index': d['image_index'],
                'forbidden_hits': hits,
                'description': d['description'],
            })

if flagged:
    print(f'⚠ {len(flagged)} descriptions hit FORBIDDEN_TERMS — review:')
    for f in flagged[:10]:
        print(f'  [{f[\"key\"]}/{f[\"image_index\"]}] hits={f[\"forbidden_hits\"]}: '
              f'{f[\"description\"][:100]}...')
else:
    print('✓ No forbidden terms detected')
"""))

CELLS.append(md("""
## Cell 9 — Write `data/visual_descriptions.json`

Schema matches TIP-003 spec exactly:

```
generated_at, model, model_settings, prompt_version,
source_dataset, source_dataset_license, n_conditions,
n_descriptions_per_condition, conditions, validation
```

`peak_vram_gb` and a per-source-dataset breakdown are added under
`run_info` for the Completion Report; they're additive to the spec
schema (do not remove any required field).
"""))

CELLS.append(code("""
out = {
    'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'model': QWEN_MODEL,
    'model_settings': {
        'temperature': QWEN_SAMPLING.temperature,
        'seed': QWEN_SAMPLING.seed,
        'max_tokens': QWEN_SAMPLING.max_tokens,
    },
    'prompt_version': PROMPT_VERSION,
    'source_dataset': 'Fitzpatrick17k' + (
        ' (+SCIN fallback)' if ENABLE_SCIN_FALLBACK else ''
    ),
    'source_dataset_license': (
        'CC BY-NC-SA 4.0' + (' / CC BY 4.0' if ENABLE_SCIN_FALLBACK else '')
    ),
    'n_conditions': len(CONDITIONS),
    'n_descriptions_per_condition': N_PER_CONDITION,
    'conditions': visual_db,
    'validation': {
        'diagnostic_term_violations': len(flagged),
        'flagged_items': flagged,
    },
    'run_info': {
        'peak_vram_gb': peak_vram_gb,
        'scin_fallback_enabled': ENABLE_SCIN_FALLBACK,
        'per_condition_source_breakdown': {
            k: dict(Counter(s['source_dataset'] for s in selected[k]))
            for k in CONDITIONS
        },
    },
}

OUT_PATH = DATA_DIR / 'visual_descriptions.json'
OUT_PATH.write_text(
    json.dumps(out, ensure_ascii=False, indent=2),
    encoding='utf-8',
)
print(f'✓ Wrote {OUT_PATH}: {OUT_PATH.stat().st_size:,} bytes')

print()
print('=' * 60)
print('TIP-003 — visual descriptions summary')
print('=' * 60)
for k in CONDITIONS:
    n = visual_db[k]['n_descriptions']
    flag = ' ⚠ < 5' if n < N_PER_CONDITION else ''
    print(f'  {k:25s} {n}/{N_PER_CONDITION}{flag}')
print()
print(f'Diagnostic term violations: {len(flagged)} '
      f'(AC: ≤ 2 with explanation)')
print(f'Peak VRAM: {peak_vram_gb} GB '
      f'(AC: < 13 GB on T4)')
"""))

CELLS.append(md("""
## Cell 10 — Done

`data/visual_descriptions.json` is the committed artifact. Raw
images in `data/raw/fitz_selected/` are gitignored (license
attribution + non-redistribution).

**Determinism check (re-run produces identical output):**
re-run this notebook end-to-end. Confirm `visual_descriptions.json`
is byte-identical (modulo `generated_at`). If descriptions differ,
something else is non-deterministic — investigate before committing.

**Next:** TIP-005 will load `visual_descriptions.json` via
`backend/prompts/visual_context.py` (stub committed alongside this
notebook) and inject into the system prompt's `{visual_context}`
slot.
"""))

# ---------------------------------------------------------------------------
NB['cells'] = CELLS
NB['metadata'] = {
    'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
    'language_info': {'name': 'python', 'version': '3.11'},
}

OUT = 'notebooks/03_fewshot_gen.ipynb'
with open(OUT, 'w', encoding='utf-8') as f:
    nbf.write(NB, f)

print(f'Wrote {OUT} — {len(CELLS)} cells')
