"""Fitness cache — memoizes evaluation scores by canonical code hash.

Lever A2 (Fase 0).  Evolutionary runs re-evaluate the same candidates over and
over (survivors are re-scored every generation, warm starts re-run archived
code).  This cache keys results by a *canonical* hash of the code so that
whitespace/comment formatting differences still hit:

* parseable Python → ``sha256("a:" + ast.dump(tree))`` (structural),
* anything else   → ``sha256("r:" + raw text)``.

Backends (flag ``fitness_cache.backend``):
* ``sqlite`` (default, stdlib only) — one row per key, ``ts`` for eviction;
* ``json`` — plain file, for platforms without a writable sqlite.

Both are capped at ``fitness_cache.max_entries`` (oldest-first eviction).
The cache is per-run state by default (open on demand, close at end of run)
but persists across processes when the same path is reused, which is what
makes warm-start (Fase 3) free of re-evaluation.
"""

from __future__ import annotations

import ast
import json
import sqlite3
import threading
import time
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = [
    "FitnessCache",
    "canonical_code_hash",
    "fitness_cache_key",
]


def canonical_code_hash(code: str) -> str:
    """Canonical structural hash of a candidate program.

    Parseable Python is hashed from ``ast.dump`` (whitespace- and
    comment-insensitive, attribute-free), everything else from the raw text.
    """
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return "r:" + sha256(code.encode("utf-8", errors="replace")).hexdigest()
    dumped = ast.dump(tree)
    return "a:" + sha256(dumped.encode("utf-8", errors="replace")).hexdigest()


def fitness_cache_key(namespace: str, code: str) -> str:
    """Namespace-scoped key: ``<namespace>:<canonical_hash>``.

    ``namespace`` isolates runs with different scorers (profile/seed).
    """
    return f"{namespace}:{canonical_code_hash(code)}"


class FitnessCache:
    """Score memo with hit/miss accounting. Values are arbitrary JSON."""

    def __init__(
        self,
        path: str | Path,
        backend: str = "sqlite",
        max_entries: int = 100_000,
        namespace: str = "default",
    ) -> None:
        self.path = Path(path)
        self.backend = backend
        self.max_entries = max(1, int(max_entries))
        self.namespace = namespace
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._put_count = 0
        self._conn: Optional[sqlite3.Connection] = None
        self._json: Dict[str, Dict[str, Any]] = {}
        if self.path.parent and str(self.path.parent) not in ("", "."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        if backend == "sqlite":
            self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS fitness ("
                "key TEXT PRIMARY KEY, ts REAL NOT NULL, value TEXT NOT NULL)"
            )
            self._conn.commit()
        elif backend == "json":
            if self.path.exists():
                try:
                    self._json = json.loads(self.path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    self._json = {}
        else:
            raise ValueError(f"unsupported fitness cache backend: {backend!r}")

    # ── Core API ─────────────────────────────────────────────────────────
    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if self.backend == "sqlite":
                assert self._conn is not None
                row = self._conn.execute(
                    "SELECT value FROM fitness WHERE key = ?", (key,)
                ).fetchone()
            else:
                row = (self._json.get(key, {}).get("value"),) if key in self._json else None
            if row is None:
                self._misses += 1
                return None
            self._hits += 1
            try:
                return json.loads(row[0])
            except (TypeError, json.JSONDecodeError):
                return None

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._put_count += 1
            payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
            now = time.time()
            if self.backend == "sqlite":
                assert self._conn is not None
                self._conn.execute(
                    "INSERT OR REPLACE INTO fitness (key, ts, value) VALUES (?, ?, ?)",
                    (key, now, payload),
                )
                self._conn.commit()
                self._evict_sqlite_locked()
            else:
                self._json[key] = {"ts": now, "value": payload}
                self._evict_json_locked()

    def close(self) -> None:
        with self._lock:
            if self.backend == "json" and self._put_count:
                try:
                    self.path.write_text(
                        json.dumps(self._json, ensure_ascii=False, sort_keys=True),
                        encoding="utf-8",
                    )
                except OSError:
                    pass
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None

    # ── Observability ────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "backend": self.backend,
                "path": str(self.path),
                "namespace": self.namespace,
                "hits": self._hits,
                "misses": self._misses,
                "puts": self._put_count,
                "hit_rate": (self._hits / total) if total else 0.0,
            }

    # ── Eviction ─────────────────────────────────────────────────────────
    def _evict_sqlite_locked(self) -> None:
        assert self._conn is not None
        (count,) = self._conn.execute("SELECT COUNT(*) FROM fitness").fetchone()
        if count <= self.max_entries:
            return
        excess = count - self.max_entries
        self._conn.execute(
            "DELETE FROM fitness WHERE key IN ("
            "SELECT key FROM fitness ORDER BY ts ASC LIMIT ?)",
            (excess,),
        )
        self._conn.commit()

    def _evict_json_locked(self) -> None:
        if len(self._json) <= self.max_entries:
            return
        excess = len(self._json) - self.max_entries
        oldest = sorted(self._json.items(), key=lambda kv: kv[1].get("ts", 0.0))[:excess]
        for key, _ in oldest:
            self._json.pop(key, None)


def batch_key_stats(keys: List[str]) -> Dict[str, int]:
    """Split *keys* into seen/unseen counts for a ``FitnessCache`` (no I/O)."""
    return {"n": len(keys)}
