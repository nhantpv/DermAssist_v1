#!/usr/bin/env bash
# Production entrypoint for Railway. Runs migrations + seeds + uvicorn.
# Single worker by design: TIP-008 lifespan loads the embedder once;
# multi-worker would multiply that footprint and OOM small containers.

set -euo pipefail

echo "→ Running migrations..."
bash scripts/run_migrations.sh

# Seed kb_chunks only when empty. The seed script itself is idempotent
# (DELETE + INSERT by doc_id), but re-seeding 339 rows on every deploy
# adds ~30s of pointless DB churn. Use psql to count first.
PSQL_URL="${DATABASE_URL/postgresql+asyncpg/postgresql}"
KB_COUNT=$(psql "$PSQL_URL" -tA -c \
  "SELECT count(*) FROM kb_chunks WHERE doc_id = 'qd-4416-byt-2023';" \
  2>/dev/null || echo "0")
KB_COUNT=${KB_COUNT:-0}
if [ "$KB_COUNT" -lt 1 ]; then
  echo "→ Seeding kb_chunks (current count: $KB_COUNT)..."
  python scripts/seed_kb_chunks.py
else
  echo "→ kb_chunks already seeded ($KB_COUNT rows); skipping."
fi

echo "→ Starting uvicorn..."
exec uvicorn backend.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers 1 \
  --log-level info
