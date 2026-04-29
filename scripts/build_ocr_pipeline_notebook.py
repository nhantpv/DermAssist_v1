"""
Build notebooks/02_ocr_pipeline.ipynb (TIP-002A — Marker variant).

Same convention as the other build helpers: assemble a clean,
output-cleared .ipynb so the cell layout is reviewable as Python.

History:
  TIP-002   — EasyOCR-based pipeline.
  TIP-002A  — swap EasyOCR for Marker (PDF → Markdown). EasyOCR fallback
              is preserved as a commented-out cell.

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
# 02 — OCR + RAG Corpus Pipeline (TIP-002A: Marker)

**Source:** Quyết định 4416/QĐ-BYT (Bộ Y Tế, 06/12/2023) —
*Hướng dẫn chẩn đoán và điều trị các bệnh da liễu*.

This notebook replaces TIP-002's EasyOCR step with **Marker**
(https://github.com/datalab-to/marker), which produces structured
Markdown directly. The MOH guideline has numbered section hierarchy,
diagnostic-criteria tables, and multi-column layouts — Markdown
preserves all of that, while plain OCR text loses it.

**Trade-offs (accepted by Chủ thầu):**

- Marker is GPL-3.0 — used **only at build time**, never linked into
  the runtime backend (see `docs/path-to-production.md`).
- Surya (Marker's OCR backbone) has a $5M revenue/funding commercial
  clause — irrelevant for MVP / research / portfolio.
- Conversion takes ~25–35 min on Colab T4 vs ~15 min for EasyOCR.
  Output is cached (`data/raw/qd-4416-byt-2023.md`), so re-runs are
  near-instant.

**Pipeline stages:**

1. Get PDF
2. Convert PDF → Markdown via Marker (Drive-cached)
3. Markdown-native section parsing (`#`, `##`, `###`)
4. Tokenize + section-aware chunking with split + merge
5. Tag chunks with relevant condition keys
6. Embed with `intfloat/multilingual-e5-small` (`passage:` prefix)
7. Write `data/chunks.json`

**Acceptance hooks (unchanged from TIP-002):**

- ≥ 50 chunks total
- ≥ 1 chunk per in-scope condition (8 of them)
- Each chunk: 200–800 tokens
- Embeddings: exactly 384 dims
- Stable `chunk_id`s of the form `chunk-NNNN`
- `chunks.json` schema unchanged from TIP-002

**Run on Colab T4** (or any machine with CUDA + ≥ 6 GB VRAM).
"""))

CELLS.append(md("""
## Cell 1 — Setup

`marker-pdf` (replaces `easyocr` from TIP-002) is the slow install —
it pulls Surya OCR + layout detection models. Sentence-transformers
and tiktoken are unchanged. EasyOCR is no longer required for the
main flow but the fallback cell at the bottom keeps it around in case
Marker fails on a future PDF.
"""))

CELLS.append(code("""
import importlib.util, subprocess, sys

def ensure(*pkgs: str) -> None:
    missing = [p for p in pkgs if importlib.util.find_spec(p.split('==')[0].split('[')[0]) is None]
    if missing:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', *missing])

# Marker replaces EasyOCR for the primary path. tiktoken + sentence-transformers
# are unchanged from TIP-002.
ensure('pymupdf', 'marker-pdf', 'sentence_transformers', 'tiktoken')

import fitz  # pymupdf
import json, re, hashlib
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone

# Default to local layout. On Colab, override these to point at Drive
# (see Cell 2's optional Drive-mount block) so the Markdown cache and
# chunks.json survive runtime restarts.
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
## Cell 2 — (Colab only) Mount Drive for cache persistence

Skip this cell on local. On Colab, mount Drive and point `RAW_DIR` at
a project folder; this preserves the Marker Markdown cache across
runtime restarts so the 25-minute conversion only runs once per PDF.

```python
from google.colab import drive
drive.mount('/content/drive')

PROJECT_DIR = Path('/content/drive/MyDrive/DermAssist')
RAW_DIR = PROJECT_DIR / 'data' / 'raw'
DATA_DIR = PROJECT_DIR / 'data'
RAW_DIR.mkdir(parents=True, exist_ok=True)
print('Using Drive:', RAW_DIR)
```

(Cell intentionally left as code-comment so it doesn't error outside
Colab. Uncomment in a Colab session.)
"""))

