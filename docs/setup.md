# Setup Guide — DermAssist VN

Tested on Ubuntu 22.04 / 24.04. Adapt commands for other distros.

## 1. Prerequisites

| Tool | Version | Check command |
|---|---|---|
| Python | ≥ 3.11 | `python3 --version` |
| pip | ≥ 23 | `pip --version` |
| Docker Engine | ≥ 24 | `docker --version` |
| Docker Compose v2 | ≥ 2.20 | `docker compose version` |
| git | any recent | `git --version` |

## 2. Install Docker (Ubuntu 22.04 / 24.04)

The simplest route uses the Ubuntu-packaged Docker:

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER
newgrp docker        # apply group change in current shell

# Verify
docker --version
docker compose version
```

If you prefer Docker's official packages (newer versions),
follow https://docs.docker.com/engine/install/ubuntu/.

## 3. Set up Python environment

```bash
cd vlm-dermatology

# If python3.11 is not available on your system, python3.12 also works
# (pyproject.toml says requires-python = ">=3.11")
python3 -m venv .venv
source .venv/bin/activate

# Editable install from pyproject.toml (canonical):
pip install --upgrade pip
pip install -e ".[dev]"
```

## 4. Configure environment variables

```bash
cp .env.example .env

# Generate a real JWT secret:
python -c "import secrets; print(secrets.token_hex(32))"
# Paste the output as JWT_SECRET_KEY=... in .env
```

## 5. Bring up Postgres + pgvector

```bash
docker compose up -d postgres

# Wait ~5 seconds for Postgres healthcheck to pass, then:
docker compose exec postgres psql -U dermassist -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Verify:
docker compose exec postgres psql -U dermassist -c "\dx"
# Should show: vector | x.x.x | public | vector data type and ivfflat ...
```

## 6. Verification

```bash
# Python imports cleanly:
python -c "import backend; import eval; print('✓ packages importable')"

# Postgres reachable:
docker compose exec postgres pg_isready -U dermassist

# Pytest discovers tests dir (will say "no tests ran" until TIPs add tests):
pytest --collect-only
```

If all three succeed, TIP-000 is fully verified.

## 7. Common issues

| Problem | Fix |
|---|---|
| `Multiple top-level packages discovered` on `pip install -e .` | Make sure `[tool.setuptools.packages.find]` block is in `pyproject.toml` |
| `permission denied` on docker socket | `sudo usermod -aG docker $USER && newgrp docker` |
| Postgres healthcheck never passes | `docker compose logs postgres` to see why; usually port 5432 already in use |
| `vector` extension fails | Confirm image is `pgvector/pgvector:pg16`, not stock `postgres` |
| Python 3.10 or older | Install Python 3.11+: `sudo apt install python3.11 python3.11-venv` |