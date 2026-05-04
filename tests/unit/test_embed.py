"""Embedder smoke test. Loads the model — slowest unit test.
Skipped if sentence-transformers not installed."""
import pytest

pytest.importorskip("sentence_transformers")


def test_embed_query_returns_384_dims():
    from backend.retrieval.embed import embed_query
    vec = embed_query("zona thần kinh điều trị")
    assert vec.shape == (384,)
    assert vec.dtype.name in ("float32", "float64")


def test_embed_query_normalized():
    """e5 with normalize_embeddings=True returns unit-length vectors."""
    import numpy as np
    from backend.retrieval.embed import embed_query
    vec = embed_query("herpes zoster treatment")
    norm = float(np.linalg.norm(vec))
    assert abs(norm - 1.0) < 1e-4


def test_embed_query_rejects_empty():
    from backend.retrieval.embed import embed_query
    with pytest.raises(ValueError):
        embed_query("")


def test_embed_query_deterministic():
    """Same input → same vector."""
    import numpy as np
    from backend.retrieval.embed import embed_query
    a = embed_query("viêm da cơ địa")
    b = embed_query("viêm da cơ địa")
    assert np.allclose(a, b)