CELLS.append(code("""
# from google.colab import drive
# drive.mount('/content/drive')
# PROJECT_DIR = Path('/content/drive/MyDrive/DermAssist')
# RAW_DIR = PROJECT_DIR / 'data' / 'raw'
# DATA_DIR = PROJECT_DIR / 'data'
# RAW_DIR.mkdir(parents=True, exist_ok=True)
# print('Using Drive:', RAW_DIR)
"""))

CELLS.append(md("""
## Cell 3 — Get the PDF

Same as TIP-002. Auto-download via the bash helper; manual upload
fallback for Colab.
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
## Cell 4 — `has_text_layer()` (utility, not branched on)

Marker handles both text-layer and scanned PDFs uniformly, so we no
longer branch on this. Kept defined as a utility for future TIPs that
might want to know whether a source has a text layer (e.g., to skip
Marker entirely for clean digital PDFs and save 25 minutes).
"""))

CELLS.append(code("""
def has_text_layer(pdf_path: Path, sample_pages: int = 5) -> bool:
    \"\"\"Heuristic: > 200 chars/page on average across the first N pages.\"\"\"
    doc = fitz.open(pdf_path)
    n = min(sample_pages, len(doc))
    total = sum(len(doc[i].get_text('text').strip()) for i in range(n))
    return total > 200 * n

# Informational only — Marker is run regardless.
print(f'Pages: {len(fitz.open(PDF_PATH))}')
print(f'has_text_layer: {has_text_layer(PDF_PATH)} (informational)')
"""))

CELLS.append(md("""
## Cell 5 — Convert PDF → Markdown via Marker

`convert_pdf_to_markdown()` caches the result to `RAW_DIR/qd-4416-byt-2023.md`
so subsequent runs (even after Colab kernel restart, if `RAW_DIR` is on
Drive) skip the heavy step.

**Marker API verification:** the call below uses the public API as of
the date this TIP was authored. If `marker-pdf` has updated:

- The import path may have moved (`marker.converters.pdf` is current).
- `text_from_rendered()` may have additional return values; the unpack
  `markdown_text, _, _ = text_from_rendered(rendered)` matches versions
  that return `(markdown, metadata, images)`.

If your installed version differs, adapt the call. Verify by:

```python
from marker.output import text_from_rendered
help(text_from_rendered)
```
"""))

CELLS.append(code("""
def convert_pdf_to_markdown(pdf_path: Path, cache_path: Path) -> str:
    \"\"\"Run Marker on `pdf_path`, cache the Markdown to `cache_path`.

    Returns the Markdown text. Subsequent calls with an existing cache
    skip the model load + conversion entirely.
    \"\"\"
    cache_path = Path(cache_path)
    if cache_path.exists():
        print(f'✓ Cached Markdown found: {cache_path} '
              f'({cache_path.stat().st_size:,} bytes)')
        return cache_path.read_text(encoding='utf-8')

    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import text_from_rendered

    print('Loading Marker models (one-time, ~3-5 min on T4)...')
    converter = PdfConverter(artifact_dict=create_model_dict())

    print(f'Converting {pdf_path} → Markdown '
          '(~25-35 min on T4 for 474 pages)...')
    rendered = converter(str(pdf_path))
    markdown_text, _, _ = text_from_rendered(rendered)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(markdown_text, encoding='utf-8')
    print(f'✓ Wrote {len(markdown_text):,} chars to {cache_path}')
    return markdown_text

MD_CACHE = RAW_DIR / 'qd-4416-byt-2023.md'
md_text = convert_pdf_to_markdown(PDF_PATH, MD_CACHE)

print()
print(f'Markdown length: {len(md_text):,} chars')
hd_count = sum(1 for line in md_text.splitlines() if line.startswith('#'))
print(f'Heading count:   {hd_count}')
"""))

CELLS.append(md("""
## Cell 6 — Markdown-native section header parser

The TIP-002 regex parser is gone. With Markdown input, headers are
explicit (`#`, `##`, `###`). `detect_section_header()` now returns
`(level, title) | None` — `level` is 1..6, `title` is the heading text
(Marker preserves the original numbering inside the title, e.g.,
`### 2.3. Viêm da cơ địa` still has `2.3. Viêm da cơ địa` as its
title).
"""))

