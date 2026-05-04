# DermAssist VN — Eval Harness

Runs the canonical TIP-010 pipeline against a labeled gold set and
produces a self-contained HTML report (one file, no JS required).

## What gets measured

Per BLUEPRINT.md §6:

- **REQ-EVAL-001** — Zoster sensitivity (recall on `expected_key=herpes_zoster` cases). Target ≥ 95%.
- **REQ-EVAL-002** — Tier accuracy (gold tier vs predicted `management_tier`). Target ≥ 80%.
- **REQ-EVAL-003** — OOD recall (composite OOD per `compute_final_ood`). Target ≥ 85%.

Plus standard support metrics: top-1 / top-3 accuracy, OOD precision,
per-condition accuracy, 9×9 confusion matrix, latency p50 / p95, and
the top-5 most-confident wrong predictions (the most diagnostic
failure mode for prompt tuning).

## How to run

```bash
# 1. Build the gold set (one-time; downloads images into
#    data/raw/eval_images/<sha>.<ext>):
python -m eval.build_gold_set

# 2. Smoke run (3 cases, ~30 seconds):
python -m eval.runner --gold data/gold_set.jsonl --limit 3

# 3. Full run (~50 cases, ~5 minutes, ~$0.05 in OpenAI cost):
python -m eval.runner --gold data/gold_set.jsonl
```

Results land in `data/eval_results/<UTC-timestamp>.json` (raw) and
`<UTC-timestamp>.html` (human-readable report). Both are gitignored.

## Honest scope

V1 ships with ~50 cases (≤10 per in-scope condition + ~10 OOD), well
below REQ-EVAL-005's 160-minimum. See [docs/eval-limitations.md](../docs/eval-limitations.md)
for the full list of caveats:

- Sample sizes per condition are too small for tight confidence intervals.
- Tier labels are heuristic per condition, not expert-validated per case.
- Gold-set images are sourced from existing public datasets
  (Fitzpatrick17k, SCIN), not Vietnamese clinical data.

The eval is a **structural / directional capability** measurement, not
a clinical-grade evaluation. V2 with IRB partnership earns the latter.

## How the runner avoids polluting prod state

The runner creates a synthetic `eval_runner` user (idempotent), runs
the full pipeline against each case (real OpenAI calls), then
deletes all encounter rows + audit_log rows for that user at the end.
Production data isn't touched.

If you crash mid-run or hit Ctrl-C, the cleanup is skipped — re-run
to clean. Or: `--no-cleanup` flag for debugging.

## Module layout

| File | Purpose |
|---|---|
| `gold_set.py` | Load + validate `data/gold_set.jsonl`, skip cases whose images aren't on disk. |
| `metrics.py` | Pure metric functions (top-1/3, sensitivity, recall, confusion, latency). Unit-tested. |
| `runner.py` | CLI + pipeline driver. Calls `backend.orchestrator.run_encounter` per case. |
| `report.py` | Single-file HTML generator. No JS, Tailwind via CDN. |
| `build_gold_set.py` | One-time script — downloads images, writes JSONL. |

## Tests

`pytest tests/unit/test_metrics.py` exercises every metric function on
synthetic case lists. Runner integration tests are NOT included (real
OpenAI calls in tests = cost + flake; smoke-run the CLI manually).
