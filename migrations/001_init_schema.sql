-- ============================================================
-- 001_init_schema.sql
-- DermAssist VN — Initial database schema
-- Source: BLUEPRINT.md §7.1 (verbatim, with IF NOT EXISTS for idempotency)
-- Wrapped in BEGIN/COMMIT for atomicity.
-- ============================================================

BEGIN;

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================================
-- users
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username        VARCHAR(64) UNIQUE NOT NULL,
  password_hash   VARCHAR(255) NOT NULL,            -- bcrypt
  full_name       VARCHAR(128),
  role            VARCHAR(32) NOT NULL DEFAULT 'doctor'
                     CHECK (role IN ('doctor', 'admin', 'demo')),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_login_at   TIMESTAMPTZ,
  rate_limit_rpm  INT NOT NULL DEFAULT 60           -- demo gets 10
);

-- ============================================================
-- encounters
-- ============================================================
CREATE TABLE IF NOT EXISTS encounters (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  doctor_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

  -- Image (path + hash, never blob)
  image_path           TEXT NOT NULL,
  image_sha256         CHAR(64) NOT NULL,
  image_width          INT,
  image_height         INT,
  image_size_bytes     INT,

  -- Inputs
  clinical_note        TEXT,                         -- POST-redaction only
  pii_redacted_count   INT NOT NULL DEFAULT 0,       -- # of tokens redacted

  -- Preflight
  preflight_passed     BOOLEAN NOT NULL,
  preflight_blur_score FLOAT,
  preflight_brightness FLOAT,
  preflight_failure    TEXT,                         -- reason string, NULL if passed

  -- AI Output
  result_json          JSONB,                        -- DiagnosisOutput
  ood_flag             BOOLEAN,
  primary_diagnosis    VARCHAR(128),
  confidence           FLOAT,
  management_tier      VARCHAR(32) CHECK (
                         management_tier IN
                         ('home_care','outpatient_72h','outpatient_24h','emergency')
                       ),

  -- Doctor's final input (Risk E — optional, post-hoc)
  doctor_final_dx      TEXT,
  doctor_final_tier    VARCHAR(32),
  doctor_notes         TEXT,
  doctor_completed_at  TIMESTAMPTZ,

  -- Lifecycle
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at           TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '90 days',
  deleted_at           TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_encounters_doctor    ON encounters(doctor_id, created_at DESC)
  WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_encounters_expires   ON encounters(expires_at)
  WHERE deleted_at IS NULL;

-- ============================================================
-- audit_log
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_log (
  id              BIGSERIAL PRIMARY KEY,
  encounter_id    UUID REFERENCES encounters(id) ON DELETE SET NULL,
  doctor_id       UUID REFERENCES users(id) ON DELETE SET NULL,

  event_type      VARCHAR(48) NOT NULL,            -- see enum below
  ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  -- Versioning (for reproducibility & rollback)
  model_version   VARCHAR(64),                     -- 'qwen2.5-vl-7b-int4-awq-v1'
  prompt_version  VARCHAR(32),                     -- 'v1.0.0'

  -- Provenance
  rag_chunk_ids   TEXT[],
  image_sha256    CHAR(64),
  output_sha256   CHAR(64),

  -- Performance
  latency_ms      INT,
  input_tokens    INT,
  output_tokens   INT,

  -- Free-form
  details         JSONB
);

-- event_type values (informational, not enforced):
--   'auth_login', 'auth_failed'
--   'encounter_create_start', 'preflight_pass', 'preflight_fail'
--   'pii_redacted', 'injection_detected'
--   'rag_retrieve', 'vlm_call', 'vlm_retry', 'vlm_fallback_ood'
--   'output_validated', 'encounter_complete'
--   'encounter_deleted', 'encounter_expired'
--   'doctor_finalized'

CREATE INDEX IF NOT EXISTS idx_audit_encounter ON audit_log(encounter_id, ts);
CREATE INDEX IF NOT EXISTS idx_audit_doctor    ON audit_log(doctor_id, ts);
CREATE INDEX IF NOT EXISTS idx_audit_event     ON audit_log(event_type, ts);

-- ============================================================
-- kb_chunks
-- ============================================================
CREATE TABLE IF NOT EXISTS kb_chunks (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  doc_id          VARCHAR(64) NOT NULL,            -- 'qd-4416-byt-2023'
  source_url      TEXT,
  section_title   VARCHAR(255),
  chunk_index     INT NOT NULL,
  text            TEXT NOT NULL,
  text_tsv        TSVECTOR,
  embedding       VECTOR(384),                     -- multilingual-e5-small
  condition_tags  TEXT[],                          -- ['atopic_dermatitis']
  token_count     INT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kb_chunks_tsv  ON kb_chunks USING GIN (text_tsv);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_emb  ON kb_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_tags ON kb_chunks USING GIN (condition_tags);

-- Auto-populate tsv on insert/update
-- Use DO block to make trigger creation idempotent
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'kb_chunks_tsv_update'
  ) THEN
    CREATE TRIGGER kb_chunks_tsv_update
    BEFORE INSERT OR UPDATE ON kb_chunks
    FOR EACH ROW EXECUTE FUNCTION
      tsvector_update_trigger(text_tsv, 'pg_catalog.simple', text);
  END IF;
END
$$;

COMMIT;