CELLS.append(code("""
def detect_section_header(line: str) -> tuple[int, str] | None:
    \"\"\"Return (level, title) for Markdown headers; None otherwise.\"\"\"
    stripped = line.strip()
    if not stripped.startswith('#'):
        return None
    level = 0
    for ch in stripped:
        if ch == '#':
            level += 1
        else:
            break
    if level == 0 or level > 6:
        return None
    title = stripped[level:].strip()
    if not title or len(title) > 200:
        return None
    return (level, title)


# Sanity tests
_cases = [
    ('# Chương 2. Các Bệnh Da Liễu', (1, 'Chương 2. Các Bệnh Da Liễu')),
    ('## 2.3. Viêm da cơ địa',       (2, '2.3. Viêm da cơ địa')),
    ('### 2.3.1. Tiêu chuẩn',        (3, '2.3.1. Tiêu chuẩn')),
    ('Just a paragraph',              None),
    ('',                              None),
    ('#######',                       None),  # level=7, > 6
    ('## ',                           None),  # empty title
]
for inp, want in _cases:
    got = detect_section_header(inp)
    assert got == want, f'detect_section_header({inp!r}) = {got!r}, want {want!r}'
print('✓ detect_section_header sanity OK')
"""))

CELLS.append(md("""
## Cell 7 — Token counter + overlap splitter

`count_tokens(text, tokenizer=None)` and
`split_with_overlap(text, target, overlap, tokenizer=None)` are the
TIP-002 helpers, generalized to accept an explicit tokenizer (so they
can be unit-tested with stubs) but defaulting to the global `TOK`
(`tiktoken cl100k_base`) when `tokenizer is None`.

`split_with_overlap()` now returns `(text, token_count)` tuples so
callers don't have to recompute counts.
"""))

CELLS.append(code("""
import tiktoken
TOK = tiktoken.get_encoding('cl100k_base')

def count_tokens(text: str, tokenizer=None) -> int:
    t = tokenizer if tokenizer is not None else TOK
    return len(t.encode(text))

def split_with_overlap(text: str, target_tokens: int = 400,
                       overlap_tokens: int = 50, tokenizer=None
                       ) -> list[tuple[str, int]]:
    \"\"\"Split `text` into overlapping windows of ~target_tokens.

    Returns list of (sub_text, sub_token_count). The final window may be
    shorter than target_tokens.
    \"\"\"
    t = tokenizer if tokenizer is not None else TOK
    tokens = t.encode(text)
    if len(tokens) <= target_tokens:
        return [(text, len(tokens))]
    out = []
    step = max(1, target_tokens - overlap_tokens)
    for start in range(0, len(tokens), step):
        end = min(start + target_tokens, len(tokens))
        sub = t.decode(tokens[start:end])
        out.append((sub, end - start))
        if end >= len(tokens):
            break
    return out
"""))

CELLS.append(md("""
## Cell 8 — Section-aware chunking on Markdown

The chunker now walks the Markdown structure directly:

1. Iterate lines; each `<!-- page N -->` HTML comment (Marker emits
   these on some versions) updates the current page set.
2. Each Markdown header flushes the current section buffer and starts
   a new one with the new title.
3. After all sections collected, apply token-budget logic:
   - Sections > `max_tokens` → split with `split_with_overlap`.
   - Sections < `min_tokens` → tag `_merge_pending` and let
     `merge_small_consecutive()` join them.
   - Sections in band → keep as-is.

The TIP-002 `pages: list[dict]` input shape is gone — we feed Markdown
text instead.
"""))

