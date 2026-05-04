# DermAssist VN

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

> **⚠ Closed beta — Hệ thống hỗ trợ quyết định lâm sàng. KHÔNG thay thế bác sĩ.**

DermAssist VN is a Vietnamese-language clinical decision support system
for dermatology. Doctors upload a lesion image and patient context;
the system returns a structured differential diagnosis grounded in
MoH guidelines (Quyết định 4416/QĐ-BYT) plus a multi-turn follow-up
chatbot. V1 is a closed clinician beta; eight conditions in scope plus
an OOD escape valve.

See [docs/BLUEPRINT.md](docs/BLUEPRINT.md) for the full architecture
and [docs/BLUEPRINT-AMENDMENT-001.md](../user_data/BLUEPRINT-AMENDMENT-001.md)
for the V1 scope lock.

## Quick start

```bash
git clone <repo-url> vlm-dermatology && cd vlm-dermatology
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
docker compose up -d postgres && bash scripts/run_migrations.sh
cp .env.example .env  # set JWT_SECRET_KEY (use: python -c "import secrets;print(secrets.token_hex(32))")
uvicorn backend.main:app --reload  # → http://localhost:8000
```

Login at `/login` with `demo / demo`. Full setup walkthrough in
[docs/setup.md](docs/setup.md).

## Documentation

- [docs/BLUEPRINT.md](docs/BLUEPRINT.md) — architecture, requirements (38 REQs)
- [docs/SCHEMA_CURRENT.md](docs/SCHEMA_CURRENT.md) — authoritative DB column reference
- [docs/setup.md](docs/setup.md) — full local dev setup walkthrough
- [docs/TIPS_LANDED.md](docs/TIPS_LANDED.md) — V1 build log
- [docs/path-to-production.md](docs/path-to-production.md) — Surface B notes
- [docs/eval-limitations.md](docs/eval-limitations.md) — distribution-shift caveats

## Tech stack (V1)

FastAPI + Pydantic v2 + Jinja2/HTMX, async SQLAlchemy on Postgres 16
(pgvector for embeddings, tsvector for BM25), JWT auth + optional
Google OAuth. VLM calls go to OpenAI gpt-4o-mini via API. Deploys to
Railway with a custom domain. See
[BLUEPRINT-AMENDMENT-001.md §3.1](../user_data/BLUEPRINT-AMENDMENT-001.md)
for the full stack rationale.

## Status

V1 closed clinician beta in active development. Wave breakdown in
[docs/TIPS_LANDED.md](docs/TIPS_LANDED.md).

## License

Apache License 2.0 — see [LICENSE](LICENSE).
