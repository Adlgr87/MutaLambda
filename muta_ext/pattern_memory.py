"""Pattern memory for reusable evolutionary knowledge."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Dict, List


@dataclass
class PatternRecord:
    """A reusable success pattern independent from full individuals."""

    pattern_type: str
    signature: str
    success_rate: float = 0.0
    contexts: List[str] = field(default_factory=list)
    lineage_refs: List[str] = field(default_factory=list)
    observations: int = 0


class PatternMemory:
    """Stores and retrieves compact success patterns for prompts and critique."""

    def __init__(self) -> None:
        self.records: Dict[str, PatternRecord] = {}

    def observe(self, pattern_type: str, signature: str, success: bool, context: str, lineage_ref: str) -> None:
        """Update pattern success statistics."""
        key = f"{pattern_type}:{signature}"
        rec = self.records.get(key)
        if rec is None:
            rec = PatternRecord(pattern_type=pattern_type, signature=signature)
            self.records[key] = rec
        rec.observations += 1
        rec.success_rate += ((1.0 if success else 0.0) - rec.success_rate) / rec.observations
        if context and context not in rec.contexts:
            rec.contexts.append(context)
        if lineage_ref and lineage_ref not in rec.lineage_refs:
            rec.lineage_refs.append(lineage_ref)

    def best(self, limit: int = 5) -> List[PatternRecord]:
        """Return best reusable patterns."""
        return sorted(
            self.records.values(),
            key=lambda rec: (rec.success_rate, rec.observations),
            reverse=True,
        )[:limit]

    def to_dict(self) -> Dict[str, object]:
        return {"records": {key: asdict(rec) for key, rec in self.records.items()}}

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "PatternMemory":
        memory = cls()
        records = data.get("records", {})
        if isinstance(records, dict):
            for key, raw in records.items():
                if isinstance(raw, dict):
                    memory.records[key] = PatternRecord(**raw)
        return memory

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, indent=2, ensure_ascii=False)
