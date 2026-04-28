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
