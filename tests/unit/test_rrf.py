"""Unit tests for Reciprocal Rank Fusion. No DB, no model load."""
from backend.retrieval.rrf import fuse_rrf, RRF_K


def test_empty_inputs():
    assert fuse_rrf([], []) == []


def test_single_retriever_only():
    bm25 = [("a", 0.9), ("b", 0.5), ("c", 0.1)]
    dense = []
    result = fuse_rrf(bm25, dense)
    assert [cid for cid, _ in result] == ["a", "b", "c"]
    assert result[0][1] > result[1][1] > result[2][1]


def test_overlap_boosts_score():
    """A chunk that ranks high in both retrievers should outrank
    chunks that only appear in one."""
    bm25 = [("shared", 1.0), ("bm25_only", 0.9)]
    dense = [("shared", 0.95), ("dense_only", 0.85)]
    result = fuse_rrf(bm25, dense)
    assert result[0][0] == "shared"
    assert result[0][1] > result[1][1]


def test_rrf_score_formula():
    """Verify the exact RRF formula on a tiny case."""
    bm25 = [("a", 999), ("b", 998)]
    dense = [("b", 0.9), ("a", 0.8)]
    result = fuse_rrf(bm25, dense)
    a_score = 1/(RRF_K + 1) + 1/(RRF_K + 2)
    b_score = 1/(RRF_K + 2) + 1/(RRF_K + 1)
    scores = dict(result)
    assert abs(scores["a"] - a_score) < 1e-9
    assert abs(scores["b"] - b_score) < 1e-9
    assert abs(scores["a"] - scores["b"]) < 1e-9


def test_no_duplicates_in_output():
    bm25 = [("a", 0.9), ("a", 0.5)]
    dense = []
    result = fuse_rrf(bm25, dense)
    ids = [cid for cid, _ in result]
    assert len(ids) == len(set(ids))


def test_custom_rrf_k():
    bm25 = [("a", 0.9)]
    dense = []
    r1 = fuse_rrf(bm25, dense, rrf_k=10)
    r2 = fuse_rrf(bm25, dense, rrf_k=100)
    assert r1[0][1] > r2[0][1]
