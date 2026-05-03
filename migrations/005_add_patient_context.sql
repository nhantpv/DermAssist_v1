-- ============================================================
-- 005_add_patient_context.sql
-- TIP-007-V1: Add patient_context JSONB column.
-- TIP-006 collected age/sex/duration/prior_treatments/relevant_history
-- from the form but had nowhere to persist. This adds the home.
-- Idempotent (uses IF NOT EXISTS).
-- ============================================================

BEGIN;

ALTER TABLE encounters ADD COLUMN IF NOT EXISTS patient_context JSONB;

-- Optional: index on common query field if we ever filter by age band.
-- Deferred — no current query needs it. Index addition would be its
-- own migration if pattern emerges.

COMMIT;
