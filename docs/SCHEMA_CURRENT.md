# SCHEMA_CURRENT.md — Authoritative DB Schema Reference

**Generated:** 2026-05-04 (post TIP-007-V1)
**Source:** live `\d` output from dev Postgres after applying migrations
`001` → `005`. This document is the canonical reference for V1; future
TIPs must cite columns from this file rather than from `BLUEPRINT.md` §7.1
(which is a design snapshot and may drift from reality).

**Migrations applied:**
- `001_init_schema.sql` — users, encounters, audit_log, kb_chunks
- `002_seed_demo_user.sql` — demo/demo seed
- `003_add_chat_messages_and_oauth.sql` — chat_messages, users.google_sub, users.email
- `004_password_hash_nullable.sql` — users.password_hash made nullable for OAuth
- `005_add_patient_context.sql` — encounters.patient_context

---

## 1. Table dumps

### users

| Column         | Type                     | Nullable | Default                       |
|----------------|--------------------------|----------|-------------------------------|
| id             | uuid                     | not null | `gen_random_uuid()`           |
| username       | varchar(64)              | not null |                               |
| password_hash  | varchar(255)             | nullable |                               |
| full_name      | varchar(128)             | nullable |                               |
| role           | varchar(32)              | not null | `'doctor'`                    |
| created_at     | timestamptz              | not null | `now()`                       |
| last_login_at  | timestamptz              | nullable |                               |
| rate_limit_rpm | integer                  | not null | `60`                          |
| google_sub     | varchar(255)             | nullable |                               |
| email          | varchar(255)             | nullable |                               |

Constraints: PK `id`, UNIQUE `google_sub`, UNIQUE `username`,
CHECK `role IN ('doctor','admin','demo')`.

### encounters

| Column               | Type            | Nullable | Default                              |
|----------------------|-----------------|----------|--------------------------------------|
| id                   | uuid            | not null | `gen_random_uuid()`                  |
| doctor_id            | uuid            | not null | FK→users(id) ON DELETE CASCADE       |
| image_path           | text            | not null |                                      |
| image_sha256         | char(64)        | not null |                                      |
| image_width          | integer         | nullable |                                      |
| image_height         | integer         | nullable |                                      |
| image_size_bytes     | integer         | nullable |                                      |
| clinical_note        | text            | nullable | **POST-redaction only**              |
| pii_redacted_count   | integer         | not null | `0`                                  |
| preflight_passed     | boolean         | not null |                                      |
| preflight_blur_score | double precision| nullable |                                      |
| preflight_brightness | double precision| nullable |                                      |
| preflight_failure    | text            | nullable |                                      |
| result_json          | jsonb           | nullable | DiagnosisOutput payload              |
| ood_flag             | boolean         | nullable |                                      |
| primary_diagnosis    | varchar(128)    | nullable |                                      |
| confidence           | double precision| nullable |                                      |
| management_tier      | varchar(32)     | nullable | CHECK `home_care…emergency`          |
| doctor_final_dx      | text            | nullable |                                      |
| doctor_final_tier    | varchar(32)     | nullable |                                      |
| doctor_notes         | text            | nullable |                                      |
| doctor_completed_at  | timestamptz     | nullable |                                      |
| created_at           | timestamptz     | not null | `now()`                              |
| expires_at           | timestamptz     | not null | `now() + '90 days'::interval`        |
| deleted_at           | timestamptz     | nullable |                                      |
| patient_context      | jsonb           | nullable | **added in 005_add_patient_context** |

Indexes: `idx_encounters_doctor (doctor_id, created_at DESC) WHERE deleted_at IS NULL`,
`idx_encounters_expires (expires_at) WHERE deleted_at IS NULL`.

**Known gaps (V1 closed beta scope):**

- `expires_at` defaults to `created_at + 90 days`, but no scheduled job
  deletes expired rows. Manual cleanup via SQL if needed. V2: add a
  pg_cron job or Railway scheduled task to soft-delete (`deleted_at = NOW()`)
  rows where `expires_at < NOW() AND deleted_at IS NULL`.
- Encounter deletion UI does not exist. Doctors cannot delete their
  own encounters from the app. V2.
- `encounters_list` query is capped at 50 rows (TIP-011). No UI
  pagination — newest 50 wins. V2: cursor-based pagination.

### chat_messages

