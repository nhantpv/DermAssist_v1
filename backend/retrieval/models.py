"""Retrieval data shapes."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    """A retrieved chunk with provenance and content.

    Not a Pydantic model — no HTTP serialization happens at this
    layer. TIP-010 orchestrator wraps these in DiagnosisOutput.citations.
    """
    chunk_id: str
    doc_id: str
    section_title: str | None
    text: str
    chunk_index: int
    condition_tags: list[str]
    score: float
    source_url: str | None = None
