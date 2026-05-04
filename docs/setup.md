# Setup Guide — DermAssist VN

Canonical local dev walkthrough. Tested on Ubuntu 22.04 / 24.04 with
Python 3.11+ and Docker Engine ≥ 24. Adapt commands for other distros.

Target: a fresh contributor goes from `git clone` to `/health` returning
`200` in **under 15 minutes**.

---

## 1. Prerequisites

| Tool             | Version       | Check command            |
|------------------|---------------|--------------------------|
| Python           | ≥ 3.11        | `python3 --version`      |
| pip              | ≥ 23          | `pip --version`          |
| Docker Engine    | ≥ 24          | `docker --version`       |
| Docker Compose v2| ≥ 2.20        | `docker compose version` |
| psql (libpq)     | any           | `psql --version`         |
| git              | any           | `git --version`          |

`psql` is needed by `scripts/run_migrations.sh`. If it's missing on your
machine, you can install it via `sudo apt install postgresql-client` or
run migrations through the container directly (see step 5 alternative).

## 2. Install Docker (Ubuntu)

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2 postgresql-client
sudo usermod -aG docker $USER
newgrp docker          # apply group change in current shell
docker --version && docker compose version
```

For Docker's official packages (newer versions), follow
the [official Docker Engine install guide](https://docs.docker.com/engine/install/ubuntu/).

## 3. Python environment

```bash
cd vlm-dermatology
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

Available extras:

- `[dev]` — pytest, pytest-asyncio, ruff, mypy, asgi-lifespan
- `[gpu]` — vllm, torch, transformers, auto-awq (Colab/GPU only)
- `[ocr]` — pymupdf, easyocr (TIP-002 PDF extraction)

## 4. Environment variables

```bash
cp .env.example .env
```

Required:

- `JWT_SECRET_KEY` — generate with `python -c "import secrets;print(secrets.token_hex(32))"`
- `DATABASE_URL` — defaults to the local docker-compose Postgres
  (`postgresql+asyncpg://dermassist:dermassist_dev@localhost:5432/dermassist`)

Optional:

- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` —
  enables the "Sign in with Google" path on `/login`. Leave unset to
  use the `demo / demo` local fallback. To configure: create a project
  in [Google Cloud Console](https://console.cloud.google.com/), add an
  OAuth 2.0 Client (web application) with authorized redirect URI
  `http://localhost:8000/auth/google/callback`, copy client ID/secret
  into `.env`.

## 5. Postgres + migrations

```bash
docker compose up -d postgres

# Wait for healthcheck (≈5 seconds), then ensure pgvector extension
docker compose exec postgres psql -U dermassist -d dermassist \
    -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Apply hand-written migrations 001 → 005, then any Alembic upgrades
export DATABASE_URL='postgresql+asyncpg://dermassist:dermassist_dev@localhost:5432/dermassist'
bash scripts/run_migrations.sh
```

Current migrations:

- `001_init_schema.sql` — users, encounters, audit_log, kb_chunks
- `002_seed_demo_user.sql` — `demo / demo` account
- `003_add_chat_messages_and_oauth.sql` — chat_messages table + Google OAuth columns
- `004_password_hash_nullable.sql` — relaxes `password_hash` for OAuth-only users
- `005_add_patient_context.sql` — `encounters.patient_context jsonb`

If `psql` is missing locally, run each migration through the container:

```bash
for f in migrations/0*.sql; do
  docker compose exec -T postgres psql -U dermassist -d dermassist \
      -v ON_ERROR_STOP=1 < "$f"
done
```

Authoritative column reference: [docs/SCHEMA_CURRENT.md](SCHEMA_CURRENT.md).

## 6. Run the app

```bash
uvicorn backend.main:app --reload
# → http://localhost:8000
```

- `/health` returns `{"status": "ok"}`
- `/login` shows the login page (demo / demo, or Google if configured)
- `/encounters/new` is the create form (auth required)

## 7. Tests

```bash
pytest                       # all tests (unit + integration)
pytest tests/unit            # unit only — no DB required
pytest -k "preflight"        # filter by name
pytest --cov=backend         # with coverage
```

Integration tests skip themselves automatically if Postgres is not
reachable on `DATABASE_URL`.

## 8. Common issues

| Problem | Fix |
|---|---|
| `Multiple top-level packages discovered` on `pip install -e .` | `[tool.setuptools.packages.find]` block must be in `pyproject.toml` (it is — don't remove it) |
| `permission denied` on docker socket | `sudo usermod -aG docker $USER && newgrp docker` |
| Postgres healthcheck never passes | `docker compose logs postgres` — usually port 5432 already bound |
| `vector` extension fails | Confirm image is `pgvector/pgvector:pg16`, not stock `postgres` |
| Migration `005` says column already exists | That's expected; the migration is idempotent (NOTICE, not ERROR) |
| `psql: command not found` | `sudo apt install postgresql-client`, or use the container fallback in step 5 |
| Python 3.10 or older | `sudo apt install python3.11 python3.11-venv` |
