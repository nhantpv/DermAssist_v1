"""Unit tests for eval.metrics. Pure-Python; no DB, no network."""
from __future__ import annotations

import pytest

from eval.metrics import (
    CaseResult,
    compute_metrics,
    confusion_matrix,
    find_failure_cases,
    latency_summary,
    ood_precision,
    ood_recall,
    per_condition_accuracy,
    tier_accuracy,
    top_1_accuracy,
    top_3_accuracy,
    zoster_sensitivity,
)


def _case(
    expected="acne",
    predicted="acne",
    differential=None,
    expected_tier="home_care",
    predicted_tier="home_care",
    expected_ood=False,
    predicted_ood=False,
    confidence=0.7,
    latency_ms=1000,
    case_id="x",
):
    return CaseResult(
        case_id=case_id,
        expected_key=expected,
        predicted_key=predicted,
        differential_keys=list(differential or []),
        expected_tier=expected_tier,
        predicted_tier=predicted_tier,
        expected_ood=expected_ood,
        predicted_ood=predicted_ood,
        confidence=confidence,
        latency_ms=latency_ms,
    )


def test_top1_accuracy_all_correct():
    cases = [_case(), _case(), _case()]
    assert top_1_accuracy(cases) == 1.0


def test_top1_accuracy_all_wrong():
    cases = [_case(expected="acne", predicted="psoriasis"),
             _case(expected="eczema", predicted="acne")]
    assert top_1_accuracy(cases) == 0.0


def test_top3_correct_when_in_differential():
    """Expected key in 2nd differential slot still counts as top-3 hit."""
    c = _case(expected="herpes_zoster",
              predicted="contact_dermatitis",
              differential=["acne", "herpes_zoster"])
    assert top_3_accuracy([c]) == 1.0


def test_top3_caps_at_top3():
    """Expected in 4th slot is NOT a top-3 hit."""
    c = _case(expected="psoriasis",
              predicted="acne",
              differential=["eczema", "fungal_infection", "psoriasis"])
    assert top_3_accuracy([c]) == 0.0


def test_zoster_sensitivity_no_zoster_cases():
    cases = [_case(expected="acne", predicted="acne")]
    assert zoster_sensitivity(cases) is None


def test_zoster_sensitivity_partial():
    cases = [
        _case(expected="herpes_zoster", predicted="herpes_zoster"),
        _case(expected="herpes_zoster", predicted="contact_dermatitis"),
        _case(expected="herpes_zoster", predicted="herpes_zoster"),
    ]
    assert zoster_sensitivity(cases) == pytest.approx(2 / 3)


def test_ood_recall_no_ood_cases_returns_none():
    cases = [_case(), _case()]
    assert ood_recall(cases) is None


def test_ood_recall_full_credit():
    cases = [
        _case(expected="other_ood", expected_ood=True, predicted_ood=True),
        _case(expected="other_ood", expected_ood=True, predicted_ood=True),
    ]
    assert ood_recall(cases) == 1.0


def test_ood_recall_partial():
    cases = [
        _case(expected="other_ood", expected_ood=True, predicted_ood=True),
        _case(expected="other_ood", expected_ood=True, predicted_ood=False),
    ]
    assert ood_recall(cases) == 0.5


def test_ood_precision_no_predicted_ood_returns_none():
    cases = [_case(predicted_ood=False)]
    assert ood_precision(cases) is None


def test_tier_accuracy_mixed():
    cases = [
        _case(expected_tier="home_care", predicted_tier="home_care"),
        _case(expected_tier="emergency", predicted_tier="outpatient_24h"),
        _case(expected_tier="outpatient_72h", predicted_tier="outpatient_72h"),
    ]
    assert tier_accuracy(cases) == pytest.approx(2 / 3)


def test_per_condition_accuracy_distinct_conditions():
    cases = [
        _case(expected="acne", predicted="acne", confidence=0.8),
        _case(expected="acne", predicted="psoriasis", confidence=0.5),
        _case(expected="psoriasis", predicted="psoriasis", confidence=0.9),
    ]
    pca = per_condition_accuracy(cases)
    assert pca["acne"]["n"] == 2
    assert pca["acne"]["correct"] == 1
    assert pca["acne"]["accuracy"] == 0.5
    assert pca["acne"]["mean_confidence_correct"] == pytest.approx(0.8)
    assert pca["psoriasis"]["accuracy"] == 1.0
    assert pca["psoriasis"]["mean_confidence_correct"] == pytest.approx(0.9)


def test_confusion_matrix_diagonal_all_correct():
    cases = [_case(expected=k, predicted=k) for k in ("acne", "psoriasis", "eczema")]
    cm = confusion_matrix(cases)
    # Each correct case adds 1 to its diagonal cell
    assert sum(sum(row) for row in cm) == 3
    # All off-diagonal cells should be 0
    for r in range(len(cm)):
        for c in range(len(cm)):
            if r != c and cm[r][c] != 0:
                assert False, f"unexpected off-diagonal entry at ({r},{c})"


def test_confusion_matrix_misclassification():
    cases = [_case(expected="acne", predicted="psoriasis"),
             _case(expected="psoriasis", predicted="psoriasis")]
    cm = confusion_matrix(cases)
    from eval.metrics import CONDITION_LABELS
    acne_idx = CONDITION_LABELS.index("acne")
    pso_idx = CONDITION_LABELS.index("psoriasis")
    assert cm[acne_idx][pso_idx] == 1   # acne→psoriasis miss
    assert cm[pso_idx][pso_idx] == 1    # psoriasis→psoriasis correct


def test_latency_summary_simple():
    cases = [
        _case(latency_ms=1000), _case(latency_ms=2000),
        _case(latency_ms=3000), _case(latency_ms=4000),
        _case(latency_ms=5000),
    ]
    mean, p50, p95 = latency_summary(cases)
    assert mean == pytest.approx(3000)
    assert p50 == 3000
    assert p95 == 5000


def test_compute_metrics_full_pipeline():
    cases = [
        _case(expected="herpes_zoster", predicted="herpes_zoster", confidence=0.9),
        _case(expected="herpes_zoster", predicted="acne", confidence=0.4),
        _case(expected="other_ood", expected_ood=True, predicted_ood=True,
              predicted="other_ood"),
    ]
    m = compute_metrics(cases)
    assert m.n == 3
    assert m.zoster_sensitivity == 0.5
    assert m.ood_recall == 1.0
    assert "herpes_zoster" in m.per_condition_accuracy


def test_find_failure_cases_orders_by_confidence_desc():
    cases = [
        _case(case_id="low_wrong", expected="acne", predicted="psoriasis", confidence=0.3),
        _case(case_id="high_wrong", expected="acne", predicted="psoriasis", confidence=0.9),
        _case(case_id="correct", confidence=0.95),
        _case(case_id="mid_wrong", expected="acne", predicted="eczema", confidence=0.6),
    ]
    failures = find_failure_cases(cases, n=10)
    assert [c.case_id for c in failures] == ["high_wrong", "mid_wrong", "low_wrong"]
    assert all(c.predicted_key != c.expected_key for c in failures)
