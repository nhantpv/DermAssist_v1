"""
Build notebooks/02_ocr_pipeline.ipynb (TIP-002).

Same convention as the TIP-001 builders: assemble a clean, output-cleared
.ipynb so the cell layout is reviewable as Python.

Run:  python scripts/build_ocr_pipeline_notebook.py
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
# 02 — OCR + RAG Corpus Pipeline (TIP-002)

**Source:** Quyết định 4416/QĐ-BYT (Bộ Y Tế, 06/12/2023) —
*Hướng dẫn chẩn đoán và điều trị các bệnh da liễu*.

**This notebook is the GPU-bound step.** Run on **Colab T4** (or any
machine with CUDA + ≥ 6 GB VRAM). The PDF is a 474-page **scan with
no text layer**, so OCR is required.

**Outputs:**

- `data/chunks.json` — list of chunks with `embedding` (multilingual-e5-small,
  384-dim), section titles, page provenance, condition tags. Loaded into
  Postgres `kb_chunks` by `scripts/seed_kb_chunks.py`.

**Pipeline stages:**

1. Download PDF (or upload via `files.upload()`)
2. Detect text layer; OCR fallback via `easyocr` if absent (it is)
3. Section-aware chunking (target 400 tokens, 50-token overlap, max 800)
4. Tag each chunk with relevant condition keys (8 in scope)
5. Embed with `intfloat/multilingual-e5-small` (`passage:` prefix)
6. Write `data/chunks.json`

**Acceptance hooks:**

- ≥ 50 chunks total
- ≥ 1 chunk per in-scope condition (8 of them)
- Each chunk: 200–800 tokens
- Embeddings: exactly 384 dims
- Stable `chunk_id`s of the form `chunk-NNNN`
"""))

CELLS.append(md("""
## Cell 1 — Setup

GPU-side dependencies are pinned light. `easyocr` is the slow install
(~700 MB including the Vietnamese model the first time).
"""))

CELLS.append(code("""
# Colab-friendly install. On a non-Colab machine, run these manually.
import importlib.util, subprocess, sys

def ensure(*pkgs: str) -> None:
    missing = [p for p in pkgs if importlib.util.find_spec(p.split('==')[0].split('[')[0]) is None]
    if missing:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', *missing])

ensure('pymupdf', 'easyocr', 'sentence_transformers', 'tiktoken')

import fitz  # pymupdf
import json, re, hashlib
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone

REPO_ROOT = Path.cwd()
if REPO_ROOT.name == 'notebooks':
    REPO_ROOT = REPO_ROOT.parent
RAW_DIR = REPO_ROOT / 'data' / 'raw'
DATA_DIR = REPO_ROOT / 'data'
RAW_DIR.mkdir(parents=True, exist_ok=True)

print('Repo root:', REPO_ROOT)
print('Raw dir:  ', RAW_DIR, '(gitignored)')
"""))

CELLS.append(md("""
## Cell 2 — Get the PDF

Two options:

- **Auto-download** (run `scripts/download_qd_4416.sh`) — works locally
  and on Colab when `curl` is on PATH.
- **Manual upload** — `from google.colab import files; files.upload()`
  is the Colab-native fallback.

The cell tries auto-download first; falls through to a manual instruction
if it fails.
"""))

CELLS.append(code("""
PDF_PATH = RAW_DIR / 'qd-4416-byt-2023.pdf'

if not PDF_PATH.exists():
    try:
        subprocess.check_call(['bash', str(REPO_ROOT / 'scripts/download_qd_4416.sh')])
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        print(f'Auto-download failed ({e}).')
        print('Upload the PDF manually:')
        print('    from google.colab import files; files.upload()')
        print('    # then move it to', PDF_PATH)
        raise

print(f'PDF: {PDF_PATH} ({PDF_PATH.stat().st_size:,} bytes)')
"""))

CELLS.append(md("""
## Cell 3 — Detect text layer

Government-published PDFs in Vietnam are routinely scans of paper-signed
documents. Detect ahead of time so we only OCR if necessary.
"""))