CELLS.append(code("""
# Marker emits page markers as HTML comments on some versions.
PAGE_PAT = re.compile(r'<!--\\s*page\\s+(\\d+)\\s*-->', re.IGNORECASE)


def chunk_by_section(markdown_text: str,
                     target_tokens: int = 400,
                     overlap_tokens: int = 50,
                     min_tokens: int = 200,
                     max_tokens: int = 800,
                     tokenizer=None) -> list[dict]:
    \"\"\"Walk Markdown headers; group content; split big / merge small.\"\"\"
    sections: list[dict] = []
    cur_title = 'Preamble'
    cur_level = 0
    cur_buf: list[str] = []
    cur_pages: set[int] = set()

    def _flush():
        if not cur_buf:
            return
        text = '\\n'.join(cur_buf).strip()
        if text:
            sections.append({
                'section_title': cur_title,
                'level': cur_level,
                'text': text,
                'source_pages': sorted(cur_pages),
            })

    for line in markdown_text.splitlines():
        m = PAGE_PAT.search(line)
        if m:
            cur_pages.add(int(m.group(1)))
            continue
        hd = detect_section_header(line)
        if hd is not None:
            _flush()
            cur_level, cur_title = hd
            cur_buf = []
            cur_pages = set()
            continue
        cur_buf.append(line)
    _flush()

    # Token-budget pass
    chunks: list[dict] = []
    for sec in sections:
        tc = count_tokens(sec['text'], tokenizer)
        if tc > max_tokens:
            for sub_text, sub_count in split_with_overlap(
                sec['text'], target_tokens, overlap_tokens, tokenizer
            ):
                chunks.append({**sec, 'text': sub_text, 'token_count': sub_count})
        elif tc < min_tokens:
            chunks.append({**sec, 'text': sec['text'],
                           'token_count': tc, '_merge_pending': True})
        else:
            chunks.append({**sec, 'text': sec['text'], 'token_count': tc})

    return merge_small_consecutive(chunks, min_tokens, max_tokens, tokenizer)


def merge_small_consecutive(chunks: list[dict], min_tokens: int,
                            max_tokens: int, tokenizer=None) -> list[dict]:
    \"\"\"Combine consecutive `_merge_pending` chunks until they hit min_tokens
    or would exceed max_tokens. Pages and titles merge as well.\"\"\"
    out: list[dict] = []
    buffer: dict | None = None
    for ch in chunks:
        if ch.get('_merge_pending'):
            if buffer is None:
                buffer = {k: v for k, v in ch.items() if k != '_merge_pending'}
            else:
                merged_text = buffer['text'] + '\\n\\n' + ch['text']
                merged_count = count_tokens(merged_text, tokenizer)
                if merged_count <= max_tokens:
                    buffer['text'] = merged_text
                    buffer['token_count'] = merged_count
                    buffer['source_pages'] = sorted(
                        set(buffer['source_pages']) | set(ch['source_pages'])
                    )
                else:
                    out.append(buffer)
                    buffer = {k: v for k, v in ch.items() if k != '_merge_pending'}
        else:
            if buffer is not None:
                out.append(buffer)
                buffer = None
            out.append(ch)
    if buffer is not None:
        out.append(buffer)
    return out
"""))

CELLS.append(md("""
## Cell 9 — Tag and filter

Same condition keys as TIP-002. The filter still drops chunks that
have neither a condition tag nor a "general dermatology" section
title — boilerplate (signatures, appendices, table of contents) is
removed.
"""))

CELLS.append(code("""
# 8 conditions with VN aliases for tagging (Blueprint §1.1)
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
"""))

CELLS.append(md("""
## Cell 10 — Run extraction → chunks → filtered

Drives the pipeline. After this cell, `filtered` is the list of chunks
ready to embed.
"""))

CELLS.append(code("""
raw_chunks = chunk_by_section(md_text)
print(f'Raw chunks: {len(raw_chunks)}')

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

print()
print('Token-count percentiles:')
counts = sorted(c['token_count'] for c in filtered)
for q, name in [(0, 'min'), (len(counts)//4, 'p25'), (len(counts)//2, 'p50'),
                (3*len(counts)//4, 'p75'), (-1, 'max')]:
    if counts:
        print(f'  {name}: {counts[q]}')
"""))

CELLS.append(md("""
## Cell 11 — Embed (multilingual-e5-small, 384-dim)

The e5 family **requires** the `passage:` prefix on indexed documents
and `query:` prefix on user queries — this is part of how the model
was trained, not optional.

Output dim: **384**. Verify before writing.
"""))

