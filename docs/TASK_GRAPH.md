# TASK GRAPH — DermAssist VN MVP

> **Project:** DermAssist VN — VLM Clinical Decision Support (MVP)
> **Reference:** `BLUEPRINT.md` (single source of truth for design decisions)
> **Methodology:** Vibecode Kit v6.0
> **Status:** Generated 2026-04-28 — TIPs in `tips/` directory

---

## Overview

15 TIPs total (TIP-000 through TIP-014). Each TIP is self-contained and references the Blueprint for design context. **Do NOT modify the Blueprint during build** — escalate via Level 2 Report instead.

## Dependency graph

```
                    TIP-000: Project scaffold
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
   TIP-001: Dataset    TIP-002: RAG     TIP-003: Visual descs
   audit (Colab)       corpus (Colab)   (Colab + Qwen)
            │                 │                 │
            │                 ▼                 │
            │          TIP-004: DB              │
            │          migrations               │
            │                 │                 │
            └─────────┬───────┴─────────┬───────┘
                      ▼                 ▼
              TIP-005: Backend core   TIP-006: Frontend
              (auth, schemas, db)     (HTMX 3 screens)
                      │                 │
                      ▼                 │
              TIP-007: Preflight + PII  │
                      │                 │
                      ▼                 │
              TIP-008: RAG retrieval    │
                      │                 │
                      ▼                 │
              TIP-009: VLM client       │
                      │                 │
                      ▼                 │
              TIP-010: Orchestrator     │
                      │                 │
                      └────────┬────────┘
                               ▼
                       TIP-011: Integration
                               │
                               ▼
                       TIP-012: Eval harness
                               │
                               ▼
                       TIP-013: Deploy (Modal+Vercel)
                               │
                               ▼
                       TIP-014: VERIFY
```

## Execution sequence (recommended)

The Colab TIPs (001/002/003) and local scaffold (TIP-000) can run **in parallel** by different operators or sessions. Once Colab artifacts land in `data/`, local development unblocks.

| Wave | TIPs | Can run in parallel? | Estimated total |
|---|---|---|---|
| **Wave 1 — Foundation** | TIP-000 + TIP-001 + TIP-002 + TIP-003 | Yes, fully parallel | ~1 day |
| **Wave 2 — Storage** | TIP-004 | Sequential after Wave 1 | ~2 hours |
| **Wave 3 — Services** | TIP-005, then TIP-006 in parallel from here | Partial | ~1 day |
| **Wave 4 — Pipeline** | TIP-007, TIP-008, TIP-009, TIP-010 (sequential) | No | ~1.5 days |
| **Wave 5 — Integration** | TIP-011 | After 6+10 | ~half day |
| **Wave 6 — Quality** | TIP-012 | After 11 | ~half day |
| **Wave 7 — Ship** | TIP-013 | After 12 | ~half day |
| **Wave 8 — Verify** | TIP-014 | After 13 | ~half day |

**Total estimated effort:** ~5–6 working days for a single Builder.

## TIP catalog

| TIP | Title | Priority | Depends on | Phase |
|---|---|---|---|---|
| TIP-000 | Project scaffold | P0 | — | Build |
| TIP-001 | Dataset audit (Risk C) | P0 | TIP-000 | Build |
| TIP-002 | RAG corpus pipeline | P0 | TIP-000 | Build |
| TIP-003 | Visual descriptions (Qwen self-describe) | P0 | TIP-000 | Build |
| TIP-004 | Database migrations | P0 | TIP-000 | Build |
| TIP-005 | Backend core (auth + schemas + db wiring) | P0 | TIP-004 | Build |
| TIP-006 | Frontend templates (HTMX, 3 screens) | P0 | TIP-005 | Build |
| TIP-007 | Image preflight + PII redaction guardrail | P0 | TIP-005 | Build |
| TIP-008 | RAG retrieval (BM25 + dense + RRF) | P0 | TIP-002, TIP-005 | Build |
| TIP-009 | VLM client (vLLM + guided_json + retry) | P0 | TIP-003, TIP-005 | Build |
| TIP-010 | Orchestrator + output guardrails | P0 | TIP-007, 008, 009 | Build |
| TIP-011 | Integration (encounter pipeline E2E) | P0 | TIP-006, TIP-010 | Build |
| TIP-012 | Eval harness + run metrics | P0 | TIP-011 | Verify |
| TIP-013 | Modal + Vercel deploy (Surface A) | P1 | TIP-012 | Deploy |
| TIP-014 | VERIFY (RRI Reverse) | P0 | TIP-013 | Verify |

## How to execute a TIP

1. Open the TIP file in `tips/TIP-XXX-name.md`
2. Copy the entire content
3. Paste into Claude Code (Builder) along with the standard handover preamble:

```markdown
# Vibecode Kit v6.0 — Task Instruction Pack

## ROLE
You are the BUILDER in Vibecode Kit v6.0.
The Contractor (Claude Chat) and Homeowner have AGREED on the design.

## ABSOLUTE RULES
1. IMPLEMENT exactly per TIP specification below
2. DO NOT change architecture / structure
3. DO NOT add features outside TIP
4. DO NOT change tech stack / dependencies (unless TIP requires)
5. SELF-TEST per acceptance criteria
6. REPORT per Completion Report format
7. Encounter conflict → REPORT in detail, DO NOT self-decide

## PROJECT CONTEXT
This is the DermAssist VN MVP — a VLM-based clinical decision support
demo for Vietnamese dermatology. See BLUEPRINT.md for full design.
Apache 2.0, single-user T4 GPU, Modal+Vercel+Supabase deployment.

## TASK INSTRUCTION PACK
[paste TIP content here]

## AFTER COMPLETION
Create COMPLETION REPORT per Vibecode v6.0 format.
```

4. Builder produces code + Completion Report
5. Bring Completion Report back to Chủ thầu (Claude Chat) for review
6. Move to next TIP per dependency graph

## Escalation paths

- **Level 1** (Builder self-resolves): variable names, code style, minor pattern choice
- **Level 2** (Builder → Chủ thầu): spec ambiguity, conflict between TIP and existing code, performance trade-offs. Builder writes Escalation Report; user pastes back into Chat.
- **Level 3** (Chủ thầu → Chủ nhà): scope change, architectural pivot, business rule conflict, security concern. Chủ thầu writes Escalation Report.

## Completion Report standard

After each TIP, Builder writes:

```markdown
## COMPLETION REPORT — TIP-[XXX]

**STATUS:** DONE / PARTIAL / BLOCKED

**FILES CHANGED:**
- Created: [list + purpose]
- Modified: [list + change description]

**TEST RESULTS:**
- Acceptance criteria tested: [X/Y passed]
- Details: [pass/fail per criteria]

**ISSUES DISCOVERED:**
- [Issue]: [severity] — [description] — [suggestion]

**DEVIATIONS FROM SPEC:**
- [Deviation]: [what] — [why] — [impact]

**SUGGESTIONS FOR CHỦ THẦU:**
- [Suggestion]: [observation] — [recommendation]
```

---

## Batch status

| Batch | TIPs | Generated | Status |
|---|---|---|---|
| 1 — Foundation | TIP-000 through TIP-004 | ✅ Yes | Awaiting review |
| 2 — Runtime + Quality | TIP-005 through TIP-014 | ⏳ Pending | Generated next turn after user approves Batch 1 quality |

---

*Task Graph v1.0 — DermAssist VN MVP*
