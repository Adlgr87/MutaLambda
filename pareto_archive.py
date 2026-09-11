"""Pareto archive (FASE 3 — A5).

A warm-start store indexed by **API signature hash**: the canonical hash of
the target's public API fingerprint (function/class names + signatures).
Two functions that expose the same public API map to the same bucket, so a
previous optimisation of a *similar* function becomes a strong seed for the
next run.

Layout (default ``pareto_archive/``):

    pareto_archive/
      index.json            {signature_hash: {"file": ..., "updated": ...}}
      <hash[:16]>.json      {code, fitness, score, hypervolume, generation,
                             updated_at, profile}

Archive entries are plain JSON — inspectable, diff-able, safe to commit if
the project wants.  All operations are flag-gated at the call sites
(``pareto_archive.enabled`` / ``--no-warm-start``).
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = ["ParetoArchive", "signature_hash"]


def _canonical_api(source: str) -> str:
    """Canonical JSON of the target's public API (name-ordered)."""
    try:
        from api_fingerprint import extract_api_fingerprint

        fp = extract_api_fingerprint(source)
    except Exception:
        # Unparseable/unknown source: fall back to a hash of the raw source
        # (no cross-matching, but the archive still works for exact repeats).
        return "raw:" + hashlib.sha256(source.encode("utf-8", "replace")).hexdigest()
    payload = {
        "functions": [
            {
                "name": f.name,
                "args": list(f.arg_names),
                "defaults": f.defaults_count,
                "varargs": f.has_varargs,
                "varkw": f.has_varkw,
                "async": f.is_async,
            }
            for f in sorted(fp.functions.values(), key=lambda x: x.name)
        ],
        "classes": [
            {
                "name": c.name,
                "methods": list(c.methods),
                "bases": list(c.bases),
            }
            for c in sorted(fp.classes.values(), key=lambda x: x.name)
        ],
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def signature_hash(source: str) -> str:
    """Canonical hash of the public API — the archive bucket key."""
    return hashlib.sha256(_canonical_api(source).encode("utf-8")).hexdigest()


class ParetoArchive:
    """File-backed archive of best individuals, keyed by API signature."""

    def __init__(self, directory: str | Path = "pareto_archive") -> None:
        self.dir = Path(directory)
        self.index_path = self.dir / "index.json"

    # ── internals ─────────────────────────────────────────────────────────
    def _load_index(self) -> Dict[str, Dict[str, Any]]:
        if not self.index_path.exists():
            return {}
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_index(self, index: Dict[str, Dict[str, Any]]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps(index, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )

    def _entry_path(self, sig: str) -> Path:
        return self.dir / f"{sig[:16]}.json"

    # ── public ────────────────────────────────────────────────────────────
    def store(
        self,
        source: str,
        code: str,
        *,
        fitness: Optional[Dict[str, Any]] = None,
        score: float = 0.0,
        hypervolume: float = 0.0,
        generation: int = 0,
        profile: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store *code* as the archive entry for *source*'s API signature.

        Replaces any existing entry for the same signature (the archive keeps
        the latest best, not a set — the selection pressure for *better*
        entries is applied by the caller).
        Returns the signature hash.
        """
        sig = signature_hash(source)
        entry = {
            "signature_hash": sig,
            "code": code,
            "fitness": fitness or {},
            "score": float(score),
            "hypervolume": float(hypervolume),
            "generation": int(generation),
            "profile": profile,
            "updated_at": time.time(),
            "extra": extra or {},
        }
        self.dir.mkdir(parents=True, exist_ok=True)
        self._entry_path(sig).write_text(
            json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        index = self._load_index()
        index[sig] = {"file": self._entry_path(sig).name, "updated": entry["updated_at"]}
        self._save_index(index)
        return sig

    def lookup(self, source: str) -> Optional[Dict[str, Any]]:
        """Warm-start entry for *source*'s signature, or None."""
        sig = signature_hash(source)
        index = self._load_index()
        meta = index.get(sig)
        if not meta:
            return None
        path = self.dir / str(meta.get("file", f"{sig[:16]}.json"))
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def list_entries(self) -> List[Dict[str, Any]]:
        index = self._load_index()
        out: List[Dict[str, Any]] = []
        for sig, meta in index.items():
            path = self.dir / str(meta.get("file", f"{sig[:16]}.json"))
            if path.exists():
                try:
                    out.append(json.loads(path.read_text(encoding="utf-8")))
                except Exception:
                    continue
        out.sort(key=lambda e: e.get("updated_at", 0.0), reverse=True)
        return out

    def clear(self) -> None:
        """Remove every entry + the index (test/dev helper)."""
        if not self.dir.exists():
            return
        for path in self.dir.glob("*.json"):
            try:
                path.unlink()
            except Exception:
                pass