| Column       | Type         | Nullable | Default              |
|--------------|--------------|----------|----------------------|
| id           | uuid         | not null | `uuid_generate_v4()` |
| encounter_id | uuid         | not null | FK→encounters(id) CASCADE |
| role         | varchar(20)  | not null | CHECK `user/assistant/system` |
| content      | text         | not null |                      |
| citations    | jsonb        | nullable |                      |
| created_at   | timestamptz  | not null | `now()`              |
| token_count  | integer      | nullable |                      |

### audit_log

| Column         | Type         | Nullable | Notes                                |
|----------------|--------------|----------|--------------------------------------|
| id             | bigserial    | not null | PK                                   |
| encounter_id   | uuid         | nullable | FK→encounters(id) ON DELETE SET NULL |
| doctor_id      | uuid         | nullable | FK→users(id) ON DELETE SET NULL      |
| event_type     | varchar(48)  | not null | informational enum (see migration 001) |
| ts             | timestamptz  | not null | `now()`                              |
| model_version  | varchar(64)  | nullable |                                      |
| prompt_version | varchar(32)  | nullable |                                      |
| rag_chunk_ids  | text[]       | nullable |                                      |
| image_sha256   | char(64)     | nullable |                                      |
| output_sha256  | char(64)     | nullable |                                      |
| latency_ms     | integer      | nullable |                                      |
| input_tokens   | integer      | nullable |                                      |
| output_tokens  | integer      | nullable |                                      |
| details        | jsonb        | nullable |                                      |

**audit_log is currently UNUSED by any code path.** The orchestrator
in TIP-010 will populate it. Until then, the table sits empty in dev.

### kb_chunks

| Column         | Type         | Nullable | Default              |
|----------------|--------------|----------|----------------------|
| id             | uuid         | not null | `gen_random_uuid()`  |
| doc_id         | varchar(64)  | not null |                      |
| source_url     | text         | nullable |                      |
| section_title  | varchar(255) | nullable |                      |
| chunk_index    | integer      | not null |                      |
| text           | text         | not null |                      |
| text_tsv       | tsvector     | nullable | trigger-populated    |
| embedding      | vector(384)  | nullable |                      |
| condition_tags | text[]       | nullable |                      |
| token_count    | integer      | nullable |                      |
| created_at     | timestamptz  | not null | `now()`              |

Indexes: GIN on `text_tsv`, HNSW on `embedding`, GIN on `condition_tags`.
Trigger `kb_chunks_tsv_update` keeps `text_tsv` in sync with `text`.

**kb_chunks is currently UNUSED by code paths.** TIP-008 (RAG retrieval)
will read from it.

---

## 2. Code → schema column reference table

Every `text("…")` raw SQL string in `backend/`. Audit was performed
against the working tree (which includes uncommitted TIP-006 / TIP-007 work).

| File:line | Statement | Tables | Columns referenced | All in schema? |
|---|---|---|---|---|
| backend/main.py:28 | `SELECT 1` | — | — | n/a (lifespan ping) |
| backend/auth.py:140-144 | `SELECT … FROM users WHERE username = :u` | users | id, username, role, rate_limit_rpm, email | ✅ |
| backend/routes/auth.py:38-43 | `SELECT … FROM users WHERE username = :u` | users | id, username, password_hash, role | ✅ |
| backend/routes/auth.py:55 | `UPDATE users SET last_login_at=NOW() WHERE id=…` | users | id, last_login_at | ✅ |
| backend/routes/auth.py:115-120 | `SELECT … FROM users WHERE google_sub = :s` | users | id, username, role, google_sub | ✅ |
| backend/routes/auth.py:126-130 | `UPDATE users SET last_login_at=NOW(), email=:e WHERE google_sub=:s` | users | last_login_at, email, google_sub | ✅ |
| backend/routes/auth.py:137-152 | `INSERT INTO users (…) ON CONFLICT (username) DO UPDATE …` | users | username, password_hash, role, google_sub, email, rate_limit_rpm, created_at, last_login_at | ✅ |
| backend/routes/encounters.py:99-110 | `SELECT … FROM encounters WHERE doctor_id=… AND deleted_at IS NULL` (list) | encounters | id, created_at, primary_diagnosis, management_tier, doctor_completed_at, doctor_id, deleted_at | ✅ |
| backend/routes/encounters.py:130-140 | `SELECT … LIMIT 5` (recent for new form) | encounters | id, created_at, primary_diagnosis, management_tier, doctor_id, deleted_at | ✅ |
| backend/routes/encounters.py:188-198 | `SELECT … LIMIT 5` (recent for preflight rerender) | encounters | id, created_at, primary_diagnosis, management_tier, doctor_id, deleted_at | ✅ |
| backend/routes/encounters.py:225-251 | `INSERT INTO encounters (…)` | encounters | doctor_id, image_path, image_sha256, image_size_bytes, clinical_note, pii_redacted_count, preflight_passed, preflight_blur_score, preflight_brightness, preflight_failure, patient_context, result_json, created_at | ✅ (patient_context requires migration 005) |
| backend/routes/encounters.py:265-281 | `SELECT … FROM encounters WHERE id=… AND doctor_id=… AND deleted_at IS NULL` (detail) | encounters | id, created_at, image_sha256, image_path, clinical_note, pii_redacted_count, preflight_passed, preflight_failure, result_json, ood_flag, primary_diagnosis, confidence, management_tier, doctor_final_dx, doctor_final_tier, doctor_notes, doctor_completed_at, doctor_id, deleted_at | ✅ |
| backend/routes/encounters.py:286-294 | `SELECT … FROM chat_messages WHERE encounter_id=…` | chat_messages | role, content, citations, encounter_id, created_at | ✅ |
| backend/routes/encounters.py:319-329 | `UPDATE encounters SET doctor_final_dx,doctor_final_tier,doctor_notes,doctor_completed_at WHERE id=…` (finalize) | encounters | id, doctor_id, deleted_at, doctor_final_dx, doctor_final_tier, doctor_notes, doctor_completed_at | ✅ |

