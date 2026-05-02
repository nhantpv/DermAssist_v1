"""OpenAI vision client. Single function: diagnose(image_b64, note) -> dict."""
from __future__ import annotations
import base64
import json
import logging
from typing import Any

from openai import OpenAI

from demo.prompt import build_system_prompt

logger = logging.getLogger(__name__)
_client = OpenAI()  # reads OPENAI_API_KEY from env
_SYSTEM_PROMPT = build_system_prompt()  # built once at import


def diagnose(image_bytes: bytes, clinical_note: str, *, model: str = "gpt-4o-mini") -> dict[str, Any]:
    """Send image + note to OpenAI, parse JSON response, return dict.

    Raises ValueError if response is not valid JSON.
    """
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    user_text = clinical_note.strip() or "Không có ghi chú lâm sàng từ bác sĩ."

    response = _client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Ghi chú lâm sàng:\n{user_text}"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                ],
            },
        ],
        temperature=0.0,
        max_tokens=1500,
        timeout=60.0,
    )

    raw = response.choices[0].message.content or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("OpenAI returned non-JSON: %s", raw[:500])
        raise ValueError(f"Model returned invalid JSON: {e}") from e
