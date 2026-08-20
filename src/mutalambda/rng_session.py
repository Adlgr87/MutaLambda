"""Per-session and per-island RNG streams (workflow alta prioridad #13).

Provides reproducible Random instances derived from a master seed without
sharing mutable global random state across islands.
"""

from __future__ import annotations

import hashlib
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
        # Seed process-global for libraries that still use it (best-effort).
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
