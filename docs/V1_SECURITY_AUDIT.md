# V1 Security Audit — Encounter & Chat Scoping

**Generated:** TIP-011-V1.
**Scope:** every SQL query in `backend/routes/encounters.py` and
`backend/routes/chat.py` that touches `encounters` or `chat_messages`.
Authentication and OAuth surfaces are out of scope for this document
(deferred to TIP-014 VERIFY).

The threat we are mitigating: doctor A is authenticated, but uses a
crafted URL or form post to read or modify doctor B's encounter,
chat history, or uploaded image.

---

## 1. Query inventory

| # | File:line | Verb | Table | WHERE clause includes ownership? | Notes |
|---|-----------|------|-------|----------------------------------|-------|
| 1 | `backend/routes/encounters.py:79-91` | SELECT | encounters | ✅ `doctor_id = :uid AND deleted_at IS NULL` | List page; LIMIT 50 (TIP-011). |
| 2 | `backend/routes/encounters.py:110-120` | SELECT | encounters | ✅ `doctor_id = :uid AND deleted_at IS NULL LIMIT 5` | New-form recents. |
| 3 | `backend/routes/encounters.py:179-189` | SELECT | encounters | ✅ `doctor_id = :uid AND deleted_at IS NULL LIMIT 5` | Preflight-fail rerender recents. |
| 4 | `backend/routes/encounters.py:215-231` | SELECT | encounters | ✅ `id = :eid AND doctor_id = :uid AND deleted_at IS NULL` | Detail page. Returns 404 on miss. |
| 5 | `backend/routes/encounters.py:236-244` | SELECT | chat_messages | ⚠ `WHERE encounter_id = :eid` only | **Indirect:** the SELECT at #4 above runs first and 404s if the doctor doesn't own the encounter. The chat_messages query never executes for unauthorized encounter_ids. Acceptable given the upstream check. |
| 6 | `backend/routes/encounters.py:269-287` | UPDATE | encounters | ✅ `id = :eid AND doctor_id = :uid AND deleted_at IS NULL` | Finalize. `rowcount == 0` → 404. |
| 7 | `backend/routes/encounters.py:294-330` | SELECT | encounters | ✅ `image_sha256 = :sha AND doctor_id = :uid AND deleted_at IS NULL` | **Fixed in TIP-011.** Uploaded image serve now ownership-gated. |
| 8 | `backend/routes/chat.py:47-58` | SELECT | encounters | ✅ `id = :eid AND doctor_id = :uid AND deleted_at IS NULL` | Chat ownership gate. 404s before any chat_messages write. |
| 9 | `backend/routes/chat.py:69-75` | INSERT | chat_messages | ⚠ no WHERE (it's an INSERT) | **Indirect:** #8 runs first; insert only reached if owner. |
| 10 | `backend/routes/chat.py:79-89` | SELECT | chat_messages | ⚠ `WHERE encounter_id = :eid` only | Same as #5 — protected by #8 upstream. |
| 11 | `backend/routes/chat.py:110-120` | INSERT | chat_messages | ⚠ no WHERE (INSERT) | Same as #9. |
| 12 | `backend/routes/chat.py:125-136` | INSERT | chat_messages | ⚠ no WHERE (INSERT) | Same as #9. |

**Verdict:** all 12 queries are protected. Queries marked ⚠ have no
ownership clause directly, but each lives downstream of an explicit
ownership-gating SELECT in the same handler that 404s before reaching
the unprotected query. The only previously-unprotected query (#7,
`/uploads/{filename}`) was fixed in TIP-011.

## 2. Fixes landed in TIP-011

### 2.1 `GET /uploads/{filename}` ownership gate

Before TIP-011: any authenticated doctor could fetch any uploaded
image bytes if they knew or guessed the filename (a 64-char SHA-256
hex string). Realistic exploit difficulty: low if the SHA is leaked
in URLs (it is — the result page references it directly).

After TIP-011: the handler computes `sha = filename.split(".")[0]` and
runs a one-row existence check:

```sql
SELECT 1 FROM encounters
 WHERE image_sha256 = :sha
   AND doctor_id = CAST(:uid AS uuid)
   AND deleted_at IS NULL
 LIMIT 1
```

A miss returns 404 (never 403) so existence isn't probeable across
doctors. The handler also rejects filenames whose stem is not a
64-char hex sha early with 404, blocking enumeration of arbitrary
file paths.

Edge case: if **two doctors upload the same image** (same bytes →
same SHA, dedup hit), each doctor's `encounters` row owns the SHA
independently, and either can read the shared file. This is correct
behavior — ownership is per-encounter, not per-byte-stream.

## 3. Out of scope (deferred to TIP-014 VERIFY)

- Login + JWT validation surfaces (`backend/routes/auth.py`)
- Google OAuth callback (`/auth/google/callback`)
- Static-file serve via FastAPI `StaticFiles` mount (no auth gate;
  intended — only contains `static/dermassist-icon.svg` etc.)
- CSRF protections — relying on `SameSite=Lax` cookies for V1 closed beta
- Rate limiting — `users.rate_limit_rpm` column exists but is not
  enforced anywhere

A wider TIP-014 audit should sweep these.
