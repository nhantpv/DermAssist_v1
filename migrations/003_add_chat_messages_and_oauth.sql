-- ============================================================
-- 003_add_chat_messages_and_oauth.sql
-- TIP-005-CANONICAL-V1: chat_messages table + OAuth columns on users
-- Source: BLUEPRINT-AMENDMENT-001.md §3.2
-- Additive only. Idempotent (uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).
-- ============================================================

BEGIN;

-- Chat messages: one row per turn in a doctor-AI conversation
CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    encounter_id UUID NOT NULL REFERENCES encounters(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    citations JSONB,                       -- chunk_ids list, NULL for user turns
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    token_count INTEGER                    -- nullable, set by orchestrator if known
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_encounter
    ON chat_messages(encounter_id, created_at);

-- Google OAuth columns on users (NULL for local accounts)
ALTER TABLE users ADD COLUMN IF NOT EXISTS google_sub VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(255);

-- Unique constraint on google_sub when present (PostgreSQL allows multi-NULL)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_google_sub_key'
    ) THEN
        ALTER TABLE users ADD CONSTRAINT users_google_sub_key UNIQUE (google_sub);
    END IF;
END$$;

COMMIT;
