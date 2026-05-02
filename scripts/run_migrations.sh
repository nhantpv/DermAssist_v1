#!/usr/bin/env bash
# ============================================================
# run_migrations.sh
# Apply hand-written .sql migrations in order, then run Alembic
# for any subsequent migrations. Idempotent.
# ============================================================
set -euo pipefail

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL not set"
  echo "  Example: export DATABASE_URL=postgresql+asyncpg://dermassist:dermassist_dev@localhost:5432/dermassist"
  exit 1
fi

# Convert asyncpg URL to psql-compatible (strip +asyncpg suffix)
PSQL_URL="${DATABASE_URL/postgresql+asyncpg/postgresql}"

echo "→ Applying hand-written migrations..."
for f in migrations/0*.sql; do
  echo "  Running: $f"
  psql "$PSQL_URL" -v ON_ERROR_STOP=1 -f "$f"
done

echo "→ Running Alembic upgrades..."
alembic upgrade head

echo "✓ All migrations applied."
