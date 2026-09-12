"""Per-session and per-island RNG streams (workflow alta prioridad #13).

Provides reproducible Random instances derived from a master seed without
sharing mutable global random state across islands.
"""

from __future__ import annotations

import hashlib
import os
import random
from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np


def _derive_seed(master: int, *parts: str) -> int:
    h = hashlib.sha256()
    h.update(str(master).encode("utf-8"))
    for p in parts:
        h.update(b"\0")
        h.update(p.encode("utf-8"))
    return int.from_bytes(h.digest()[:8], "big") % (2**32 - 1)


@dataclass
class RNGSession:
    """Master seed + named streams for islands / modules."""

    master_seed: Optional[int] = None
    _streams: Dict[str, random.Random] = field(default_factory=dict)
    _np_streams: Dict[str, np.random.Generator] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.master_seed is None:
            self.master_seed = random.SystemRandom().randint(0, 2**31 - 1)
        # SECURITY/FIX (F6): Do NOT call random.seed() / np.random.seed() on
        # the global RNG — that contaminates the process-global state and
        # breaks determinism when running independent parallel experiments.
        # Only local random.Random / np.random.Generator instances (created
        # via stream()/numpy_stream()) are used for reproducible stochastic
        # operations. The legacy global calls below are kept as a no-op
        # fallback guarded by an env var for backward compatibility only.
        if os.environ.get("MUTALAMBDA_LEGACY_SEED_GLOBAL", "0") == "1":
            random.seed(self.master_seed)
            np.random.seed(self.master_seed % (2**32 - 1))

    def stream(self, name: str) -> random.Random:
        if name not in self._streams:
            seed = _derive_seed(int(self.master_seed), name)
            self._streams[name] = random.Random(seed)
        return self._streams[name]

    def numpy_stream(self, name: str) -> np.random.Generator:
        if name not in self._np_streams:
            seed = _derive_seed(int(self.master_seed), "np", name)
            self._np_streams[name] = np.random.default_rng(seed)
        return self._np_streams[name]

    def island(self, island_id: int) -> random.Random:
        return self.stream(f"island:{island_id}")
