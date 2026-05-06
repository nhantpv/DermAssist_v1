# TIPs Landed — V1 Build Log

Complete chronological record of every TIP that has shipped (or is
in working tree pending commit) toward the DermAssist VN V1 closed
clinician beta. This is the canonical engineering-process artifact
for VinUni evaluators.

**Methodology:** Vibecode Kit v6.0 — Contractor (design) / Builder
(implement) / Homeowner (approve) role separation, with each TIP a
self-contained Task Instruction Pack. See
[BLUEPRINT-AMENDMENT-001.md](../../user_data/BLUEPRINT-AMENDMENT-001.md) §7.

---

## Wave 1 — Project bootstrap + data prep

| TIP | Title | Status | Commit |
|---|---|---|---|
| TIP-000 | Repository scaffold | DONE | `e563d8b` |
| TIP-000 (redux) + leftovers | Pickup batch (TIP-000-redux + TIP-002A + TIP-003B + TIP-004) | DONE | `50568f3` |
| TIP-001 | Dataset audit notebook (Risk C mitigation) | DONE | `15e8c11` |
| TIP-001A | Augment datasets, finalize 8-condition scope | DONE | `7e07aa7` |
| TIP-002 | RAG corpus pipeline (notebook + scripts; chunks.json deferred) | DONE | `83a8a2f` |
| TIP-002A | Swap EasyOCR for Marker (PDF→Markdown) | DONE | `e8d9af0` |
| TIP-003 | Visual descriptions notebook (Qwen self-describe) | DONE | `86fb465` |
| TIP-003A | Multi-source visual descriptions + quality checks | DONE | `6e81232` |
| TIP-003B | Consolidated fixes (notebook + build script + deps) | DONE | `2bd96e2` |
| TIP-003C | `peak_vram_gb` via nvidia-smi (subprocess-blind torch fix) | DONE | `b196405` |
| TIP-004 | DB migrations 001 + 002 (init schema, demo seed) | DONE | (folded into `50568f3` pickup batch) |
| TIP-004B | Build-script cleanup + README guidance | DONE | `f8b9bfc`, `456da32` |

## Wave 2 — Demo track (decommissioned)

A throwaway parallel demo using OpenAI gpt-4o-mini directly. Validated
the end-to-end flow on Day 0; superseded by the canonical backend.
Decommissioned in TIP-CLEANUP-V1 (see Wave 5).

| TIP | Title | Status | Commit |
|---|---|---|---|
| TIP-DEMO | Scaffold `demo/` + pyproject demo group | ARCHIVED | `3e08ae2` |
| TIP-DEMO | README pointer to demo/ | ARCHIVED | `25c2901` |
| TIP-DEMO-002 | Image + persistence | NOT EXECUTED | — (canonical superseded before this fired) |

## Wave 3 — Backend canonical V1

| TIP | Title | Status | Commit |
|---|---|---|---|
| TIP-005 | Backend core (config, db, auth, schemas, main) | DONE | `7f67e81` |
| TIP-005 | Routes (auth, pages) + tests | DONE | `308adec` |
| TIP-006-V1 | Canonical frontend (HTMX templates, encounter create/list/detail/finalize, chat stub) | **DONE in working tree, UNCOMMITTED** | — |
| TIP-007-V1 | Image preflight (Laplacian blur) + Vietnamese-aware PII redaction + `patient_context` column | **DONE in working tree, UNCOMMITTED** | — |

## Wave 4 — Hygiene

| TIP | Title | Status | Commit |
|---|---|---|---|
| TIP-CLEANUP-V1 | Project hygiene + consistency audit (this TIP) | **IN PROGRESS — working tree only** | — |

## Wave 5 — Coming next (per BLUEPRINT-AMENDMENT-001 §2)

| TIP | Title | Status |
|---|---|---|
| TIP-008-V1 | RAG retrieval (BM25 + dense + RRF) | DONE | 5fc28c2 |
| TIP-009-V1 | VLM client (OpenAI provider) | DONE | d68559a |
| TIP-010-V1 | Orchestrator + chat wire-up | DONE | 2a74e70 |
| TIP-011-V1 | Encounter polish + scoping audit | DONE | 69b8d8e |
| TIP-012-V1 | Eval harness + HTML report | DONE | 51178d6 |
| TIP-013-V1 | Railway deploy | DONE | ade0c45 |
| TIP-013-FIXUP-* | Deploy hotfixes | DONE | (3 commits) |
| TIP-014-V1 | VERIFY | DONE | e31898b, 94b0a2b |

---

## Audit-trail gaps

The following TIPs landed in working tree (verified via tests + DB
state) but **do not have clean `TIP-NNN:` commit messages**. To audit
them today, you must read the working-tree diff or the in-conversation
TIP completion reports — not `git log`.

- **TIP-006-V1** — uncommitted; introduces:
  `backend/routes/encounters.py`, `backend/routes/chat.py`,
  `backend/static/`, `backend/templates/`, plus
  `migrations/004_password_hash_nullable.sql`, `tests/integration/test_pages.py`,
  `tests/unit/test_template_rendering.py`.
- **TIP-007-V1** — uncommitted; introduces:
  `backend/preflight.py`, `backend/text/`,
  `migrations/005_add_patient_context.sql`,
  `tests/unit/test_preflight.py`, `tests/unit/test_pii.py`,
  `tests/integration/test_encounter_preflight.py`. Modifies
  `backend/routes/encounters.py` (preflight + redaction wire-up) and
  `backend/templates/encounter_result.html` (redaction notice in stub
  branch).
- **TIP-CLEANUP-V1** (this TIP) — uncommitted; introduces:
  `docs/SCHEMA_CURRENT.md`, `docs/TIPS_LANDED.md`; refreshes
  `README.md`, `docs/setup.md`; removes `[demo]` extra from
  `pyproject.toml`; `git rm -r demo/` (working tree only).

These three TIPs need to land as their own commits before the
build log is fully reconstructable from `git log` alone.

## Counts

- TIPs **committed** to git: **16**
- TIPs **DONE in working tree, awaiting commit**: **3** (TIP-006-V1,
  TIP-007-V1, TIP-CLEANUP-V1)
- TIPs **NOT STARTED** (per Amendment 001 §2 in-scope list):
  **7** (TIP-008 → TIP-014)
- TIPs **ARCHIVED / NOT EXECUTED**: **3** (demo track)
