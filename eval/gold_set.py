"""Load and validate data/gold_set.jsonl.

Cases whose `image_path` does not exist on disk are skipped with a
logged warning — the gold set may reference images not yet downloaded.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GoldCase:
    case_id: str
    image_path: Path
    expected_condition_key: str
    expected_tier: str
    expected_ood: bool
    fitzpatrick_type: int | None
    monk_tone: float | None
    source_dataset: str | None
    license: str | None
    notes: str | None


def _coerce(raw: dict, repo_root: Path) -> GoldCase | None:
    try:
        rel = raw.get("image_path") or ""
        path = (repo_root / rel) if rel else None
        if path is None:
            logger.warning("skip case (missing image_path): %s", raw.get("case_id"))
            return None
        if not path.exists():
            logger.warning("skip case (image not on disk): %s — %s", raw.get("case_id"), path)
            return None
        return GoldCase(
            case_id=str(raw["case_id"]),
            image_path=path,
            expected_condition_key=str(raw["expected_condition_key"]),
            expected_tier=str(raw["expected_tier"]),
            expected_ood=bool(raw["expected_ood"]),
            fitzpatrick_type=raw.get("fitzpatrick_type"),
            monk_tone=raw.get("monk_tone"),
            source_dataset=raw.get("source_dataset"),
            license=raw.get("license"),
            notes=raw.get("notes"),
        )
    except (KeyError, ValueError) as e:
        logger.warning("skip malformed case: %s — %s", raw, e)
        return None


def load_gold_set(path: Path, *, repo_root: Path | None = None) -> list[GoldCase]:
    """Read JSONL, skipping any line that's blank or invalid. Image
    paths are resolved relative to `repo_root` (default: parent of
    `path`'s parent — i.e. project root if path is `data/gold_set.jsonl`)."""
    if repo_root is None:
        repo_root = path.resolve().parent.parent
    cases: list[GoldCase] = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning("skip line %d (bad JSON): %s", line_no, e)
                continue
            case = _coerce(raw, repo_root)
            if case is not None:
                cases.append(case)
    return cases


def per_condition_counts(cases: Iterable[GoldCase]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in cases:
        out[c.expected_condition_key] = out.get(c.expected_condition_key, 0) + 1
    return out
