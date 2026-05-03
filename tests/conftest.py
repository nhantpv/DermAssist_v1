"""Test config — ensure required env vars exist before any `backend.*`
module is imported, so `Settings` and the cached engine instantiate cleanly.

`Settings` is `lru_cache`'d, so once it loads, env-var changes during a
test session won't affect already-cached values. Set fallbacks here.
Real test runs override DATABASE_URL via the local docker-compose
postgres (`postgresql+asyncpg://dermassist:dermassist_dev@localhost:5432/dermassist`).
"""
import os

# Provide a deterministic JWT secret for tests if the user hasn't exported one.
os.environ.setdefault("JWT_SECRET_KEY", "x" * 64)
# Provide a default DATABASE_URL pointing at the docker-compose postgres.
# Integration tests check connectivity and skip on failure; unit tests don't
# touch the DB but still need the URL to satisfy Settings validation.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://dermassist:dermassist_dev@localhost:5432/dermassist",
)
