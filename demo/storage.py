"""In-memory encounter store. Resets on process restart — fine for demo."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

# username -> list[dict]
_encounters_by_user: dict[str, list[dict[str, Any]]] = {}


def create_encounter(username: str, payload: dict[str, Any]) -> str:
    eid = str(uuid4())
    record = {
        "id": eid,
        "username": username,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    _encounters_by_user.setdefault(username, []).append(record)
    return eid


def get_encounter(username: str, eid: str) -> dict[str, Any] | None:
    for r in _encounters_by_user.get(username, []):
        if r["id"] == eid:
            return r
    return None


def list_encounters(username: str) -> list[dict[str, Any]]:
    # newest first
    return sorted(
        _encounters_by_user.get(username, []),
        key=lambda r: r["created_at"],
        reverse=True,
    )
