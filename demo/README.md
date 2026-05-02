# DermAssist VN — Demo

Self-contained throwaway demo of the diagnostic flow. Uses OpenAI
gpt-4o-mini for vision reasoning. Not the canonical pipeline — see
`backend/` (when it exists) for the real thing.

## Setup

```bash
# from repo root
python -m venv .venv && source .venv/bin/activate
pip install -e ".[demo]"

# copy .env, fill in OPENAI_API_KEY
cp demo/.env.example demo/.env
# (edit demo/.env)

# load env and run
export $(cat demo/.env | xargs)
uvicorn demo.app:app --reload --port 8000
```

Open http://localhost:8000 — login with `demo` / `demo`.

## What this demo does

- Login (hardcoded demo/demo, signed-cookie session)
- Upload an image + clinical note
- Calls OpenAI gpt-4o-mini with the image and a Vietnamese system
  prompt grounded in `data/visual_descriptions.json`
- Returns and displays a structured diagnosis (primary dx, confidence,
  differential, key features, management tier, red flags, OOD flag)
- Encounter history visible at `/encounters`

## What this demo does NOT do

- No DB persistence — encounter list resets on server restart
- No image preflight (blur/brightness/PII detection)
- No RAG retrieval — relies on system prompt only
- No multi-turn anamnesis — single-shot diagnosis
- No real auth — `demo`/`demo` is the only account
- No rate limiting

These are scope items for the canonical TIPs (TIP-005…TIP-011).

## Cost

gpt-4o-mini: ~$0.15 per 1M input tokens, $0.60 per 1M output tokens.
Each encounter is ~3K input tokens (system prompt + image) + ~500
output tokens. Demo cost: <$0.001 per request. Fine for showing it
to a few people.

## Cleanup

To remove the demo entirely: `rm -rf demo/` and remove the
`[project.optional-dependencies.demo]` block from `pyproject.toml`.
No other code references `demo/`.
