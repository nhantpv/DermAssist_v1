"""Query embedding via multilingual-e5-small.

Single global model instance, loaded once. e5-small uses ~150MB RAM,
loads in ~3-5 sec on CPU at startup. Acceptable for closed beta.

Per the e5 model card: queries should be prefixed with 'query: '
before embedding for proper retrieval behavior.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_QUERY_PREFIX = "query: "
_PASSAGE_PREFIX = "passage: "  # Only used if we re-embed corpus; seed already did this

_model: Optional[object] = None
_load_lock = threading.Lock()


def _load_model():
    """Lazy load. Idempotent under concurrent calls via lock."""
    global _model
    if _model is not None:
        return _model
    with _load_lock:
        if _model is not None:
            return _model
        logger.info("Loading multilingual-e5-small embedder...")
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("intfloat/multilingual-e5-small")
        logger.info("Embedder loaded.")
        return _model


def warmup() -> None:
    """Force model load. Called from FastAPI lifespan startup so the
    first user request doesn't pay the cold-start cost."""
    _load_model()


def embed_query(text: str) -> np.ndarray:
    """Embed a query string. Returns 384-dim normalized float32 array."""
    if not text or not isinstance(text, str):
        raise ValueError("embed_query requires non-empty string")
    model = _load_model()
    vec = model.encode(
        [_QUERY_PREFIX + text],
        normalize_embeddings=True,
        convert_to_numpy=True,
    )[0]
    return vec.astype(np.float32)
