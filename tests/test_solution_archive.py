"""
Tests for SolutionArchive — FAISS-based memory, Novelty Search,
Curriculum Learning, persistence and telemetry.

Note (FIX 4.1): intentionally separate from test_nsga2.py — archive covers
embedding/novelty APIs, not FitnessVector Pareto selection. Shared fixtures
live in tests/conftest.py when needed.

These tests mock SentenceTransformer and FAISS to avoid heavy
dependency downloads during CI.

Run:  pytest test_solution_archive.py -v
"""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ── Mock heavy deps BEFORE importing muta_lambda ─────────────────────────
# Esto evita que el import falle si faiss/sentence-transformers no están instalados.

_mock_st = MagicMock()
_mock_st.return_value.encode.return_value = np.random.randn(1, 384).astype("float32")
_mock_st.return_value.get_sentence_embedding_dimension.return_value = 384

# Mock faiss with Kmeans and write_index/read_index
_mock_faiss = MagicMock()
_mock_faiss.write_index = MagicMock()
_mock_faiss.read_index = MagicMock(return_value=MagicMock())
_mock_faiss.Kmeans = MagicMock()

with patch.dict("sys.modules", {
    "sentence_transformers": MagicMock(SentenceTransformer=_mock_st),
    "faiss": _mock_faiss,
}):
    import muta_lambda
    from muta_lambda import SolutionArchive


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def archive():
    """Create a SolutionArchive with mocked dependencies."""
    # Ensure muta_lambda.faiss points to our mock
    muta_lambda.faiss = _mock_faiss

    with patch.object(SolutionArchive, "__init__", lambda self, **kw: None):
        arch = SolutionArchive.__new__(SolutionArchive)

    # Mock essential attributes
    arch._dim = 384
    arch._lock = __import__("threading").Lock()
    arch._pending_prunes = 0
    arch.solutions = __import__("collections").deque(maxlen=1000)
    arch.max_size = 1000
    arch.prune_threshold = 50

    # Mock embedder: encode returns random normalized vectors
    mock_embedder = MagicMock()
    mock_embedder.get_sentence_embedding_dimension.return_value = 384

    def _fake_encode(texts, **kwargs):
        vectors = []
        for text in texts:
            seed = abs(hash(text)) % (2**32)
            rng = np.random.default_rng(seed)
            vec = rng.standard_normal(384, dtype=np.float32)
            norm = np.linalg.norm(vec) + 1e-9
            vectors.append(vec / norm)
        return np.vstack(vectors).astype("float32")

    mock_embedder.encode = _fake_encode
    arch.embedder = mock_embedder

    # Mock FAISS index
    mock_index = MagicMock()
    arch.index = mock_index

    # Rebind _encode_normalized to use the mocked embedder
    def _fake_encode_norm(texts):
        return arch.embedder.encode(texts)

    arch._encode_normalized = _fake_encode_norm

    return arch


def _add_solution(arch: SolutionArchive, code: str):
    """Helper: add a solution to the archive."""
    from muta_lambda import ArchivedSolution
    emb = arch._encode_normalized([code])[0]
    arch.solutions.append(
        ArchivedSolution(code=code, metrics={}, embedding=emb)
    )
    arch.index.add.return_value = None  # mock


# ── Tests ────────────────────────────────────────────────────────────────

