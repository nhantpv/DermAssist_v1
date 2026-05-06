# Deploy Guide — DermAssist VN on Railway (Surface A)

Production-deploy runbook for the V1 closed clinician beta.
Targets a public Railway URL serving a single FastAPI replica plus
a managed Postgres with pgvector. After the steps below, evaluators
visit `https://<your-app>.up.railway.app` and the demo flow works
end-to-end (login → upload → diagnosis → chat → result).

For local dev setup see [setup.md](setup.md). For the canonical DB
column reference see [SCHEMA_CURRENT.md](SCHEMA_CURRENT.md).

---

## 1. Prerequisites

- A Railway account ([railway.app](https://railway.app)). Free tier works
  for Option B/C cold-start; **hobby plan ($5/month) is required for
  Option A** (always-warm replica) — see §3.
- An OpenAI API key with access to `gpt-4o-mini` (vision-capable).
- Local dev environment confirmed working: `pytest` green, `/health`
  returns 200, `demo / demo` login works on localhost. **Do this
  sanity check before touching production.**
- (Optional) A Google Cloud Console OAuth client if you want
  "Sign in with Google" enabled in production.

### 1.1 GitHub remote (required first)

Railway auto-deploys from a GitHub repository, so before anything in
the Railway dashboard works, the local repo must have a GitHub remote
and the latest commits must be pushed.

```bash
# 1. Create a new repository on github.com (private OK; Railway needs read access)
# 2. Add the remote (substitute your owner/name):
git remote add origin git@github.com:<your-username>/<repo-name>.git

# 3. Verify:
git remote -v
# Expected:
# origin  git@github.com:.../....git (fetch)
# origin  git@github.com:.../....git (push)

# 4. Push:
git push -u origin main
```

Skip this and Railway's "Deploy from GitHub" wizard in §2.1 will not
see your repo.

## 2. One-time Railway setup

The web UI is the source of truth here — `railway.json` + `Procfile`
in the repo only configure the build/run, not the dashboard state.

1. **Create the project.** Railway dashboard → **New Project** →
   **Deploy from GitHub** → select this repo → choose the branch
   (default: `main`).

2. **Attach Postgres.** From the project, **+ New** → **Database** →
   **Add PostgreSQL**. Railway provisions a managed Postgres and auto-injects
   `DATABASE_URL` into the web service's environment.

3. **Verify pgvector is available.** Open the Postgres service in the
   dashboard → **Data** tab (or **Connect** → use the provided psql
   connection string locally). Run:

   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
   ```

   Recent Railway Postgres images ship with pgvector pre-enabled.
   If `CREATE EXTENSION` fails with "extension not found", **stop and
   escalate** — you'll need a different Postgres image
   (`pgvector/pgvector:pg16` or use Supabase as a fallback per
   [Blueprint Amendment 001](../user_data/BLUEPRINT-AMENDMENT-001.md) §3.1
   pre-Amendment fallback).

4. **Set environment variables.** Web service → **Variables** tab →
   **+ New Variable** for each entry below.
   `DATABASE_URL` is auto-injected; do NOT set it manually.

   | Variable | Value | Notes |
   |---|---|---|
   | `JWT_SECRET_KEY` | 64-hex string | Generate fresh: `python -c "import secrets;print(secrets.token_hex(32))"`. Do **not** reuse the dev secret. |
   | `OPENAI_API_KEY` | `sk-…` | Same key style used for TIP-009. |
   | `BASE_URL` | `https://<assigned>.up.railway.app` | Set after Railway assigns the public domain (step 6). |
   | `LOG_LEVEL` | `INFO` | |
   | `VLM_PROVIDER` | `openai` | |
   | `VLM_MODEL` | `gpt-4o-mini` | **Do not change.** TIP-012 eval numbers are pinned to this model. |
   | `VLM_ENDPOINT` | `https://api.openai.com/v1` | |
   | `GOOGLE_CLIENT_ID` | (optional) | Set only if you want Google login. |
   | `GOOGLE_CLIENT_SECRET` | (optional) | |
   | `GOOGLE_REDIRECT_URI` | `https://<your-domain>/auth/google/callback` | Trailing slashes matter — must match Google Cloud Console exactly. |

   See [.env.production.template](../.env.production.template) for the
   committed list (no secret values).

5. **First deploy.** Railway auto-deploys on every push to the
   configured branch. The first deploy after attaching Postgres should
   pick up `Procfile` + `railway.json` + `nixpacks.toml` and run
   `scripts/start_production.sh`. Watch the deploy logs in the
   dashboard.

6. **Public domain.** Web service → **Settings** → **Networking** →
   **Generate Domain** for a free `*.up.railway.app` subdomain.
   Custom domain optional: same panel → **Add Custom Domain** →
   point a CNAME at the value Railway gives you. DNS propagation
   takes 1–60 minutes. Update `BASE_URL` and (if used) Google
   `GOOGLE_REDIRECT_URI` to match.

## 3. Cold-start mitigation chosen — **Option A (always-warm)**

The TIP-008 multilingual-e5-small embedder takes ~19s to load on the
first lifespan call. Without mitigation, the *first* user after a cold
start waits ~19s before retrieval works, which is unacceptable for a
demo URL evaluators may click any time over a 7-day window.

**Choice: Option A — always-warm replica.**

- Implemented via `"sleepApplication": false` in `railway.json`.
- Cost: $5/month Railway hobby plan. Acceptable inside the capstone
  demo budget for a 7-day evaluation period.
- UX: best of the three options. Embedder loads once at deploy/restart
  and stays in memory for the life of the replica; idle traffic does
  not put the container to sleep.
- Code: no changes needed. Lifespan already calls `warmup()` before
  yield (see `backend/main.py`); the readiness endpoint
  (`/healthz/ready`) returns 200 immediately because warmup completes
  before the app accepts HTTP traffic.

Alternative options considered and rejected:

- **Option B — `/healthz/ready` 503-until-warm + LB drain.** Free.
  Workable but trades evaluator UX (they may hit a 503 once after a
  cold restart and assume the system is broken) for cost savings.
  Implementation reserved as a future fallback if the $5/month becomes
  a hard constraint — would require gating `/healthz/ready` on a
  `_embedder_ready` flag set in the lifespan, and pointing
  `railway.json` `healthcheckPath` at `/healthz/ready`.
- **Option C — lazy load on first request.** Free, simplest. Worst
  UX: first user after each container restart pays the full ~19s.
  Hard no for evaluator-facing demo.

Verification (see §5).

## 4. Deploy

Railway auto-deploys on every push to the configured branch. The
deploy sequence:

1. **Build (Nixpacks)** — installs Python 3.11 + the libpq client
   (`psql`, used by `scripts/run_migrations.sh`), runs
   `pip install -e .[dev]`. Nixpacks config in `nixpacks.toml`.
2. **Start command** — `bash scripts/start_production.sh`, defined in
   `railway.json` and mirrored in `Procfile`. The script:
   - Runs `scripts/run_migrations.sh` (idempotent — applies migrations
     001 → 005 in order, skips already-applied ones).
   - Counts `kb_chunks` rows. If zero, runs `python scripts/seed_kb_chunks.py`
     to load the 339 QĐ-4416 chunks. If non-zero, skips reseed (avoids
     re-embedding 339 rows on every push).
   - `exec`s `uvicorn backend.main:app --host 0.0.0.0 --port $PORT --workers 1 --log-level info`.
3. **Healthcheck** — Railway hits `/healthz` (path from `railway.json`).
   On 200, the new replica receives traffic and the previous deploy is
   shut down (zero-downtime swap when warmup completes within
   `healthcheckTimeout: 60s`).
4. **Lifespan startup** — FastAPI `lifespan` runs `SELECT 1` on the DB
   and calls `backend.retrieval.embed.warmup()`. Total cold start
   ~25–30s on a small Railway container.

Trigger: `git push origin main`. Watch the deploy in the dashboard
**Deployments** tab.

## 5. Verify (post-deploy smoke)

After the first successful deploy, verify each of the following.
Replace `<URL>` with the Railway public URL (or your custom domain).

```bash
# AC-S1 — liveness
curl -fsS https://<URL>/healthz
# expect: {"status":"ok"}

# AC-S2 — readiness (Option A: 200 immediately after lifespan)
curl -fsS https://<URL>/healthz/ready
# expect: {"status":"ready"}

# AC-S3 — login page renders Vietnamese
curl -fsS https://<URL>/login | grep -E "Đăng nhập|demo / demo"

# AC-S4 — local login works
curl -fsS -c /tmp/c.txt -X POST -d "username=demo&password=demo" \
     https://<URL>/auth/login -o /dev/null -w "%{http_code}\n"
# expect: 303
```

Then in a browser:

- **AC-S3** — visit `/login`, see Vietnamese title and the
  `demo / demo` hint.
- **AC-S5** — log in, go to `/encounters/new`, upload a real
  Vietnamese dermatology JPEG (one of the test images from local
  development is fine), submit. Wait for diagnosis. Result page
  must show a non-stub `primary_diagnosis` (not "Chẩn đoán đang
  được xử lý").
- **AC-S6** — on the result page, post a chat message ("Liều
  acyclovir cho bệnh nhân 70kg?" or any clinical question). The
  assistant reply must include at least one `chunk-…` citation
  reference.
- **AC-S7** — open browser DevTools console. Should be empty (the
  Tailwind CDN warning is silenced via `?warn=false` in
  `base.html`).

If `GOOGLE_CLIENT_ID` is set:

- **AC-OAUTH** — `/auth/google` redirects to Google's consent
  screen. Confirm the redirect URI on the Google consent screen
  matches `GOOGLE_REDIRECT_URI` exactly. Authorize, return to the
  app, end up on `/encounters/new`.

## 6. Production smoke (parity check, optional)

The TIP-012 eval can be re-run against the deployed environment to
confirm the model behaves the same in production as locally:

- **(a) Quick:** export `DATABASE_URL` to point at Railway's Postgres
  (Railway dashboard → Postgres → **Connect** → copy the public URL),
  then `python -m eval.runner` on your local machine. Same OpenAI
  calls, same prompt, same code path. Only the DB is remote.
- **(b) Thorough:** copy `eval/runner.py` to `eval/runner_remote.py`
  that POSTs `/encounters/create` against the deployed URL with the
  cookie session. Slower (network round-trip per case) but tests the
  full HTTP path.

Run on 5–10 cases (not the full 49) — speed-of-iteration matters more
than statistical power for a parity check. Compare top-1 / tier
accuracy / OOD recall to the TIP-012 local numbers. **Investigate any
metric that diverges by >5pp** — usual suspects are env-var differences
(prompt version, model name) or a model version drift on OpenAI's side.

This is **optional**. If you skip it, document why in the TIP-013
completion report. The TIP-012 local eval already covers the model
behavior.

## 7. Rollback

Railway dashboard → web service → **Deployments** tab → find the last
known-good deploy → click the kebab menu → **Redeploy**. Takes about
the same time as a fresh build+startup (~3–5 minutes including the
lifespan warmup). DB migrations are forward-only and idempotent, so
redeploying an older app version is safe even if the schema is newer
— the older app simply won't use new columns.

If a migration itself broke production, **do not** add a "fix"
migration that depends on the broken state — write a corrective
migration that's idempotent against both states, or rollback the
Postgres data via Railway's **Backups** tab.

## 8. Common issues

| Problem | Fix |
|---|---|
| `CREATE EXTENSION vector` fails: "extension not found" | Railway Postgres image lacks pgvector. Either swap to a `pgvector/pgvector` image (Railway → Postgres → Settings → image) or fall back to Supabase per Amendment 001 pre-Amendment plan. |
| Healthcheck times out at 60s | Embedder warmup taking longer than expected. Check deploy logs for the `Loading multilingual-e5-small embedder...` line. If it never finishes, suspect OOM (small Railway plan can be too tight); upgrade plan or downsize the embedder cache. |
| 502 Bad Gateway on first request | Lifespan `SELECT 1` failed. Check `DATABASE_URL` is auto-injected; check Postgres service is up; check pgvector enabled. |
| `/auth/google/callback` returns 401 with `redirect_uri_mismatch` | Google Cloud Console redirect URI does not match Railway's exactly. Trailing slash, http vs https, and the `BASE_URL` env var must all align. Update Google Cloud Console first, then retest. |
| `OPENAI_API_KEY not set` 500 on first encounter create | Variable missing in Railway dashboard. Set under web service → Variables. Trigger a redeploy. |
| `seed_kb_chunks.py` fails: `data/chunks.json is empty` | The build pulled a branch where the chunks artifact wasn't committed. Re-deploy from a branch that has `data/chunks.json` populated (TIP-008 output, ~135k lines). |
| `psql: command not found` in start script | `nixpacks.toml` is missing the `postgresql` system package. Restore it under `[phases.setup] nixPkgs = [...]`. |
| Container restarts every few minutes | `restartPolicyType: ON_FAILURE` is doing its job because the app is crashing on startup. Tail Railway logs for the actual error; usually a missing env var. |
| Cold-start latency > 30s | Either the embedder genuinely takes that long on the assigned hardware, or you're not on Option A and the container slept. Check `railway.json` has `"sleepApplication": false`. |
| Demo account login broken in prod | Migrations 002 (demo seed) didn't run. Check deploy logs for migration output; manually re-run via Railway → Postgres → **Connect** → run `migrations/002_seed_demo_user.sql`. |

## 9. Publishing the Google OAuth app

While the OAuth consent screen is in **Testing** status, only Google
accounts on the explicit test-user list can sign in. Anyone else
hits "Access blocked: this app has not completed the Google verification
process." For the closed beta we want any Vietnamese clinician with a
Google account to be able to log in, so the consent screen has to be
**Published**.

### Procedure (Chủ nhà executes — manual, NOT done by Thợ)

1. Open Google Cloud Console → **APIs & Services** → **OAuth consent
   screen**.
2. Status reads **Testing**. Click **Publish app**.
3. Confirm the dialog.

That's it — no review submission required for "external/unverified"
apps. Within ~1 minute the consent screen accepts arbitrary Google
accounts.

### What users will see

Because the app has not been verified by Google (verification is a
separate, weeks-long review the project does not currently need), the
consent screen shows an interstitial:

> **Google hasn't verified this app**
> The app is requesting access to sensitive info in your Google
> Account. Until the developer (…) verifies this app with Google, you
> shouldn't use it.

Below that warning is a small **Advanced** link. After clicking it:

> **Go to DermAssist VN (unsafe)**

Tapping that link proceeds to the normal consent screen and then back
into DermAssist VN. The "(unsafe)" copy is alarming but normal for any
unverified OAuth app — it does not mean the app is actually unsafe.

### Vietnamese explanation (paste into the README / Zalo intro)

> Đây là dự án nghiên cứu — Google chưa xác minh app, bạn có thể click
> "Advanced" → "Tiếp tục" (hoặc "Go to DermAssist VN (unsafe)") để
> đăng nhập. App chỉ yêu cầu thông tin tài khoản cơ bản.

### One-way warning

Publishing is **one-way**. The OAuth consent screen does not have a
"go back to Testing" button. If the project later needs to lock the
app down to a test-user list again, the only path is to delete the
OAuth client and create a new one — which invalidates every existing
session and forces all current users to re-authorize.

If "Published" status causes any policy issue (e.g., volume of users
exceeds free quota, or a real verification request becomes necessary),
plan that work before clicking. For the V1 closed beta the trade-off
is acceptable: a few hundred clinicians at most over the demo window.

### Optional: full app verification (V2 work)

The "Google hasn't verified this app" interstitial disappears only
after Google verifies the app, which takes **1–2 weeks** of back-and-
forth (privacy policy URL, brand verification, scopes justification).
This is V2 work — flagged for the next round of polish but not
required for the closed beta.
