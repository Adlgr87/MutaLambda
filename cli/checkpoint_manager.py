"""
Checkpoint manager for MutaLambda CLI.

Uses JSON (+ optional gzip), never pickle (ML-CK01 / ML-CK02).
"""

from __future__ import annotations

import gzip
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.table import Table

from cli.animator import RetroAnimator


class CheckpointManager:
    """Manages evolution checkpoints as JSON artifacts."""

    def __init__(
        self,
        checkpoint_dir: str = "checkpoints",
        animator: Optional[RetroAnimator] = None,
    ):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.animator = animator or RetroAnimator()
        self.console = Console()
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        state: Dict[str, Any],
        generation: int,
        metadata: Optional[Dict[str, Any]] = None,
        compress: bool = True,
        score: Optional[float] = None,
    ) -> str:
        """Save evolution state to a JSON checkpoint.

        Signature supports both:
        - save(state, generation, metadata=...)
        - legacy CLI calls that pass generation/score/state positionally via wrappers
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"gen_{generation:04d}_{timestamp}.json"
        filepath = self.checkpoint_dir / filename

        checkpoint = {
            "version": "4.0.0",
            "format": "json",
            "generation": generation,
            "timestamp": timestamp,
            "best_score": score if score is not None else state.get("best_score"),
            "state": state,
            "metadata": metadata or {},
        }

        try:
            payload = json.dumps(checkpoint, indent=2, ensure_ascii=False, default=str)
            if compress:
                actual_path = filepath.with_suffix(".json.gz")
                with gzip.open(actual_path, "wt", encoding="utf-8") as f:
                    f.write(payload)
            else:
                actual_path = filepath
                actual_path.write_text(payload, encoding="utf-8")

            self.animator.success_message(f"Checkpoint saved: {actual_path.name}")
            return str(actual_path)
        except Exception as e:
            self.animator.error_message(f"Failed to save checkpoint: {e}")
            return ""

    def load(self, checkpoint_path: str) -> Optional[Dict[str, Any]]:
        """Load evolution state from a JSON checkpoint (rejects pickle)."""
        path = Path(checkpoint_path)

        if not path.exists():
            self.animator.error_message(f"Checkpoint not found: {checkpoint_path}")
            return None

        try:
            if path.suffix == ".gz" or path.name.endswith(".json.gz"):
                with gzip.open(path, "rt", encoding="utf-8") as f:
                    raw = f.read()
            else:
                raw = path.read_text(encoding="utf-8")

            # Hard reject pickle payloads.
            if raw.startswith("\x80") or "pickle" in path.suffix.lower():
                raise ValueError("Pickle checkpoints are no longer supported (use JSON)")

            checkpoint = json.loads(raw)
            if not isinstance(checkpoint, dict):
                raise ValueError("Invalid checkpoint structure")

            self.animator.success_message(
                f"Loaded checkpoint: {path.name} "
                f"(generation {checkpoint.get('generation', '?')})"
            )
            # Flatten common fields for CLI consumers.
            if "best_score" not in checkpoint and "state" in checkpoint:
                checkpoint["best_score"] = checkpoint["state"].get("best_score", 0.0)
            return checkpoint
        except Exception as e:
            self.animator.error_message(f"Failed to load checkpoint: {e}")
            return None

    def list_checkpoints(self, sort_by: str = "time") -> List[Dict[str, Any]]:
        """List all available JSON checkpoints."""
        checkpoints: List[Dict[str, Any]] = []
        patterns = ["*.json", "*.json.gz"]
        files = []
        for pattern in patterns:
            files.extend(self.checkpoint_dir.glob(pattern))

        for filepath in files:
            try:
                stat = filepath.stat()
                generation: Any = "?"
                timestamp: Any = "?"
                metadata: Dict[str, Any] = {}
                try:
                    data = self.load(str(filepath))
                    if data:
                        generation = data.get("generation", "?")
                        timestamp = data.get("timestamp", "?")
                        metadata = data.get("metadata", {})
                except Exception:
                    pass

                checkpoints.append(
                    {
                        "path": str(filepath),
                        "filename": filepath.name,
                        "generation": generation,
                        "timestamp": timestamp,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime),
                        "metadata": metadata,
                    }
                )
            except Exception as e:
                self.animator.warning_message(f"Failed to read {filepath.name}: {e}")

        if sort_by == "time":
            checkpoints.sort(key=lambda x: x["modified"], reverse=True)
        elif sort_by == "generation":
            checkpoints.sort(
                key=lambda x: x["generation"] if isinstance(x["generation"], int) else -1,
                reverse=True,
            )
        elif sort_by == "size":
            checkpoints.sort(key=lambda x: x["size"], reverse=True)

        return checkpoints

    def cleanup(self, keep_last: int = 10) -> int:
        """Delete older checkpoints, keeping the newest N."""
        items = self.list_checkpoints(sort_by="time")
        removed = 0
        for item in items[keep_last:]:
            try:
                Path(item["path"]).unlink(missing_ok=True)
                removed += 1
            except OSError:
                pass
        return removed

    def display_list(self) -> None:
        self.display_checkpoints(self.list_checkpoints())

    def display_checkpoints(self, items: Optional[List[Dict[str, Any]]] = None) -> None:
        items = items if items is not None else self.list_checkpoints()
        table = Table(title="Checkpoints")
        table.add_column("Generation")
        table.add_column("Timestamp")
        table.add_column("Size")
        table.add_column("Path")
        for item in items:
            table.add_row(
                str(item["generation"]),
                str(item["timestamp"]),
                f"{item['size']} B",
                item["filename"],
            )
        self.console.print(table)

    def clean_old_checkpoints(self, max_age_days: int = 30) -> int:
        """Remove checkpoints older than max_age_days."""
        removed = 0
        cutoff = time.time() - (max_age_days * 86400)
        for item in self.list_checkpoints():
            path = Path(item["path"])
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                pass
        return removed