class TestNoveltyScore:
    """Core Novelty Search tests."""

    def test_empty_archive_returns_max_novelty(self, archive):
        """Empty archive → maximum novelty (1.0)."""
        arch = archive
        arch.index.search.return_value = (np.array([[0.0]]), np.array([[0]]))
        score = arch.novelty_score("def f(): return 1")
        assert score == 1.0

    def test_identical_code_returns_low_novelty(self, archive):
        """Code identical to something in archive → low novelty."""
        arch = archive
        _add_solution(arch, "def f(): return 1")
        arch.index.search.return_value = (np.array([[0.99]]), np.array([[0]]))
        score = arch.novelty_score("def f(): return 1")
        assert score < 0.05

    def test_different_code_returns_high_novelty(self, archive):
        """Structurally different code → high novelty."""
        arch = archive
        _add_solution(arch, "def f(x): return x + 1")
        arch.index.search.return_value = (np.array([[0.1]]), np.array([[0]]))
        score = arch.novelty_score("def g(y):\n    return y * y")
        assert score > 0.2

    def test_novelty_bounded_0_to_2(self, archive):
        """Novelty score for normalized embeddings stays in [0, 2]."""
        arch = archive
        _add_solution(arch, "def f(): pass")

        arch.index.search.return_value = (np.array([[0.0]]), np.array([[0]]))
        assert 0.0 <= arch.novelty_score("x") <= 2.0

        arch.index.search.return_value = (np.array([[1.0]]), np.array([[0]]))
        assert 0.0 <= arch.novelty_score("x") <= 2.0


class TestDiverseSample:
    """Curriculum Learning — diverse sample retrieval."""

    def test_empty_archive_returns_empty(self, archive):
        arch = archive
        assert arch.get_diverse_sample(k=5) == []

    def test_fewer_than_k_returns_all(self, archive):
        arch = archive
        for code in ["a", "b", "c"]:
            _add_solution(arch, code)
        result = arch.get_diverse_sample(k=10)
        assert len(result) == 3

    def test_returns_k_diverse(self, archive):
        """With 30 solutions, get_diverse_sample returns ≤ k codes."""
        arch = archive
        for i in range(30):
            _add_solution(arch, f"def f{i}(): return {i}")

        # Inject mock faiss.Kmeans directly into the module
        mock_kmeans = MagicMock()
        mock_kmeans.train = MagicMock()
        mock_kmeans.index.search.return_value = (
            np.random.randn(30, 1).astype("float32"),
            np.array([[i % 5] for i in range(30)], dtype="int64"),
        )
        original_kmeans = muta_lambda.faiss.Kmeans
        muta_lambda.faiss.Kmeans = MagicMock(return_value=mock_kmeans)
        try:
            result = arch.get_diverse_sample(k=5)
        finally:
            muta_lambda.faiss.Kmeans = original_kmeans
        assert len(result) <= 5
        assert all(isinstance(c, str) for c in result)


class TestPersistence:
    """Save / Load round-trip."""

    def test_save_and_load_roundtrip(self, archive, tmp_path):
        arch = archive
        for code in ["def a(): return 1", "def b(): return 2"]:
            _add_solution(arch, code)

        save_path = str(tmp_path / "archive_test")

        # Inject mock for faiss.write_index
        original_write = muta_lambda.faiss.write_index
        muta_lambda.faiss.write_index = MagicMock(
            side_effect=lambda idx, path: open(path, "wb").close()
        )
        try:
            arch.save(save_path)
        finally:
            muta_lambda.faiss.write_index = original_write

        assert os.path.exists(f"{save_path}.index")
        assert os.path.exists(f"{save_path}.json")

        # Verify JSON content
        with open(f"{save_path}.json") as f:
            meta = json.load(f)
        assert len(meta) == 2
        assert meta[0]["code"] == "def a(): return 1"

    def test_save_creates_directories(self, archive, tmp_path):
        arch = archive
        _add_solution(arch, "x")
        deep_path = str(tmp_path / "deep" / "nested" / "archive")
        arch.save(deep_path)
        assert os.path.exists(f"{deep_path}.json")


class TestStats:
    """Archive telemetry."""

    def test_empty_stats(self, archive):
        arch = archive
        s = arch.stats()
        assert s["total_solutions"] == 0
        assert s["mean_pairwise_similarity"] == 0.0
        assert s["embedding_dim"] == 384

    def test_populated_stats(self, archive):
        arch = archive
        for i in range(10):
            _add_solution(arch, f"def f{i}(): return {i}")
        s = arch.stats()
        assert s["total_solutions"] == 10
        assert s["embedding_dim"] == 384
        # mean pairwise similarity should be computed
        assert isinstance(s["mean_pairwise_similarity"], float)
