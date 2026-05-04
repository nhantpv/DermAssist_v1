"""Pure metric computation. No I/O, no network, no DB.

Input: list of CaseResult objects. Output: a Metrics object holding
all aggregated numbers in one go. Each metric function is independently
testable on synthetic data — see tests/unit/test_metrics.py.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Iterable, Sequence

# Canonical 9-class label order for the confusion matrix.
CONDITION_LABELS: tuple[str, ...] = (
    "acne",
    "atopic_dermatitis",
    "contact_dermatitis",
    "eczema",
    "fungal_infection",
    "herpes_zoster",
    "psoriasis",
    "scabies",
    "other_ood",
)


@dataclass(frozen=True)
class CaseResult:
    """One row in the eval result set. Mirrors the JSON shape."""
    case_id: str
    expected_key: str
    predicted_key: str
    differential_keys: list[str]
    expected_tier: str
    predicted_tier: str
    expected_ood: bool
    predicted_ood: bool
    confidence: float
    latency_ms: int


@dataclass
class Metrics:
    n: int = 0
    top_1_accuracy: float = 0.0
    top_3_accuracy: float = 0.0
    tier_accuracy: float = 0.0
    zoster_sensitivity: float | None = None  # None if no zoster cases
    ood_recall: float | None = None
    ood_precision: float | None = None
    per_condition_accuracy: dict[str, dict] = field(default_factory=dict)
    confusion_matrix: list[list[int]] = field(default_factory=list)
    confusion_labels: list[str] = field(default_factory=list)
    mean_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    mean_confidence_correct: float | None = None


def _safe_div(num: int, denom: int) -> float | None:
    return (num / denom) if denom > 0 else None


def top_1_accuracy(cases: Sequence[CaseResult]) -> float:
    if not cases:
        return 0.0
    correct = sum(1 for c in cases if c.predicted_key == c.expected_key)
    return correct / len(cases)


def top_3_accuracy(cases: Sequence[CaseResult]) -> float:
    """Expected key appears in {predicted_key} ∪ differential_keys (top-3 cap)."""
    if not cases:
        return 0.0
    correct = 0
    for c in cases:
        candidates = [c.predicted_key] + list(c.differential_keys)
        # Top-3: predicted + first 2 differential entries
        if c.expected_key in candidates[:3]:
            correct += 1
    return correct / len(cases)


def tier_accuracy(cases: Sequence[CaseResult]) -> float:
    """REQ-EVAL-002. Predicted tier matches gold tier."""
    if not cases:
        return 0.0
    correct = sum(1 for c in cases if c.predicted_tier == c.expected_tier)
    return correct / len(cases)


def zoster_sensitivity(cases: Sequence[CaseResult]) -> float | None:
    """REQ-EVAL-001. Of cases where expected_key == 'herpes_zoster',
    fraction predicted herpes_zoster."""
    relevant = [c for c in cases if c.expected_key == "herpes_zoster"]
    if not relevant:
        return None
    hits = sum(1 for c in relevant if c.predicted_key == "herpes_zoster")
    return hits / len(relevant)


def ood_recall(cases: Sequence[CaseResult]) -> float | None:
    """REQ-EVAL-003. Of cases where expected_ood=True, fraction with
    predicted_ood=True (composite OOD per compute_final_ood)."""
    relevant = [c for c in cases if c.expected_ood]
    if not relevant:
        return None
    hits = sum(1 for c in relevant if c.predicted_ood)
    return hits / len(relevant)


def ood_precision(cases: Sequence[CaseResult]) -> float | None:
    """Of cases where predicted_ood=True, fraction with expected_ood=True."""
    relevant = [c for c in cases if c.predicted_ood]
    if not relevant:
        return None
    hits = sum(1 for c in relevant if c.expected_ood)
    return hits / len(relevant)


def per_condition_accuracy(cases: Sequence[CaseResult]) -> dict[str, dict]:
    """Per-condition top-1 accuracy + N + mean confidence on correct.

    Keyed by expected_condition_key. Each value: {n, correct,
    accuracy, mean_confidence_correct (None if 0 correct)}.
    """
    by_key: dict[str, list[CaseResult]] = {}
    for c in cases:
        by_key.setdefault(c.expected_key, []).append(c)
    out: dict[str, dict] = {}
    for key, group in by_key.items():
        correct = [c for c in group if c.predicted_key == c.expected_key]
        out[key] = {
            "n": len(group),
            "correct": len(correct),
            "accuracy": len(correct) / len(group),
            "mean_confidence_correct": (
                statistics.mean(c.confidence for c in correct) if correct else None
            ),
        }
    return out


def confusion_matrix(
    cases: Sequence[CaseResult],
    labels: Sequence[str] = CONDITION_LABELS,
) -> list[list[int]]:
    """Rows = expected, cols = predicted. Entries outside `labels`
    fold into 'other_ood' (the last label)."""
    label_idx = {label: i for i, label in enumerate(labels)}
    n = len(labels)
    matrix = [[0] * n for _ in range(n)]
    for c in cases:
        r = label_idx.get(c.expected_key, label_idx["other_ood"])
        col = label_idx.get(c.predicted_key, label_idx["other_ood"])
        matrix[r][col] += 1
    return matrix


def latency_summary(cases: Sequence[CaseResult]) -> tuple[float, float, float]:
    """(mean, p50, p95). Returns (0,0,0) on empty input."""
    if not cases:
        return 0.0, 0.0, 0.0
    latencies = sorted(c.latency_ms for c in cases)
    mean = statistics.mean(latencies)
    p50 = _percentile(latencies, 50)
    p95 = _percentile(latencies, 95)
    return mean, p50, p95


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    # Nearest-rank
    k = max(0, min(len(sorted_values) - 1, int(round(pct / 100.0 * (len(sorted_values) - 1)))))
    return float(sorted_values[k])


def mean_confidence_on_correct(cases: Sequence[CaseResult]) -> float | None:
    correct = [c for c in cases if c.predicted_key == c.expected_key]
    if not correct:
        return None
    return statistics.mean(c.confidence for c in correct)


def compute_metrics(cases: Sequence[CaseResult]) -> Metrics:
    """One-call summary. Used by report.py and the CLI summary line."""
    if not cases:
        return Metrics()
    mean, p50, p95 = latency_summary(cases)
    return Metrics(
        n=len(cases),
        top_1_accuracy=top_1_accuracy(cases),
        top_3_accuracy=top_3_accuracy(cases),
        tier_accuracy=tier_accuracy(cases),
        zoster_sensitivity=zoster_sensitivity(cases),
        ood_recall=ood_recall(cases),
        ood_precision=ood_precision(cases),
        per_condition_accuracy=per_condition_accuracy(cases),
        confusion_matrix=confusion_matrix(cases),
        confusion_labels=list(CONDITION_LABELS),
        mean_latency_ms=mean,
        p50_latency_ms=p50,
        p95_latency_ms=p95,
        mean_confidence_correct=mean_confidence_on_correct(cases),
    )


def find_failure_cases(
    cases: Sequence[CaseResult],
    *,
    n: int = 5,
) -> list[CaseResult]:
    """Top-N most confident wrong predictions. Helps spot prompt-tuning
    targets — high confidence on a wrong call is the most diagnostic
    failure mode."""
    wrong = [c for c in cases if c.predicted_key != c.expected_key]
    wrong.sort(key=lambda c: c.confidence, reverse=True)
    return wrong[:n]
