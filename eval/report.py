"""Generate a self-contained HTML eval report.

No JS, no external assets except the Tailwind CDN script (matches the
canonical frontend pattern). Output is one file evaluators can open
from disk or attach to capstone submission.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

# REQ-EVAL targets from BLUEPRINT §6
TARGETS = {
    "zoster_sensitivity": 0.95,
    "tier_accuracy": 0.80,
    "ood_recall": 0.85,
}

CONDITION_VN = {
    "acne": "Mụn trứng cá",
    "atopic_dermatitis": "Viêm da cơ địa",
    "contact_dermatitis": "Viêm da tiếp xúc",
    "eczema": "Chàm",
    "fungal_infection": "Nhiễm nấm da",
    "herpes_zoster": "Zona thần kinh",
    "psoriasis": "Vảy nến",
    "scabies": "Ghẻ",
    "other_ood": "Ngoài phạm vi (OOD)",
}


def _pct(v: float | None, default: str = "n/a") -> str:
    if v is None:
        return default
    return f"{v * 100:.1f}%"


def _status_class(value: float | None, target: float) -> tuple[str, str]:
    """(label, css class) for a metric vs target."""
    if value is None:
        return ("N/A", "bg-slate-100 text-slate-700 border-slate-300")
    if value >= target:
        return ("PASS", "bg-emerald-50 text-emerald-800 border-emerald-300")
    if value >= target - 0.05:
        return ("NEAR", "bg-amber-50 text-amber-800 border-amber-300")
    return ("FAIL", "bg-red-50 text-red-800 border-red-300")


def _summary_card(metrics: dict) -> str:
    rows = []
    for key, label, target in [
        ("zoster_sensitivity", "Zoster sensitivity (REQ-EVAL-001)", TARGETS["zoster_sensitivity"]),
        ("tier_accuracy", "Tier accuracy (REQ-EVAL-002)", TARGETS["tier_accuracy"]),
        ("ood_recall", "OOD recall (REQ-EVAL-003)", TARGETS["ood_recall"]),
    ]:
        value = metrics.get(key)
        status, css = _status_class(value, target)
        rows.append(
            f'<tr class="border-b border-slate-200">'
            f'<td class="px-4 py-3 text-sm">{html.escape(label)}</td>'
            f'<td class="px-4 py-3 text-sm font-mono text-right">{_pct(value)}</td>'
            f'<td class="px-4 py-3 text-sm font-mono text-right text-slate-500">≥ {_pct(target)}</td>'
            f'<td class="px-4 py-3"><span class="inline-block px-2 py-0.5 text-xs '
            f'font-semibold rounded border {css}">{status}</span></td>'
            f"</tr>"
        )
    return (
        '<section class="mb-8">'
        '<h2 class="text-lg font-semibold text-slate-900 mb-3">REQ-EVAL targets</h2>'
        '<div class="bg-white border border-slate-200 rounded-lg overflow-hidden">'
        '<table class="w-full text-left">'
        '<thead class="bg-slate-50 border-b border-slate-200">'
        '<tr>'
        '<th class="px-4 py-2 text-xs font-medium uppercase tracking-wide text-slate-600">Metric</th>'
        '<th class="px-4 py-2 text-xs font-medium uppercase tracking-wide text-slate-600 text-right">Actual</th>'
        '<th class="px-4 py-2 text-xs font-medium uppercase tracking-wide text-slate-600 text-right">Target</th>'
        '<th class="px-4 py-2 text-xs font-medium uppercase tracking-wide text-slate-600">Status</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        "</table></div></section>"
    )


def _topline_metrics(metrics: dict) -> str:
    cells = [
        ("Top-1 accuracy", _pct(metrics.get("top_1_accuracy"))),
        ("Top-3 accuracy", _pct(metrics.get("top_3_accuracy"))),
        ("Tier accuracy", _pct(metrics.get("tier_accuracy"))),
        ("OOD precision", _pct(metrics.get("ood_precision"))),
        ("OOD recall", _pct(metrics.get("ood_recall"))),
        ("Mean conf (correct)", _pct(metrics.get("mean_confidence_correct"))),
    ]
    cards = "".join(
        f'<div class="bg-white border border-slate-200 rounded-lg p-4">'
        f'<div class="text-xs font-medium uppercase tracking-wide text-slate-500">{html.escape(label)}</div>'
        f'<div class="mt-1 text-2xl font-semibold text-slate-900 font-mono">{html.escape(value)}</div>'
        f"</div>"
        for label, value in cells
    )
    return (
        '<section class="mb-8">'
        '<h2 class="text-lg font-semibold text-slate-900 mb-3">Top-line metrics</h2>'
        f'<div class="grid grid-cols-2 md:grid-cols-3 gap-3">{cards}</div>'
        "</section>"
    )


def _per_condition_table(metrics: dict, input_counts: dict[str, int]) -> str:
    pca = metrics.get("per_condition_accuracy", {})
    keys = sorted(set(list(pca.keys()) + list(input_counts.keys())))
    rows = []
    for k in keys:
        row = pca.get(k, {})
        n_input = input_counts.get(k, 0)
        n_scored = row.get("n", 0)
        accuracy = row.get("accuracy")
        mean_conf = row.get("mean_confidence_correct")
        vn = CONDITION_VN.get(k, k)
        rows.append(
            f'<tr class="border-b border-slate-200">'
            f'<td class="px-4 py-2 text-sm">{html.escape(vn)}</td>'
            f'<td class="px-4 py-2 text-xs text-slate-500 font-mono">{html.escape(k)}</td>'
            f'<td class="px-4 py-2 text-sm font-mono text-right">{n_input}</td>'
            f'<td class="px-4 py-2 text-sm font-mono text-right">{n_scored}</td>'
            f'<td class="px-4 py-2 text-sm font-mono text-right">'
            f'{_pct(accuracy) if accuracy is not None else "n/a"}</td>'
            f'<td class="px-4 py-2 text-sm font-mono text-right">'
            f'{_pct(mean_conf) if mean_conf is not None else "n/a"}</td>'
            f"</tr>"
        )
    return (
        '<section class="mb-8">'
        '<h2 class="text-lg font-semibold text-slate-900 mb-3">Per-condition accuracy</h2>'
        '<div class="bg-white border border-slate-200 rounded-lg overflow-x-auto">'
        '<table class="w-full text-left">'
        '<thead class="bg-slate-50 border-b border-slate-200"><tr>'
        '<th class="px-4 py-2 text-xs font-medium uppercase tracking-wide text-slate-600">Condition</th>'
        '<th class="px-4 py-2 text-xs font-medium uppercase tracking-wide text-slate-600">Key</th>'
        '<th class="px-4 py-2 text-xs font-medium uppercase tracking-wide text-slate-600 text-right">N input</th>'
        '<th class="px-4 py-2 text-xs font-medium uppercase tracking-wide text-slate-600 text-right">N scored</th>'
        '<th class="px-4 py-2 text-xs font-medium uppercase tracking-wide text-slate-600 text-right">Top-1</th>'
        '<th class="px-4 py-2 text-xs font-medium uppercase tracking-wide text-slate-600 text-right">Mean conf</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        "</table></div></section>"
    )


def _confusion_matrix_html(metrics: dict) -> str:
    matrix: list[list[int]] = metrics.get("confusion_matrix", [])
    labels: list[str] = metrics.get("confusion_labels", [])
    if not matrix:
        return ""

    # Heat color: scale by row max so each row's diagonal stands out
    def heat_class(val: int, row_max: int) -> str:
        if val == 0:
            return "bg-white text-slate-300"
        ratio = val / max(row_max, 1)
        if ratio >= 0.8:
            return "bg-emerald-200 text-emerald-900 font-semibold"
        if ratio >= 0.5:
            return "bg-emerald-100 text-emerald-800"
        if ratio >= 0.2:
            return "bg-emerald-50 text-emerald-700"
        return "bg-slate-50 text-slate-600"

    header = "".join(
        f'<th class="px-2 py-1 text-xs font-mono text-slate-600 border-l border-slate-200" '
        f'title="{html.escape(labels[i])}">{html.escape(labels[i][:10])}</th>'
        for i in range(len(labels))
    )

    body_rows = []
    for r, row in enumerate(matrix):
        row_max = max(row) if row else 0
        cells = [
            f'<th class="px-2 py-1 text-xs font-mono text-slate-700 text-left whitespace-nowrap">'
            f'{html.escape(labels[r])}</th>'
        ]
        for c, val in enumerate(row):
            cls = heat_class(val, row_max)
            cells.append(
                f'<td class="px-2 py-1 text-xs font-mono text-center border-l border-slate-200 {cls}">'
                f'{val if val else ""}</td>'
            )
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    return (
        '<section class="mb-8">'
        '<h2 class="text-lg font-semibold text-slate-900 mb-3">Confusion matrix</h2>'
        '<p class="text-xs text-slate-500 mb-2">Rows = expected, columns = predicted. '
        'Diagonal cells (correct) shaded green by intensity within each row.</p>'
        '<div class="bg-white border border-slate-200 rounded-lg p-2 overflow-x-auto">'
        '<table class="w-full text-xs">'
        f'<thead><tr><th></th>{header}</tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody>'
        "</table></div></section>"
    )


def _latency_card(metrics: dict) -> str:
    return (
        '<section class="mb-8">'
        '<h2 class="text-lg font-semibold text-slate-900 mb-3">Pipeline latency</h2>'
        '<div class="grid grid-cols-3 gap-3">'
        f'<div class="bg-white border border-slate-200 rounded-lg p-4">'
        f'<div class="text-xs font-medium uppercase tracking-wide text-slate-500">Mean</div>'
        f'<div class="mt-1 text-2xl font-semibold text-slate-900 font-mono">'
        f'{metrics.get("mean_latency_ms", 0):.0f} ms</div></div>'
        f'<div class="bg-white border border-slate-200 rounded-lg p-4">'
        f'<div class="text-xs font-medium uppercase tracking-wide text-slate-500">P50</div>'
        f'<div class="mt-1 text-2xl font-semibold text-slate-900 font-mono">'
        f'{metrics.get("p50_latency_ms", 0):.0f} ms</div></div>'
        f'<div class="bg-white border border-slate-200 rounded-lg p-4">'
        f'<div class="text-xs font-medium uppercase tracking-wide text-slate-500">P95</div>'
        f'<div class="mt-1 text-2xl font-semibold text-slate-900 font-mono">'
        f'{metrics.get("p95_latency_ms", 0):.0f} ms</div></div>'
        '</div></section>'
    )


def _failures_section(failures: list[dict]) -> str:
    if not failures:
        return (
            '<section class="mb-8">'
            '<h2 class="text-lg font-semibold text-slate-900 mb-3">Failure cases</h2>'
            '<p class="text-sm text-slate-600">No misclassifications.</p>'
            "</section>"
        )
    rows = []
    for c in failures:
        rows.append(
            f'<tr class="border-b border-slate-200">'
            f'<td class="px-4 py-2 text-xs font-mono text-slate-700">{html.escape(c["case_id"])}</td>'
            f'<td class="px-4 py-2 text-sm">{html.escape(CONDITION_VN.get(c["expected_key"], c["expected_key"]))}</td>'
            f'<td class="px-4 py-2 text-sm">{html.escape(CONDITION_VN.get(c["predicted_key"], c["predicted_key"]))}</td>'
            f'<td class="px-4 py-2 text-sm font-mono text-right">{c["confidence"]:.2f}</td>'
            f'<td class="px-4 py-2 text-sm font-mono text-right">{c["latency_ms"]} ms</td>'
            f"</tr>"
        )
    return (
        '<section class="mb-8">'
        '<h2 class="text-lg font-semibold text-slate-900 mb-3">'
        'Failure cases (top-5 highest-confidence wrong predictions)</h2>'
        '<div class="bg-white border border-slate-200 rounded-lg overflow-x-auto">'
        '<table class="w-full text-left">'
        '<thead class="bg-slate-50 border-b border-slate-200"><tr>'
        '<th class="px-4 py-2 text-xs font-medium uppercase tracking-wide text-slate-600">Case</th>'
        '<th class="px-4 py-2 text-xs font-medium uppercase tracking-wide text-slate-600">Expected</th>'
        '<th class="px-4 py-2 text-xs font-medium uppercase tracking-wide text-slate-600">Predicted</th>'
        '<th class="px-4 py-2 text-xs font-medium uppercase tracking-wide text-slate-600 text-right">Confidence</th>'
        '<th class="px-4 py-2 text-xs font-medium uppercase tracking-wide text-slate-600 text-right">Latency</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        "</table></div></section>"
    )


def generate_html(payload: dict[str, Any], out_path: Path) -> None:
    metrics = payload.get("metrics", {})
    failures = payload.get("failure_cases", [])
    input_counts = payload.get("per_condition_counts_input", {})

    body = (
        _summary_card(metrics)
        + _topline_metrics(metrics)
        + _per_condition_table(metrics, input_counts)
        + _confusion_matrix_html(metrics)
        + _latency_card(metrics)
        + _failures_section(failures)
    )

    skipped_count = len(payload.get("skipped", []))
    header_html = (
        '<header class="mb-6">'
        '<h1 class="text-2xl font-bold text-slate-900">DermAssist VN — Eval Report</h1>'
        f'<div class="text-sm text-slate-600 mt-1">Run: '
        f'<span class="font-mono">{html.escape(payload["run_id"])}</span></div>'
        '<div class="mt-2 grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">'
        f'<div><span class="text-slate-500">Model:</span> '
        f'<span class="font-mono text-slate-800">{html.escape(payload.get("model_version",""))}</span></div>'
        f'<div><span class="text-slate-500">Prompt:</span> '
        f'<span class="font-mono text-slate-800">{html.escape(payload.get("prompt_version",""))}</span></div>'
        f'<div><span class="text-slate-500">Gold size:</span> '
        f'<span class="font-mono text-slate-800">{payload.get("gold_set_size",0)}</span></div>'
        f'<div><span class="text-slate-500">Scored / skipped:</span> '
        f'<span class="font-mono text-slate-800">{payload.get("scored",0)} / {skipped_count}</span></div>'
        '</div></header>'
    )

    footer_html = (
        '<footer class="mt-12 pt-6 border-t border-slate-200 text-xs text-slate-500">'
        'See <a class="underline" href="../../docs/eval-limitations.md">'
        'docs/eval-limitations.md</a> for sample-size and tier-label provenance. '
        'Generated by <code>python -m eval.runner</code>.'
        '</footer>'
    )

    document = (
        "<!doctype html>\n"
        '<html lang="en"><head>'
        '<meta charset="utf-8">'
        f'<title>Eval Report — {html.escape(payload["run_id"])}</title>'
        '<script src="https://cdn.tailwindcss.com"></script>'
        '<style>body { font-family: -apple-system, BlinkMacSystemFont, '
        '"Segoe UI", Roboto, sans-serif; }</style>'
        '</head>'
        '<body class="bg-slate-50 min-h-screen">'
        '<main class="max-w-6xl mx-auto px-6 py-8">'
        f'{header_html}{body}{footer_html}'
        '</main></body></html>'
    )
    out_path.write_text(document, encoding="utf-8")


def generate_from_json(json_path: Path, html_path: Path | None = None) -> Path:
    """Standalone helper: regenerate HTML from an existing JSON file."""
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    if html_path is None:
        html_path = json_path.with_suffix(".html")
    generate_html(payload, html_path)
    return html_path
