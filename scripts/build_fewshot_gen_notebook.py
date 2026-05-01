"""
Build notebooks/03_fewshot_gen.ipynb (TIP-003 → TIP-003A → TIP-003B).

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

**Source datasets (per-condition policy, see Cell 4):**
- Fitzpatrick17k (CC BY-NC-SA 4.0) — acne, contact_dermatitis,
  psoriasis, scabies, eczema (fallback)
- SCIN (CC BY 4.0) — eczema (preferred), fungal_infection, herpes_zoster
- DermNet NZ (CC BY-NC-ND, session-only, never persisted to disk) —
  atopic_dermatitis

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

## Coverage policy

The 8 in-scope conditions are split across three datasets via the
`SOURCE_POLICY` dict in Cell 4 (TIP-003A). Three conditions
(`atopic_dermatitis`, `fungal_infection`, `herpes_zoster`) have zero
images in Fitzpatrick17k and are filled from SCIN or DermNet NZ
automatically — no manual flag flip required. A coverage circuit-breaker
in the main loop aborts the run if any condition ends with fewer than
3 successful descriptions.
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

ensure('vllm', 'pillow', 'requests', 'pandas')

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
from google.colab import drive
drive.mount('/content/drive')
PROJECT_DIR = Path('/content/drive/MyDrive/DermAssist')
RAW_DIR = PROJECT_DIR / 'data' / 'raw'
DATA_DIR = PROJECT_DIR / 'data'
IMAGES_DIR = RAW_DIR / 'fitz_selected'
for p in (RAW_DIR, IMAGES_DIR):
    p.mkdir(parents=True, exist_ok=True)
print('Using Drive:', RAW_DIR)
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
import os
import sys

# Fix 1: Force legacy V1 engine để tránh suppress_stdout bug trong Jupyter
os.environ[\"VLLM_USE_V1\"] = \"0\"

# Fix 2: Monkey-patch fileno() cho trường hợp vLLM version khác vẫn gọi fileno
_real_stdout = sys.stdout

class _JupyterStdoutPatch:
    def __getattr__(self, name):
        return getattr(_real_stdout, name)
    def fileno(self):
        return 1  # fake fd, tương đương stdout

sys.stdout = _JupyterStdoutPatch()

# --- Load model ---
from vllm import LLM, SamplingParams

QWEN_MODEL = 'Qwen/Qwen2.5-VL-7B-Instruct-AWQ'

try:
    llm = LLM(
        model=QWEN_MODEL,
        quantization='awq_marlin',   # nhanh hơn ~20-30% so với 'awq' trên T4
        dtype='float16',
        max_model_len=4096,
        gpu_memory_utilization=0.85,
        trust_remote_code=True,
        seed=42,
    )
    print(f'✓ Loaded {QWEN_MODEL}')
except Exception as e:
    # Fallback: thử lại với quantization='awq' nếu awq_marlin không được hỗ trợ
    print(f'awq_marlin failed ({e}), retrying with awq...')
    llm = LLM(
        model=QWEN_MODEL,
        quantization='awq',
        dtype='float16',
        max_model_len=4096,
        gpu_memory_utilization=0.85,
        trust_remote_code=True,
        seed=42,
    )
    print(f'✓ Loaded {QWEN_MODEL} (awq fallback)')
finally:
    sys.stdout = _real_stdout  # restore stdout sau khi load xong
"""))

CELLS.append(md("""
## Cell 4 — Constants, condition mapping, and source policy

The 8 in-scope conditions, their Vietnamese names, and the per-condition
`SOURCE_POLICY` dict (TIP-003A). Sanity check at the bottom verifies
every in-scope condition has at least one source.
"""))

CELLS.append(code("""
print(DATA_DIR)
"""))