**Mismatches found:** **0** (all column references map to live schema).
**Level 2 escalations triggered:** **0**.

---

## 3. Naming conventions and intentional aliases

The form/template layer and the DB layer use different vocabularies in
several places. These aliases are intentional and **must not be renamed
in V1** (changes deferred to a Blueprint Amendment 002 if the team wants
to normalize for V2).

| Form / template / Pydantic name | DB column        | Where the alias happens |
|---------------------------------|------------------|-------------------------|
| `doctor_diagnosis` (form field) | `doctor_final_dx` (DB) | Mapped in `backend/routes/encounters.py` finalize handler (`:dx`) and `_row_to_record` (sets `record['doctor_diagnosis']` from `doctor_final_dx`) |
| `doctor_tier` (form field)      | `doctor_final_tier` (DB) | Same handler / record mapping |
| `doctor_finalized` (template flag) | derived: `doctor_completed_at IS NOT NULL` | SELECT computes it; `_row_to_record` also computes from row |
| `diagnosis` (template / record) | `result_json` (DB) | `_row_to_record` aliases `result_json` → `record['diagnosis']` |
| `image_url` (template)          | derived from `image_path` | `_row_to_record` builds `/uploads/{filename}` from path |
| `id_short` (template)           | derived from `id[:8]` | `_row_to_record` |

The earlier TIP-006 deviation list (in `backend/routes/encounters.py` docstring) is canonical:

```
TIP-006 form / template       → Actual schema (migrations 001 + 005)
clinical_note_redacted        → clinical_note (single column; pre-redaction never persisted)
pii_redaction_count           → pii_redacted_count
patient_context_json          → patient_context (NEW in 005)
```

**Note:** the historical alias `pii_redaction_count` (Pydantic / spec)
vs `pii_redacted_count` (DB) was settled in favor of the DB name. The
result template uses `record.pii_redacted_count` directly — no in-Python
alias. Confirmed by template grep:

```
backend/templates/encounter_result.html:45  {% if record.pii_redacted_count and record.pii_redacted_count > 0 %}
backend/templates/encounter_result.html:46  ⓘ {{ record.pii_redacted_count }} thông tin nhận dạng đã được loại bỏ.
```

---

## 4. Reserved / unused-for-now columns

These columns exist in schema but are not yet read or written by any
code path. They are reserved for downstream TIPs:

| Table | Columns | Reserved for |
|---|---|---|
| encounters | `image_width`, `image_height` | (no current consumer; spec keeps for future preflight rules) |
| audit_log  | all columns | TIP-010 (orchestrator) |
| kb_chunks  | all columns | TIP-008 (RAG ingestion + retrieval) |

If TIP-008 / TIP-010 ship without using these, audit will need to either
(a) remove the columns or (b) accept them as truly reserved. For now,
they're correct.