CELLS.append(code("""
def has_text_layer(pdf_path: Path, sample_pages: int = 5) -> bool:
    doc = fitz.open(pdf_path)
    n = min(sample_pages, len(doc))
    total = sum(len(doc[i].get_text('text').strip()) for i in range(n))
    return total > 200 * n  # > 200 chars/page average

doc = fitz.open(PDF_PATH)
print(f'Pages: {len(doc)}')
print(f'has_text_layer: {has_text_layer(PDF_PATH)}')
"""))

CELLS.append(md("""
## Cell 4 — Fast path: extract text layer

If `has_text_layer` is True we just pull `page.get_text("text")` per
page. (It's not, for QĐ-4416 — but we keep this path for any future
text-layer source.)
"""))

CELLS.append(code("""
def extract_text_layer(pdf_path: Path) -> list[dict]:
    doc = fitz.open(pdf_path)
    return [
        {'page_num': i + 1, 'text': page.get_text('text')}
        for i, page in enumerate(doc)
    ]
"""))

CELLS.append(md("""
## Cell 5 — OCR fallback (easyocr, GPU)

`easyocr.Reader(['vi','en'], gpu=True)` will download model weights on
first use (~500 MB Vietnamese + English). On T4 each page takes 1–3 s;
on CPU expect 10–30 s/page (so a 474-page PDF is impractical CPU-only).

**Cleanup applied to every page:** strip headers, footers, page numbers,
and collapse repeated whitespace (per TIP constraint "DO NOT ship raw OCR
output to the prompt — clean it"). Heuristics:

- Remove standalone numeric lines (page numbers).
- Collapse runs of `\\s+` → single space.
- Drop very short lines (`< 4 chars`) unless they look like
  enumeration bullets (`-`, `1.`, etc.).
"""))

CELLS.append(code("""
HEADER_FOOTER_PATTERNS = [
    re.compile(r'^\\s*\\d+\\s*$'),                    # bare page number
    re.compile(r'^\\s*Trang\\s+\\d+\\s*$', re.I),    # \"Trang N\"
    re.compile(r'BỘ Y TẾ.{0,80}$', re.I),            # \"Bộ Y Tế ...\" running header
    re.compile(r'^\\s*-+\\s*$'),                      # divider
]

def clean_ocr_line(line: str) -> str | None:
    s = line.strip()
    if not s:
        return None
    for pat in HEADER_FOOTER_PATTERNS:
        if pat.search(s):
            return None
    if len(s) < 4 and not re.match(r'^[-\\u2022•]|\\d+[.)]', s):
        return None
    return re.sub(r'\\s+', ' ', s)

def extract_text_ocr(pdf_path: Path, scale: float = 2.0,
                     gpu: bool = True) -> list[dict]:
    import easyocr
    reader = easyocr.Reader(['vi', 'en'], gpu=gpu)
    doc = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc):
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat)
        results = reader.readtext(pix.tobytes('png'), detail=0, paragraph=True)
        cleaned = [c for line in results if (c := clean_ocr_line(line))]
        pages.append({'page_num': i + 1, 'text': '\\n'.join(cleaned)})
        if (i + 1) % 25 == 0:
            print(f'  OCR progress: {i + 1}/{len(doc)} pages')
    return pages
"""))

CELLS.append(md("""
## Cell 6 — Run extraction

Picks fast path if text layer exists; falls back to OCR. Caches the
intermediate result to `data/raw/pages.json` so re-running the chunking
cells doesn't re-OCR.
"""))

