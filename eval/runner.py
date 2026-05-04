"""End-to-end eval runner.

For each gold case:
  1. Read image bytes from data/raw/eval_images/<sha>.<ext>
  2. Call backend.orchestrator.run_encounter() — real OpenAI call.
  3. Capture predicted_key, predicted_tier, predicted_ood (composite),
     confidence, top-3 differential keys, latency_ms.
  4. Cleanup: delete the encounter row + its audit_log + chat_messages
     so the eval doesn't pollute production state.

Outputs:
  data/eval_results/<timestamp>.json   (raw results + metrics)
  data/eval_results/<timestamp>.html   (human-readable report)

CLI:
  python -m eval.runner --gold data/gold_set.jsonl --limit 3
  python -m eval.runner --gold data/gold_set.jsonl --out data/eval_results/
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from backend.db import SessionLocal
from backend.orchestrator import run_encounter
from eval.gold_set import GoldCase, load_gold_set, per_condition_counts
from eval.metrics import CaseResult, compute_metrics, find_failure_cases
from eval.report import generate_html

logger = logging.getLogger(__name__)

# Synthetic doctor for the eval runner. Created lazily with a stable
# UUID so cleanup can target rows by doctor_id alone.
_EVAL_DOCTOR_USERNAME = "eval_runner"
_EVAL_DOCTOR_PASSWORD = "eval_runner_no_login"


_EXT_TO_CONTENT_TYPE = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def _content_type_for(path: Path) -> str:
    ext = path.suffix.lstrip(".").lower()
    return _EXT_TO_CONTENT_TYPE.get(ext, "image/jpeg")


async def _ensure_eval_doctor() -> str:
    """Idempotently create the eval-runner user. Returns its UUID."""
    import bcrypt
    pwd_hash = bcrypt.hashpw(
        _EVAL_DOCTOR_PASSWORD.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")
    async with SessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO users (username, password_hash, full_name, role) "
                "VALUES (:u, :h, 'Eval Runner', 'doctor') "
                "ON CONFLICT (username) DO NOTHING"
            ),
            {"u": _EVAL_DOCTOR_USERNAME, "h": pwd_hash},
        )
        await db.commit()
        row = (
            await db.execute(
                text("SELECT id::text AS id FROM users WHERE username = :u"),
                {"u": _EVAL_DOCTOR_USERNAME},
            )
        ).mappings().first()
    return row["id"]


async def _cleanup_eval_data(doctor_id: str) -> None:
    """Delete all encounters + audit_log entries for the eval doctor.
    Chat messages cascade via FK ON DELETE CASCADE."""
    async with SessionLocal() as db:
        # audit_log is FK→encounters with ON DELETE SET NULL, so delete
        # audit rows first by doctor_id.
        await db.execute(
            text("DELETE FROM audit_log WHERE doctor_id = CAST(:uid AS uuid)"),
            {"uid": doctor_id},
        )
        await db.execute(
            text("DELETE FROM encounters WHERE doctor_id = CAST(:uid AS uuid)"),
            {"uid": doctor_id},
        )
        await db.commit()


def _diagnosis_to_top_keys(differential: list[Any]) -> list[str]:
    """Pull condition_key out of differential entries, in order."""
    out: list[str] = []
    for d in differential:
        if isinstance(d, dict):
            k = d.get("condition_key")
        else:
            k = getattr(d, "condition_key", None)
        if k:
            out.append(k)
    return out


async def _run_one(
    case: GoldCase,
    *,
    doctor_id: str,
) -> CaseResult | None:
    """One pipeline call. Returns None if the image fails to read."""
    try:
        image_bytes = case.image_path.read_bytes()
    except OSError as e:
        logger.warning("read fail %s: %s", case.case_id, e)
        return None

    content_type = _content_type_for(case.image_path)
    note = (case.notes or "").strip()[:1000]

    t0 = time.monotonic()
    async with SessionLocal() as db:
        result = await run_encounter(
            db=db,
            doctor_id=doctor_id,
            image_bytes=image_bytes,
            image_content_type=content_type,
            clinical_note=note,
            patient_context={
                "age_years": None,
                "sex": None,
                "symptom_duration_days": None,
                "prior_treatments": None,
                "relevant_history": None,
            },
        )
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    # Preflight failure or no diagnosis → the case is unscorable;
    # synthesize a conservative result so it shows up in the report.
    if result.diagnosis is None:
        return CaseResult(
            case_id=case.case_id,
            expected_key=case.expected_condition_key,
            predicted_key="other_ood",
            differential_keys=[],
            expected_tier=case.expected_tier,
            predicted_tier="outpatient_72h",
            expected_ood=case.expected_ood,
            predicted_ood=True,
            confidence=0.0,
            latency_ms=elapsed_ms,
        )

    diag = result.diagnosis
    diff_keys = _diagnosis_to_top_keys(diag.differential)
    return CaseResult(
        case_id=case.case_id,
        expected_key=case.expected_condition_key,
        predicted_key=diag.primary_condition_key,
        differential_keys=diff_keys,
        expected_tier=case.expected_tier,
        predicted_tier=diag.management_tier,
        expected_ood=case.expected_ood,
        predicted_ood=result.final_ood,
        confidence=diag.confidence,
        latency_ms=elapsed_ms,
    )


async def run_eval(
    gold_path: Path,
    out_dir: Path,
    *,
    limit: int | None = None,
    cleanup: bool = True,
) -> Path:
    """Top-level entry. Returns path to the written JSON file. Also
    writes the HTML report alongside."""
    cases = load_gold_set(gold_path)
    if limit:
        cases = cases[:limit]
    logger.info("Loaded %d gold cases (limit=%s)", len(cases), limit)

    doctor_id = await _ensure_eval_doctor()
    logger.info("Eval doctor id: %s", doctor_id)

    results: list[CaseResult] = []
    skipped: list[str] = []
    for i, case in enumerate(cases, start=1):
        logger.info("[%d/%d] %s (%s)", i, len(cases), case.case_id, case.expected_condition_key)
        try:
            r = await _run_one(case, doctor_id=doctor_id)
        except Exception as e:
            logger.exception("case %s crashed: %s", case.case_id, e)
            skipped.append(case.case_id)
            continue
        if r is None:
            skipped.append(case.case_id)
            continue
        results.append(r)
        logger.info(
            "    predicted=%s (conf=%.2f) tier=%s ood=%s latency=%dms",
            r.predicted_key, r.confidence, r.predicted_tier,
            r.predicted_ood, r.latency_ms,
        )

    if cleanup:
        await _cleanup_eval_data(doctor_id)
        logger.info("Cleaned up eval encounter rows")

    metrics = compute_metrics(results)
    failures = find_failure_cases(results, n=5)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{timestamp}.json"
    html_path = out_dir / f"{timestamp}.html"

    payload: dict[str, Any] = {
        "run_id": timestamp,
        "gold_path": str(gold_path),
        "gold_set_size": len(cases),
        "scored": len(results),
        "skipped": skipped,
        "model_version": "gpt-4o-mini-v1",
        "prompt_version": "v1.0.0",
        "per_condition_counts_input": per_condition_counts(cases),
        "cases": [dataclasses.asdict(r) for r in results],
        "metrics": dataclasses.asdict(metrics),
        "failure_cases": [dataclasses.asdict(c) for c in failures],
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    generate_html(payload, html_path)

    # Stdout summary
    pct = lambda v: f"{v*100:.1f}%" if isinstance(v, (int, float)) else "n/a"
    print(
        f"Top-1: {int(metrics.top_1_accuracy*len(results))}/{len(results)} "
        f"({pct(metrics.top_1_accuracy)}), "
        f"Tier: {int(metrics.tier_accuracy*len(results))}/{len(results)} "
        f"({pct(metrics.tier_accuracy)}), "
        f"Zoster sens: {pct(metrics.zoster_sensitivity)}, "
        f"OOD recall: {pct(metrics.ood_recall)}. "
        f"Report: {html_path}"
    )
    return json_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run DermAssist eval harness")
    parser.add_argument("--gold", type=Path, default=Path("data/gold_set.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("data/eval_results"))
    parser.add_argument("--limit", type=int, default=None,
                        help="Run only the first N cases (smoke test).")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Skip the post-run DB cleanup (debugging).")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )
    args = _parse_args()
    if not args.gold.exists():
        logger.error("Gold set not found: %s — run python -m eval.build_gold_set", args.gold)
        return 1
    asyncio.run(run_eval(
        args.gold, args.out, limit=args.limit, cleanup=not args.no_cleanup,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
