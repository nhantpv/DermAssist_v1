# DermAssist VN

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

> **🔴 DEMO ONLY — Sample images only. NOT for clinical use.**
> This is a reference implementation released under Apache 2.0 for
> research / thesis / portfolio purposes.

---

## What this is

DermAssist VN is a Vision-Language-Model-based clinical decision support
demo for Vietnamese dermatology. It assists doctors with differential
diagnosis suggestions for **8 common conditions**, plus an out-of-distribution
escape valve for anything outside scope.

See [BLUEPRINT.md §1](docs/BLUEPRINT.md) for full project framing.

## ⚠️ NOT FOR CLINICAL USE

This system is a **suggestion-only assistant** that has not been clinically
validated, IRB-approved, or registered with the Vietnamese Ministry of
Health (Bộ Y Tế). It must **not** be used for real patient diagnosis,
triage, or treatment decisions.

Independent clinical judgment by a licensed physician is always required.

## 8 conditions in scope

| # | Tiếng Việt | English | Severity profile |
|---|---|---|---|
| 1 | Viêm da cơ địa | Atopic Dermatitis | Chronic, common in children |
| 2 | Nấm da | Fungal Infections | Common in hot/humid climate |
| 3 | Zona thần kinh | Herpes Zoster | **DANGEROUS** — esp. ophthalmicus |
| 4 | Mụn trứng cá | Acne | Adolescent, hormonal |
| 5 | Viêm da tiếp xúc & Mề đay | Contact Dermatitis & Urticaria | Allergen exposure |
| 6 | Chàm | Eczema | Chronic, often atopic-related |
| 7 | Vảy nến | Psoriasis | Chronic autoimmune |
| 8 | Bệnh ghẻ | Scabies | Highly contagious |

Anything outside these 8 → `ood_flag = true` + recommend specialist
consultation.

---

## Quickstart

### Local development setup

```bash
# 1. Clone and enter
git clone <repo-url> vlm-dermatology
cd vlm-dermatology

# 2. Create venv and install
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 3. Bring up Postgres + pgvector
docker compose up -d postgres
docker compose exec postgres psql -U dermassist -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 4. Configure env
cp .env.example .env
# Edit .env — at minimum set JWT_SECRET_KEY:
#   python -c "import secrets; print(secrets.token_hex(32))"
```

The VLM service (`VLM_ENDPOINT`) is expected to come from Modal in
deployment, or from a local vLLM server during development. See
[docs/path-to-production.md](docs/path-to-production.md).

### Running Colab notebooks

GPU-bound work (model verification, RAG corpus extraction, visual
descriptions, evaluation) runs in Colab notebooks under [`notebooks/`](notebooks/).

| Notebook | Purpose |
|---|---|
| `01_model_verify.ipynb` | Load Qwen2.5-VL INT4, verify VRAM |
| `02_ocr_pipeline.ipynb` | Extract & chunk QĐ-4416/BYT, embed, export |
| `03_fewshot_gen.ipynb` | Self-describe via Qwen → `visual_descriptions.json` |
| `04_dataset_audit.ipynb` | Per-condition sample count audit (Risk C) |
| `05_eval_run.ipynb` | Run eval suite, dump metrics |

### Editing notebooks

Notebooks under `notebooks/` are source-of-truth — edit them directly
in Colab or Jupyter. Before committing, clear all outputs:

```bash
jupyter nbconvert --clear-output --inplace notebooks/*.ipynb
```

(Or use `nbstripout` if installed.) Do not commit outputs — they bloat
the repo and create spurious diffs.

### Running tests

```bash
pytest                       # all tests
pytest tests/unit            # unit only
pytest -k "preflight"        # filter by name
pytest --cov=backend         # with coverage
```

---

## Architecture

See [BLUEPRINT.md §2](docs/BLUEPRINT.md) for the full diagram.
At a glance:

```
Browser (HTMX + Tailwind)
     ↓ HTTPS
FastAPI (Modal serverless GPU)
  ├── Auth (JWT)
  ├── Guardrails (PII redact, injection canary, language sniff)
  ├── Image preflight (Laplacian blur + exposure)
  ├── RAG retrieve (BM25 + pgvector + RRF)
  ├── VLM call (Qwen2.5-VL-7B-Instruct INT4 on vLLM, semaphore=1)
  ├── Output validation (Pydantic + composite OOD rule)
  └── Persist (Postgres + audit_log)
```

## Project structure

See [BLUEPRINT.md §4](docs/BLUEPRINT.md) for the full layout.

```
vlm-dermatology/
├── notebooks/        ← Colab GPU work
├── data/             ← Artifacts (chunks, visual descs, eval results)
├── backend/          ← FastAPI app
├── frontend/         ← Jinja2 + HTMX templates
├── migrations/       ← SQL DDL
├── eval/             ← Eval harness, gold set, metrics
├── tests/            ← pytest unit + integration
├── deploy/           ← Surface A (demo) + Surface B (deferred)
├── scripts/          ← One-shot scripts
└── docs/             ← Architecture, path-to-production, eval-limitations
```

## Contributing

See `docs/CONTRIBUTING.md` (placeholder — TBD).

## License

Apache License 2.0 — see [LICENSE](LICENSE).

## Citation

```bibtex
@misc{dermassist_vn_2026,
  title  = {DermAssist VN: VLM-based Clinical Decision Support for Vietnamese Dermatology (MVP)},
  author = {DermAssist VN Project Contributors},
  year   = {2026},
  note   = {Apache 2.0. Demo / portfolio / thesis reference implementation.}
}
```

This project uses public dermatology datasets:

```bibtex
@inproceedings{groh2021evaluating,
  author    = {Matthew Groh and Caleb Harris and Luis Soenksen and ...},
  title     = {Evaluating Deep Neural Networks Trained on Clinical Images
               in Dermatology with the Fitzpatrick 17k Dataset},
  booktitle = {CVPR Workshop},
  year      = {2021}
}

@article{ward2024scin,
  title   = {SCIN: A Crowdsourced Dataset of Diverse Skin Conditions
             Annotated by Dermatologists},
  author  = {Ward, Abbi and ...},
  journal = {Google Health},
  year    = {2024},
  url     = {https://github.com/google-research-datasets/scin}
}
```

DermNet NZ image URLs are referenced for non-commercial research only;
images are not redistributed (see `docs/dermnet_attribution.md`).