CELLS.append(code("""
PAGES_CACHE = RAW_DIR / 'pages.json'

if PAGES_CACHE.exists():
    pages = json.loads(PAGES_CACHE.read_text(encoding='utf-8'))
    print(f'Loaded cached extraction: {len(pages)} pages from {PAGES_CACHE}')
elif has_text_layer(PDF_PATH):
    pages = extract_text_layer(PDF_PATH)
    PAGES_CACHE.write_text(json.dumps(pages, ensure_ascii=False), encoding='utf-8')
    print(f'Text-layer extraction: {len(pages)} pages')
else:
    pages = extract_text_ocr(PDF_PATH, scale=2.0, gpu=True)
    PAGES_CACHE.write_text(json.dumps(pages, ensure_ascii=False), encoding='utf-8')
    print(f'OCR extraction: {len(pages)} pages')

# Show a sample
for p in pages[:2]:
    print(f\"--- page {p['page_num']} ---\")
    print(p['text'][:300])
"""))

CELLS.append(md("""
## Cell 7 — Section-aware chunking

The MOH guideline is structured as a numbered table of contents — every
disease chapter starts with a heading like `2.3. Viêm da cơ địa` or
`Chương 5. Bệnh nhiễm trùng da`. We detect those headings and accumulate
lines under each section.

If a section is too long for `target_tokens=400`, split it with
`overlap_tokens=50` so chunks straddle section boundaries.

We use **tiktoken `cl100k_base`** as a token counter — not because the
embedding model uses it, but because it's a stable approximation that
correlates well with sentence-transformer token counts and is cheap to
compute. The TIP requires per-chunk `token_count`.
"""))

CELLS.append(code("""
import tiktoken
TOK = tiktoken.get_encoding('cl100k_base')

def n_tokens(text: str) -> int:
    return len(TOK.encode(text))

# 8 conditions with their VN aliases for tagging (Blueprint §1.1)
CONDITION_ALIASES = {
    'atopic_dermatitis':  ['viêm da cơ địa', 'atopic dermatitis'],
    'fungal_infection':   ['nấm da', 'lang ben', 'hắc lào', 'tinea',
                           'nấm móng', 'candida', 'dermatophyte'],
    'herpes_zoster':      ['zona', 'herpes zoster', 'giời leo',
                           'thần kinh sau zona'],
    'acne':               ['mụn trứng cá', 'trứng cá', 'acne'],
    'contact_dermatitis': ['viêm da tiếp xúc', 'mề đay', 'urticaria',
                           'dị ứng da'],
    'eczema':             ['chàm', 'eczema'],
    'psoriasis':          ['vảy nến', 'psoriasis'],
    'scabies':            ['ghẻ', 'bệnh ghẻ', 'scabies', 'sarcoptes'],
}

# Heading detector: numbered headings (e.g. \"2.3. Viêm da cơ địa\")
# OR \"Chương N. Title\". Title must start with an uppercase Vietnamese
# letter (after the number) and be < 200 chars.
HEADING_NUMBERED = re.compile(
    r'^\\s*\\d+(\\.\\d+)*\\.?\\s+[A-ZÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ]'
)
HEADING_CHAPTER = re.compile(r'^\\s*(Chương|CHƯƠNG)\\s+[IVX0-9]+\\.?\\s+', re.I)

def detect_section_header(line: str) -> str | None:
    s = line.strip()
    if not s or len(s) > 200:
        return None
    if HEADING_NUMBERED.match(s) or HEADING_CHAPTER.match(s):
        return s
    return None

def split_long_section(text: str, *, target: int = 400, overlap: int = 50,
                       max_t: int = 800) -> list[str]:
    \"\"\"Split a long section into overlapping windows of `target` tokens.\"\"\"
    tokens = TOK.encode(text)
    if len(tokens) <= max_t:
        return [text]
    out = []
    step = max(1, target - overlap)
    for start in range(0, len(tokens), step):
        end = min(start + target, len(tokens))
        out.append(TOK.decode(tokens[start:end]))
        if end >= len(tokens):
            break
    return out

def chunk_by_section(pages: list[dict],
                     *, target: int = 400, overlap: int = 50,
                     max_t: int = 800, min_t: int = 200) -> list[dict]:
    sections: list[dict] = []  # {section_title, lines:[(page_num, line)]}
    current = {'section_title': '(preamble)', 'lines': []}

    for p in pages:
        for line in p['text'].splitlines():
            hd = detect_section_header(line)
            if hd is not None:
                if current['lines']:
                    sections.append(current)
                current = {'section_title': hd, 'lines': []}
            else:
                if line.strip():
                    current['lines'].append((p['page_num'], line.rstrip()))
    if current['lines']:
        sections.append(current)

    chunks: list[dict] = []
    for sec in sections:
        text = '\\n'.join(line for _, line in sec['lines']).strip()
        if not text:
            continue
        pages_seen = sorted({pn for pn, _ in sec['lines']})
        for piece in split_long_section(text, target=target,
                                        overlap=overlap, max_t=max_t):
            tc = n_tokens(piece)
            # Drop chunks below min_t — too small to be useful as RAG context.
            if tc < min_t:
                continue
            chunks.append({
                'section_title': sec['section_title'],
                'text': piece,
                'token_count': tc,
                'source_pages': pages_seen,
            })
    return chunks

raw_chunks = chunk_by_section(pages)
print(f'Raw chunks: {len(raw_chunks)}')
print(f'Token-count percentiles:')
counts = sorted(c['token_count'] for c in raw_chunks)
for q, name in [(0, 'min'), (len(counts)//4, 'p25'), (len(counts)//2, 'p50'),
                (3*len(counts)//4, 'p75'), (-1, 'max')]:
    if counts:
        print(f'  {name}: {counts[q]}')
"""))

