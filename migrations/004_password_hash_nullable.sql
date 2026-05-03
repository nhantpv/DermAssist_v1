-- ============================================================
-- 004_password_hash_nullable.sql
-- TIP-006-V1 piggyback: relax password_hash NOT NULL so OAuth users
-- don't need a placeholder hash. Idempotent.
-- ============================================================

BEGIN;

ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;

-- Backfill: clear placeholder hashes inserted by TIP-005's OAuth path
UPDATE users
   SET password_hash = NULL
 WHERE google_sub IS NOT NULL
   AND password_hash LIKE '$2b$12$oauth_placeholder%';

COMMIT;
