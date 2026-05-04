"""Hybrid retrieval over QĐ-4416 chunks: BM25 + dense + RRF.

Public API: retrieve(query, k=5, condition_filter=None) -> list[Chunk]
"""
from backend.retrieval.models import Chunk
from backend.retrieval.rrf import retrieve

__all__ = ["Chunk", "retrieve"]