CELLS.append(code("""
from sentence_transformers import SentenceTransformer

EMBED_MODEL = 'intfloat/multilingual-e5-small'
device = 'cuda' if __import__('torch').cuda.is_available() else 'cpu'
model = SentenceTransformer(EMBED_MODEL, device=device)

def embed_passages(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    prefixed = [f'passage: {t}' for t in texts]
    arr = model.encode(prefixed, batch_size=batch_size,
                        normalize_embeddings=True,
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
## Cell 12 — Write `data/chunks.json`

**Schema unchanged from TIP-002** (per TIP-002A constraint): each
chunk has `chunk_id`, `doc_id`, `source_url`, `section_title`,
`chunk_index`, `text`, `token_count`, `condition_tags`,
`source_pages`, `embedding`.

`level` from the Markdown parser is intentionally NOT in the output —
it's an internal hint for chunking only.
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
print('TIP-002A — RAG corpus build summary (Marker)')
print('=' * 60)
print(f'Markdown chars:        {len(md_text):,}')
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
## Cell 13 — EasyOCR fallback (kept for emergency use)

Marker is the primary path. If a future PDF chokes Marker (e.g.,
extreme layout, decorative fonts, very low scan quality), the EasyOCR
path from TIP-002 is preserved here as a commented-out cell.

**To re-enable EasyOCR:**

1. Uncomment the install + function definitions below.
2. Replace `convert_pdf_to_markdown(...)` in Cell 5 with
   `extract_text_ocr(PDF_PATH, scale=2.0, gpu=True)` and join the
   page texts.
3. Re-introduce the regex-based section-header detector if you also
   need to bypass Markdown structure.

Note that the chunker (Cell 8) takes Markdown text — falling back to
plain OCR text would also require reverting to the TIP-002 line-walking
chunker. The simplest emergency path is: run `extract_text_ocr` from
this cell, then synthesize Markdown headers manually before passing
into `chunk_by_section`.
"""))

CELLS.append(code("""
# # --- BEGIN EasyOCR fallback (commented out — Marker is the primary path) ---
# # ensure('easyocr')
# # import easyocr
# #
# # HEADER_FOOTER_PATTERNS = [
# #     re.compile(r'^\\s*\\d+\\s*$'),                     # bare page number
# #     re.compile(r'^\\s*Trang\\s+\\d+\\s*$', re.I),     # \"Trang N\"
# #     re.compile(r'BỘ Y TẾ.{0,80}$', re.I),
# #     re.compile(r'^\\s*-+\\s*$'),
# # ]
# #
# # def clean_ocr_line(line: str) -> str | None:
# #     s = line.strip()
# #     if not s:
# #         return None
# #     for pat in HEADER_FOOTER_PATTERNS:
# #         if pat.search(s):
# #             return None
# #     if len(s) < 4 and not re.match(r'^[-\\u2022•]|\\d+[.)]', s):
# #         return None
# #     return re.sub(r'\\s+', ' ', s)
# #
# # def extract_text_ocr(pdf_path: Path, scale: float = 2.0,
# #                      gpu: bool = True) -> list[dict]:
# #     reader = easyocr.Reader(['vi', 'en'], gpu=gpu)
# #     doc = fitz.open(pdf_path)
# #     pages = []
# #     for i, page in enumerate(doc):
# #         mat = fitz.Matrix(scale, scale)
# #         pix = page.get_pixmap(matrix=mat)
# #         results = reader.readtext(pix.tobytes('png'), detail=0, paragraph=True)
# #         cleaned = [c for line in results if (c := clean_ocr_line(line))]
# #         pages.append({'page_num': i + 1, 'text': '\\n'.join(cleaned)})
# #         if (i + 1) % 25 == 0:
# #             print(f'  OCR progress: {i + 1}/{len(doc)} pages')
# #     return pages
# # --- END EasyOCR fallback ---
"""))

CELLS.append(md("""
## Cell 14 — Done

`data/chunks.json` is the committed artifact. `data/raw/qd-4416-byt-2023.md`
is gitignored (it's the Marker output cache; re-derivable from the PDF).

Re-running this notebook is safe: the Markdown cache is reused, the
final cells overwrite `chunks.json`. To force a re-conversion, delete
the cached `.md` first.

Next: `scripts/seed_kb_chunks.py` loads `chunks.json` into Postgres
`kb_chunks` (TIP-004 migration must be applied first).
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
