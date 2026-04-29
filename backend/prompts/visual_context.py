"""Load `data/visual_descriptions.json` and format for system prompt insertion.

The system prompt template (Blueprint §8) has a `{visual_context}` slot
that this helper fills. Output shape: per-condition section, each with
the Vietnamese name and a bullet list of observational descriptions.

This is a stub — TIP-005 will wire it into the FastAPI startup path so
the formatted block is cached at process start (it's static per build).

Example usage:

    from backend.prompts.visual_context import load_visual_context
    block = load_visual_context(Path("data/visual_descriptions.json"))
    # block fills {visual_context} in prompts/system.v1.0.0.md
"""

from __future__ import annotations

import json
from pathlib import Path


def load_visual_context(path: Path) -> str:
    """Read `visual_descriptions.json` and format for system-prompt insertion.

    Returns a string with one block per condition:

        Viêm da cơ địa:
          - <description 1>
          - <description 2>
          ...

        Nấm da:
          - <description 1>
          ...

    Conditions with `n_descriptions == 0` are emitted with a placeholder
    line so prompt-injection-style auditors can confirm coverage gaps
    aren't silently hidden.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    blocks: list[str] = []
    for _key, info in data["conditions"].items():
        if info["n_descriptions"] == 0:
            blocks.append(
                f"{info['name_vi']}:\n  (chưa có mô tả mẫu — system phải dựa hoàn toàn "
                "vào VLM cho điều kiện này)"
            )
            continue
        descs = "\n".join(
            f"  - {d['description']}" for d in info["descriptions"]
        )
        blocks.append(f"{info['name_vi']}:\n{descs}")
    return "\n\n".join(blocks)
