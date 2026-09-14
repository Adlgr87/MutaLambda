"""Tests for archive.py fixes (Issue #1, #7)."""
import pytest
import numpy as np

# Check dependencies BEFORE importing archive module
# (archive.py requires both faiss and sentence-transformers)
try:
    import faiss  # noqa: F401
    import sentence_transformers  # noqa: F401
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

if HAS_DEPS:
    from mutalambda_engines.archive import SolutionArchive
else:
    SolutionArchive = None

@pytest.mark.skipif(not HAS_DEPS, reason="faiss-cpu and sentence-transformers not installed")
def test_archive_faiss_sync_after_dedupe():
    """Issue #1: FAISS index must sync after dedupe merge."""
    archive = SolutionArchive(max_size=3, embedder_model="all-MiniLM-L6-v2")
    archive.add("def f(): pass", {"score": 0.5})
    archive.add("def f(): pass", {"score": 0.8})  # Should trigger dedupe
    # After dedupe, index should be consistent
    results = archive.nearest("def f(): return 1", k=1)
    assert len(results) > 0
    assert results[0].metrics["score"] == 0.8

@pytest.mark.skipif(not HAS_DEPS, reason="faiss-cpu and sentence-transformers not installed")
def test_archive_api_consistency():
    """Issue #7: Consistent sentence-transformers API."""
    archive = SolutionArchive(max_size=2, embedder_model="all-MiniLM-L6-v2")
    assert archive._dim > 0
