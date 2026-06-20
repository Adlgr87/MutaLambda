"""
Compatibility entrypoint for the legacy Inferless adapter.

The implementation now lives in [`legacy/inferless_wrapper.py`](legacy/inferless_wrapper.py:1)
so the core evolutionary engine does not pull HuggingFace/Torch dependencies.
"""

from __future__ import annotations

from legacy.inferless_wrapper import InferlessPythonModel

__all__ = ["InferlessPythonModel"]