CELLS.append(code("""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

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

IN_SCOPE_CONDITIONS = {
    'atopic_dermatitis':  ['atopic dermatitis', 'atopic-dermatitis', 'eczema atopic', 'atopic'],
    'fungal_infection':   ['tinea', 'tinea corporis', 'tinea pedis', 'tinea cruris',
                           'onychomycosis', 'fungal infection', 'candidiasis',
                           'dermatophytosis', 'dermatophyte', 'ringworm'],
    'herpes_zoster':      ['herpes zoster', 'shingles', 'zoster', 'varicella zoster'],
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
N_PER_CONDITION    = 5
N_CANDIDATES       = 30
DOWNLOAD_TIMEOUT   = 12
MIN_IMAGE_BYTES    = 10_000
SELECTION_SEED     = 42

# Per-condition source policy
SOURCE_POLICY = {
    'acne':               ['fitzpatrick17k'],
    'contact_dermatitis': ['fitzpatrick17k'],
    'psoriasis':          ['fitzpatrick17k'],
    'scabies':            ['fitzpatrick17k'],
    'eczema':             ['scin', 'fitzpatrick17k'],
    'fungal_infection':   ['scin'],
    'herpes_zoster':      ['scin'],
    'atopic_dermatitis':  ['dermnet_session_only'],
}

# Sanity check: every in-scope condition has at least one source
scope_path = DATA_DIR / 'condition_scope.json'
audit_path = DATA_DIR / 'dataset_audit.json'
if not scope_path.exists():
    raise FileNotFoundError('data/condition_scope.json missing')
if not audit_path.exists():
    raise FileNotFoundError('data/dataset_audit.json missing')

scope = json.loads(scope_path.read_text())
for cond in scope['in_scope']:
    assert cond in SOURCE_POLICY, f'Missing source policy for: {cond}'
print('✓ Source policy covers all in-scope conditions')

# vLLM sampling — deterministic
QWEN_SAMPLING = SamplingParams(temperature=0.0, max_tokens=200, seed=42)

# Forbidden diagnostic terms (descriptions must be observational only)
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

CELLS.append(code('''
import csv
import random
import time
import urllib.request
from io import BytesIO

import pandas as pd
import requests
from PIL import Image

FITZ_URL   = 'https://raw.githubusercontent.com/mattgroh/fitzpatrick17k/main/fitzpatrick17k.csv'
FITZ_LOCAL = RAW_DIR / 'fitzpatrick17k.csv'

if not FITZ_LOCAL.exists():
    print('Downloading Fitzpatrick17k metadata...')
    urllib.request.urlretrieve(FITZ_URL, FITZ_LOCAL)
print(f'Fitzpatrick17k metadata: {FITZ_LOCAL.stat().st_size:,} bytes')


def _stable_seed(condition_key: str) -> int:
    """Deterministic per-condition seed — không dùng hash() vì PYTHONHASHSEED random."""
    return SELECTION_SEED + CONDITIONS.index(condition_key)


def fitz_candidates_for(condition_key: str, n: int = 30) -> list[dict]:
    rng = random.Random(_stable_seed(condition_key))
    rows = []
    with open(FITZ_LOCAL) as f:
        for row in csv.DictReader(f):
            if map_label(row.get('label', '')) == condition_key:
                rows.append({
                    'url':             row['url'],
                    'fitzpatrick_type': row.get('fitzpatrick_scale', ''),
                    'qc':              row.get('qc', ''),
                    'label':           row['label'],
                    'source_dataset':  'Fitzpatrick17k',
                    'license':         'CC BY-NC-SA 4.0',
                    'case_id':         None,
                    'monk_tone':       None,
                })

    def priority(r):
        atlas   = 'atlas' in r['url'].lower()
        in_band = r['fitzpatrick_type'] in ('3', '4', '5')
        return (
            0 if in_band else 1,
            0 if atlas   else 1,
            0 if str(r.get('qc', '')).strip() == '1' else 1,
            rng.random(),
        )

    rows.sort(key=priority)
    return rows[:n]


SCIN_CASES_URL  = 'https://storage.googleapis.com/dx-scin-public-data/dataset/scin_cases.csv'
SCIN_LABELS_URL = 'https://storage.googleapis.com/dx-scin-public-data/dataset/scin_labels.csv'
SCIN_IMAGE_BASE = 'https://storage.googleapis.com/dx-scin-public-data/dataset/images/'


def load_scin_metadata():
    labels_cache = RAW_DIR / 'scin_labels.csv'
    cases_cache  = RAW_DIR / 'scin_cases.csv'
    labels = pd.read_csv(labels_cache) if labels_cache.exists() else pd.read_csv(SCIN_LABELS_URL)
    if not labels_cache.exists():
        labels.to_csv(labels_cache, index=False)
    cases  = pd.read_csv(cases_cache)  if cases_cache.exists()  else pd.read_csv(SCIN_CASES_URL)
    if not cases_cache.exists():
        cases.to_csv(cases_cache, index=False)
    return labels, cases


def scin_candidates_for(condition_key: str, n: int = 30) -> list[dict]:
    labels, cases = load_scin_metadata()
    img_col = 'image_1_path' if 'image_1_path' in cases.columns else 'image_path'

    labels = labels.copy()
    labels['mapped_key'] = labels['dermatologist_skin_condition_on_label_name'].apply(map_label)
    matched = labels[labels['mapped_key'] == condition_key]
    joined  = matched.merge(cases, on='case_id', how='inner')

    if 'monk_skin_tone_label_us' in joined.columns:
        joined = joined.copy()
        joined['_priority'] = joined['monk_skin_tone_label_us'].apply(
            lambda x: 0 if isinstance(x, str) and any(
                f'Monk {t}' in x for t in ['4', '5', '6']
            ) else 1
        )
        joined = joined.sort_values('_priority')

    candidates = []
    for _, row in joined.head(n).iterrows():
        img_path = row.get(img_col)
        if not isinstance(img_path, str):
            continue
        url = SCIN_IMAGE_BASE + img_path.split('/')[-1]
        candidates.append({
            'url':            url,
            'source_dataset': 'SCIN',
            'license':        'CC BY 4.0',
            'case_id':        row['case_id'],
            'monk_tone':      row.get('monk_skin_tone_label_us'),
            'fitzpatrick_type': None,
        })
    return candidates


def dermnet_candidates_for(condition_key: str, n: int = 30) -> list[dict]:
    # FIX: dùng DATA_DIR thay vì hardcoded relative path
    audit = json.loads((DATA_DIR / 'dataset_audit.json').read_text())
    urls  = audit['datasets']['dermnet_nz']['image_urls_per_condition'].get(condition_key, [])[:n]
    return [
        {
            'url':            u,
            'source_dataset': 'DermNet NZ',
            'license':        'CC BY-NC-ND (session-only)',
            'case_id':        None,
            'monk_tone':      None,
            'fitzpatrick_type': None,
        }
        for u in urls
    ]


def candidates_for(condition_key: str, n: int = 30) -> list[dict]:
    candidates = []
    remaining  = n
    for source in SOURCE_POLICY[condition_key]:
        if remaining <= 0:
            break
        if source == 'fitzpatrick17k':
            new = fitz_candidates_for(condition_key, remaining)
        elif source == 'scin':
            new = scin_candidates_for(condition_key, remaining)
        elif source == 'dermnet_session_only':
            new = dermnet_candidates_for(condition_key, remaining)
        else:
            raise ValueError(f'Unknown source: {source}')
        candidates.extend(new)
        remaining -= len(new)
    return candidates[:n]


HTTP_HEADERS = {'User-Agent': USER_AGENT}


def _cache_key(url: str) -> str:
    """Deterministic cache filename — dùng md5 thay vì hash() để tránh PYTHONHASHSEED."""
    return hashlib.md5(url.encode()).hexdigest()[:12]


def fetch_image(candidate: dict) -> Image.Image | None:
    url = candidate['url']
    try:
        if candidate['source_dataset'] == 'DermNet NZ':
            # Session-only: không cache xuống disk (CC BY-NC-ND)
            r = requests.get(url, headers=HTTP_HEADERS, timeout=DOWNLOAD_TIMEOUT)
            r.raise_for_status()
            if len(r.content) < MIN_IMAGE_BYTES:
                return None
            return Image.open(BytesIO(r.content)).convert('RGB')
        else:
            src_slug  = candidate['source_dataset'].lower().replace(' ', '_')
            cache_dir = RAW_DIR / f'{src_slug}_selected'
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path = cache_dir / f'{_cache_key(url)}.jpg'
            if cache_path.exists():
                return Image.open(cache_path).convert('RGB')
            r = requests.get(url, headers=HTTP_HEADERS, timeout=DOWNLOAD_TIMEOUT)
            r.raise_for_status()
            if len(r.content) < MIN_IMAGE_BYTES:
                return None
            img = Image.open(BytesIO(r.content)).convert('RGB')
            img.save(cache_path, 'JPEG', quality=92)
            time.sleep(0.5)
            return img
    except Exception as e:
        print(f'  ⚠ fetch failed: {url[:70]}... — {e}')
        return None


# --- Main selection loop ---
selected:      dict[str, list[dict]]       = {}
fetched_images: dict[str, list[Image.Image]] = {}

for key in CONDITIONS:
    cands      = candidates_for(key, n=N_CANDIDATES)
    kept_cands = []
    kept_imgs  = []
    print(f'\\n{key}: {len(cands)} candidates')
    for c in cands:
        if len(kept_cands) >= N_PER_CONDITION:
            break
        img = fetch_image(c)
        if img is not None:
            kept_cands.append(c)
            kept_imgs.append(img)
    selected[key]       = kept_cands
    fetched_images[key] = kept_imgs
    print(f'  → {len(kept_cands)}/{N_PER_CONDITION} fetched')

print('\\n=== Selection summary ===')
for k in CONDITIONS:
    by_src = Counter(s['source_dataset'] for s in selected[k])
    print(f'  {k:25s} {len(selected[k])}/{N_PER_CONDITION}  {dict(by_src)}')
'''))

CELLS.append(md("""
## Cell 6 — Vietnamese describe prompt + sampling params

Deterministic settings: `temperature=0.0`, `seed=42`. The prompt
explicitly forbids diagnostic terms — descriptions must be
observational only. The `validation` step in Cell 9 catches any
leakage.
"""))

CELLS.append(code('''
# FIX: thống nhất "3-5 câu" cho đồng bộ với AC spec
DESCRIBE_PROMPT_VI = """Bạn là người hỗ trợ mô tả ảnh, KHÔNG phải bác sĩ.

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
- Trả lời bằng tiếng Việt, 3-5 câu, ngắn gọn"""

PROMPT_VERSION = 'describe-v1.1'
'''))

CELLS.append(md("""
## Cell 6b — Determinism smoke check

Quick check: same image, same prompt, twice — same output. If this
fails, the rest of the run is not deterministic and the JSON should
not be committed. Result is stored in `run_info_extras` so the JSON
write picks it up.
"""))

CELLS.append(code('''
import base64
from io import BytesIO

try:
    import torch
    torch.cuda.reset_peak_memory_stats()
except Exception:
    torch = None

peak_vram_gb    = None
run_info_extras = {}


def _pil_to_base64(img: Image.Image) -> str:
    buf = BytesIO()
    img.save(buf, format='JPEG', quality=92)
    return base64.b64encode(buf.getvalue()).decode('utf-8')


def describe_image(image: Image.Image) -> str:
    # FIX: dùng image_url + base64 thay vì {'type': 'image', 'image': pil}
    b64 = _pil_to_base64(image)
    messages = [{
        'role': 'user',
        'content': [
            {
                'type': 'image_url',
                'image_url': {'url': f'data:image/jpeg;base64,{b64}'},
            },
            {'type': 'text', 'text': DESCRIBE_PROMPT_VI},
        ],
    }]
    output = llm.chat(messages, sampling_params=QWEN_SAMPLING)
    return output[0].outputs[0].text.strip()


# Determinism check
print('Running determinism check...')
first_cond = next(
    (c for c in CONDITIONS if SOURCE_POLICY[c][0] != 'dermnet_session_only'), None
)
if first_cond:
    test_cands = candidates_for(first_cond, n=1)
    test_img   = fetch_image(test_cands[0]) if test_cands else None
    if test_img:
        d1 = describe_image(test_img)
        d2 = describe_image(test_img)
        if d1 == d2:
            print('✓ Determinism confirmed')
            run_info_extras['determinism_check'] = 'pass'
        else:
            print('⚠ Determinism FAILED — outputs differ')
            run_info_extras['determinism_check'] = 'fail'
            run_info_extras['determinism_sample'] = {'run1': d1, 'run2': d2}
    else:
        print('⚠ Could not fetch test image; skipping')
else:
    print('⚠ No non-DermNet condition; skipping determinism check')
'''))

CELLS.append(md("""
## Cell 8 — Generate descriptions

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

CELLS.append(code('''
# Main generation loop
visual_db: dict[str, dict] = {}

for key in CONDITIONS:
    descriptions = []
    for i, (cand, img) in enumerate(zip(selected[key], fetched_images[key])):
        desc = describe_image(img)
        descriptions.append({
            'image_index':      i,
            'source_dataset':   cand['source_dataset'],
            'license':          cand['license'],
            'case_id':          cand.get('case_id'),
            'fitzpatrick_type': cand.get('fitzpatrick_type'),
            'monk_tone':        cand.get('monk_tone'),
            'source_url':       cand['url'],
            'description':      desc,
        })
    visual_db[key] = {
        'name_vi':        CONDITION_VN[key],
        'name_en':        key.replace('_', ' ').title(),
        'n_descriptions': len(descriptions),
        'descriptions':   descriptions,
    }
    print(f'✓ {CONDITION_VN[key]:30s} {len(descriptions)} descriptions')

# Coverage circuit-breaker
MIN_DESCRIPTIONS = 3
failed = [c for c, info in visual_db.items() if info['n_descriptions'] < MIN_DESCRIPTIONS]
if failed:
    raise RuntimeError(
        f'Coverage circuit-breaker tripped — < {MIN_DESCRIPTIONS} descriptions: {failed}. '
        f'Counts: { {c: i["n_descriptions"] for c, i in visual_db.items()} }'
    )
print(f'✓ Coverage check passed: all conditions ≥ {MIN_DESCRIPTIONS} descriptions')

if torch is not None and torch.cuda.is_available():
    peak_vram_gb = round(torch.cuda.max_memory_allocated() / 1024**3, 2)
    print(f'Peak VRAM: {peak_vram_gb} GB')
'''))

CELLS.append(md("""
## Cell 9 — Validate (forbidden terms check)

Per TIP-003 AC: descriptions must NOT mention diagnostic terms.
≤ 2 violations is acceptable; > 2 fails the AC and the Completion
Report must explain.
"""))

CELLS.append(code(r'''
import re


def count_sentences(text: str) -> int:
    """Rough Vietnamese sentence count."""
    parts = re.split(r'[.!?]+(?:\s|$)', text.strip())
    return sum(1 for s in parts if s.strip())


flagged            = []
short_descriptions = []
long_descriptions  = []

for key, data in visual_db.items():
    for d in data['descriptions']:
        desc       = d['description']
        text_lower = desc.lower()

        # Forbidden terms check
        hits = [term for term in FORBIDDEN_TERMS if term in text_lower]
        if hits:
            flagged.append({
                'key':           key,
                'image_index':   d['image_index'],
                'forbidden_hits': hits,
                'description':   desc,
            })

        # FIX: threshold > 5 để đúng với AC "3-5 sentences"
        n = count_sentences(desc)
        if n < 3:
            short_descriptions.append({
                'key': key, 'image_index': d['image_index'],
                'sentences': n, 'description': desc,
            })
        elif n > 5:
            long_descriptions.append({
                'key': key, 'image_index': d['image_index'],
                'sentences': n,
            })

if flagged:
    print(f'⚠ {len(flagged)} descriptions hit FORBIDDEN_TERMS:')
    for f in flagged[:10]:
        print(f'  [{f["key"]}/{f["image_index"]}] hits={f["forbidden_hits"]}: '
              f'{f["description"][:100]}...')
else:
    print('✓ No forbidden terms detected')

if short_descriptions:
    print(f'⚠ {len(short_descriptions)} descriptions < 3 sentences')
if long_descriptions:
    print(f'⚠ {len(long_descriptions)} descriptions > 5 sentences')

print(f'\nValidation summary: {len(flagged)} violation(s) '
      f'(AC: ≤ 2), {len(short_descriptions)} short, {len(long_descriptions)} long')
'''))

CELLS.append(md("""
## Cell 10 — Write `data/visual_descriptions.json`

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

CELLS.append(code('''
from datetime import datetime, timezone

# FIX: tính license từ SOURCE_POLICY thay vì ENABLE_SCIN_FALLBACK deprecated
_LICENSE_MAP = {
    'fitzpatrick17k':     'CC BY-NC-SA 4.0',
    'scin':               'CC BY 4.0',
    'dermnet_session_only': 'CC BY-NC-ND (session-only)',
}
_active_licenses = sorted({
    _LICENSE_MAP[src]
    for sources in SOURCE_POLICY.values()
    for src in sources
})

out = {
    'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'model':         QWEN_MODEL,
    'model_settings': {
        'temperature': QWEN_SAMPLING.temperature,
        'seed':        QWEN_SAMPLING.seed,
        'max_tokens':  QWEN_SAMPLING.max_tokens,
    },
    'prompt_version': PROMPT_VERSION,
    'source_datasets': [
        {'name': 'Fitzpatrick17k', 'license': 'CC BY-NC-SA 4.0'},
        {'name': 'SCIN',           'license': 'CC BY 4.0'},
        {'name': 'DermNet NZ',     'license': 'CC BY-NC-ND (session-only)'},
    ],
    'source_dataset':         'multi-source',
    'source_dataset_license': ' / '.join(_active_licenses),  # FIX: dynamic từ SOURCE_POLICY
    'n_conditions':                  len(CONDITIONS),
    'n_descriptions_per_condition':  N_PER_CONDITION,
    'conditions': visual_db,
    'validation': {
        'diagnostic_term_violations': len(flagged),
        'flagged_items':              flagged,
        'short_descriptions':         short_descriptions,
        'long_descriptions':          long_descriptions,
        'short_count':                len(short_descriptions),
        'long_count':                 len(long_descriptions),
    },
    'run_info': {
        'peak_vram_gb':                  peak_vram_gb,
        'per_condition_source_breakdown': {
            k: dict(Counter(s['source_dataset'] for s in selected[k]))
            for k in CONDITIONS
        },
        **run_info_extras,
    },
}

OUT_PATH = DATA_DIR / 'visual_descriptions.json'
OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'✓ Wrote {OUT_PATH}: {OUT_PATH.stat().st_size:,} bytes')

print()
print('=' * 60)
print('TIP-003 — visual descriptions summary')
print('=' * 60)
for k in CONDITIONS:
    n    = visual_db[k]['n_descriptions']
    flag = ' ⚠ < 5' if n < N_PER_CONDITION else ''
    print(f'  {k:25s} {n}/{N_PER_CONDITION}{flag}')
print()
print(f'Diagnostic term violations : {len(flagged)} (AC: ≤ 2)')
print(f'Short descriptions (< 3 s) : {len(short_descriptions)}')
print(f'Long descriptions  (> 5 s) : {len(long_descriptions)}')
print(f'Peak VRAM                  : {peak_vram_gb} GB (AC: < 13 GB)')
print(f'Active licenses            : {", ".join(_active_licenses)}')
'''))

CELLS.append(md("""
## Cell 11 — Done

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