CELLS.append(md("""
## Cell 8 — Tag and filter

A chunk is kept if it:

- has at least one matching condition tag, OR
- has a section title containing general dermatology keywords
  (`tổng quan`, `tiêu chuẩn`, `phân loại`, `đại cương`, `nguyên tắc`)

This drops boilerplate (e.g. acknowledgements, signature blocks,
appendices not relevant to the 8 conditions).
"""))

CELLS.append(code("""
GENERAL_KEYWORDS = ('tổng quan', 'tiêu chuẩn', 'phân loại', 'đại cương',
                    'nguyên tắc', 'điều trị')

def tag_conditions(text: str) -> list[str]:
    text_lower = text.lower()
    return [
        key for key, aliases in CONDITION_ALIASES.items()
        if any(alias in text_lower for alias in aliases)
    ]

def is_general(section_title: str) -> bool:
    return any(kw in section_title.lower() for kw in GENERAL_KEYWORDS)

filtered = []
for ch in raw_chunks:
    tags = tag_conditions(ch['text'])
    if tags or is_general(ch['section_title']):
        ch['condition_tags'] = tags
        filtered.append(ch)

print(f'Filtered chunks: {len(filtered)} (kept from {len(raw_chunks)} raw)')
print()
print('Per-condition coverage:')
for key in CONDITION_ALIASES:
    n = sum(1 for c in filtered if key in c['condition_tags'])
    flag = ' ⚠ NO COVERAGE' if n == 0 else ''
    print(f'  {key:25s} {n:>4d} chunks{flag}')
"""))

CELLS.append(md("""
## Cell 9 — Embed (multilingual-e5-small, 384-dim)

The e5 family **requires** the `passage:` prefix on indexed documents
and `query:` prefix on user queries — this is part of how the model was
trained, not optional.

Output dim: **384**. Verify before writing.
"""))

CELLS.append(code("""
from sentence_transformers import SentenceTransformer

EMBED_MODEL = 'intfloat/multilingual-e5-small'
model = SentenceTransformer(EMBED_MODEL, device='cuda' if __import__('torch').cuda.is_available() else 'cpu')

def embed_passages(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    prefixed = [f'passage: {t}' for t in texts]
    arr = model.encode(prefixed, batch_size=batch_size, normalize_embeddings=True,
                        show_progress_bar=True)
    return arr.tolist()

texts = [c['text'] for c in filtered]
embs = embed_passages(texts)
assert len(embs) == len(filtered), 'embed count mismatch'
assert all(len(e) == 384 for e in embs), 'expected 384-dim embeddings'
print(f'✓ {len(embs)} embeddings, dim={len(embs[0])}')

for c, e in zip(filtered, embs):
    c['embedding'] = e
"""))

