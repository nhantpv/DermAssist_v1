# Path to Production (Surface B)

This document describes the migration path from Surface A (demo) to
Surface B (on-premise hospital deployment). Surface B is **deferred**
in v1 — see Blueprint §11 for rationale.

## Migration components

| MVP (Surface A) | Production (Surface B) |
|---|---|
| Modal serverless GPU | On-prem GPU server (T4/L40/A100) running vLLM |
| Vercel hosted frontend | Hospital nginx + same templates |
| Supabase Postgres | Local Postgres in Docker / VM |
| Public-internet access | Hospital LAN only |
| Demo banner (red) | Hospital-grade audit banner |
| JWT only | LDAP/AD/SSO |
| Public dataset images | IRB-approved real patient images |

## Triggering criteria

Begin Surface B migration when:
- Hospital partner committed
- IRB approval obtained
- GPU hardware specified
- Compliance review (Luật KCB + Nghị định 13/2023) passed

## Estimated migration effort

Surface B is largely a deployment swap, not a rewrite. Estimated 2–3 weeks
of additional work.

## OCR / PDF Conversion at Build Time

The RAG corpus pipeline (TIP-002 / TIP-002A) uses **Marker**
(datalab-to/marker) to convert clinical guideline PDFs to Markdown.
Marker is GPL-3.0 licensed and used as a **build-time tool only** —
it is NOT linked into or shipped with the runtime backend.

**Implication for Surface B (commercial hospital deployment):**

- Marker itself can be installed and run by the hospital at index
  time; the resulting Markdown / `chunks.json` is theirs to use under
  the hospital's normal data ownership.
- Marker uses **Surya OCR** (datalab-to/surya), which has a
  commercial-use clause: free for organizations under $5M annual
  revenue OR $5M total funding; otherwise requires a commercial
  license from Datalab.
- For hospitals over the threshold: either purchase Surya commercial
  license, OR replace Marker with a fully-open alternative (EasyOCR,
  PaddleOCR, or Tesseract) at index time. The runtime backend is
  unaffected — only the offline `data/chunks.json` build step
  changes.

For MVP / research / portfolio use, both Marker and Surya are free.