CELLS.append(md("""
## Cell 10 — Write `data/chunks.json`

Stable `chunk_id`s of the form `chunk-NNNN`, zero-padded so lexical sort
matches numerical sort. The VLM cites these in its `citations[]` field
(see Blueprint §8 system prompt).
"""))

CELLS.append(code("""
SOURCE_URL = (
    'https://benhvienhatrung.vn/wp-content/uploads/2024/02/'
    'quyet-dinh-4416-qd-byt-2023-huong-dan-chan-doan-va-dieu-tri-'
    'cac-benh-da-lieu.pdf'
)

chunks_data = []
for i, ch in enumerate(filtered):
    chunks_data.append({
        'chunk_id': f'chunk-{i:04d}',
        'doc_id': 'qd-4416-byt-2023',
        'source_url': SOURCE_URL,
        'section_title': ch['section_title'],
        'chunk_index': i,
        'text': ch['text'],
        'token_count': ch['token_count'],
        'condition_tags': ch['condition_tags'],
        'source_pages': ch['source_pages'],
        'embedding': ch['embedding'],
    })

CHUNKS_PATH = DATA_DIR / 'chunks.json'
CHUNKS_PATH.write_text(
    json.dumps(chunks_data, ensure_ascii=False, indent=2),
    encoding='utf-8',
)
print(f'✓ Wrote {CHUNKS_PATH}: {len(chunks_data)} chunks, '
      f'{CHUNKS_PATH.stat().st_size:,} bytes')

print()
print('=' * 60)
print('TIP-002 — RAG corpus build summary')
print('=' * 60)
print(f'Pages extracted:       {len(pages)}')
print(f'Raw chunks:            {len(raw_chunks)}')
print(f'Filtered chunks:       {len(filtered)}')
print(f'Embedding dim:         {len(chunks_data[0][\"embedding\"]) if chunks_data else 0}')
print(f'Per-condition coverage:')
for key in CONDITION_ALIASES:
    n = sum(1 for c in chunks_data if key in c['condition_tags'])
    print(f'  {key:25s} {n:>4d} chunks')
print()
print('Acceptance gates:')
print(f'  ≥ 50 chunks:               {\"YES\" if len(chunks_data) >= 50 else \"NO — escalate\"}')
print(f'  All 8 conditions covered:  '
      f'{\"YES\" if all(any(k in c[\"condition_tags\"] for c in chunks_data) for k in CONDITION_ALIASES) else \"NO — escalate\"}')
print(f'  All chunks 200–800 tokens: '
      f'{\"YES\" if all(200 <= c[\"token_count\"] <= 800 for c in chunks_data) else \"NO\"}')
print(f'  Embedding dim 384:         '
      f'{\"YES\" if all(len(c[\"embedding\"]) == 384 for c in chunks_data) else \"NO\"}')
"""))

CELLS.append(md("""
## Cell 11 — Done

Next step: run `scripts/seed_kb_chunks.py` against a Postgres with the
`kb_chunks` table created (TIP-004). It loads `data/chunks.json` into
the table; the trigger on `kb_chunks` auto-populates the `tsvector`
column for BM25 search.

Re-running this notebook is safe — it overwrites `data/chunks.json` and
reuses cached extraction in `data/raw/pages.json`. To force a re-OCR,
delete `data/raw/pages.json` first.
"""))

# ---------------------------------------------------------------------------
NB['cells'] = CELLS
NB['metadata'] = {
    'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
    'language_info': {'name': 'python', 'version': '3.11'},
}

OUT = 'notebooks/02_ocr_pipeline.ipynb'
with open(OUT, 'w', encoding='utf-8') as f:
    nbf.write(NB, f)

print(f'Wrote {OUT} — {len(CELLS)} cells')
