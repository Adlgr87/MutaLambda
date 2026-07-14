"""Solution archive with optional FAISS-backed semantic search."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from collections import deque
from typing import Deque, Dict, List, Tuple

import numpy as np

from models import ArchivedSolution

try:
    import faiss as _faiss_module
except ImportError:  # pragma: no cover - optional dependency
    _faiss_module = None  # type: ignore[assignment]

try:
    from sentence_transformers import SentenceTransformer as _SentenceTransformer
except ImportError:  # pragma: no cover - optional dependency
    _SentenceTransformer = None  # type: ignore[assignment,misc]

logger = logging.getLogger("MutaLambda")


def _get_faiss():
    """Return FAISS module, preferring the top-level compatibility global."""
    top_level = sys.modules.get("muta_lambda")
    return getattr(top_level, "faiss", None) or _faiss_module


def _get_sentence_transformer():
    """Return SentenceTransformer class, preferring top-level compatibility global."""
    top_level = sys.modules.get("muta_lambda")
    return getattr(top_level, "SentenceTransformer", None) or _SentenceTransformer


class SolutionArchive:
    """Memoria a largo plazo con búsqueda semántica por embeddings."""

    def __init__(
        self,
        embedder_model: str = "all-MiniLM-L6-v2",
        max_size: int = 10_000,
        prune_threshold: int = 50,
        dedupe_similarity: float = 0.98,
    ):
        sentence_transformer = _get_sentence_transformer()
        faiss = _get_faiss()
        if sentence_transformer is None or faiss is None:
            raise ImportError(
                "SolutionArchive requires faiss-cpu and sentence-transformers. "
                "Install them: pip install faiss-cpu sentence-transformers"
            )

        self.embedder = sentence_transformer(
            f"sentence-transformers/{embedder_model}"
        )
        # Prefer modern API when available (sentence-transformers rename).
        if hasattr(self.embedder, "get_embedding_dimension"):
            self._dim = self.embedder.get_embedding_dimension()
        else:
            self._dim = self.embedder.get_sentence_embedding_dimension()
        self.index = faiss.IndexFlatIP(self._dim)
        self.solutions: Deque[ArchivedSolution] = deque(maxlen=max_size)
        self.max_size = max_size
        self.prune_threshold = prune_threshold
        self.dedupe_similarity = float(dedupe_similarity)
        self._pending_prunes: int = 0
        self._lock = threading.RLock()
        self._dedupe_updates: int = 0

    def _encode_normalized(self, texts: List[str]) -> np.ndarray:
        """Encode + L2-normalize en batch."""
        embeddings = self.embedder.encode(
            texts, convert_to_numpy=True, show_progress_bar=False
        ).astype("float32")
        _get_faiss().normalize_L2(embeddings)
        return embeddings

    def _rebuild_index(self) -> None:
        """Reconstruye el índice FAISS desde self.solutions."""
        faiss = _get_faiss()
        self.index = faiss.IndexFlatIP(self._dim)
        if self.solutions:
            embeddings = np.vstack(
                [s.embedding.reshape(1, -1) for s in self.solutions]
            ).astype("float32")
            faiss.normalize_L2(embeddings)
            self.index.add(embeddings)

    def add(self, code: str, metrics: Dict[str, float]) -> None:
        """Agrega una solución al archivo con dedupe semántico (ML-L07) y pruning lazy.

        Si el vecino más cercano supera ``dedupe_similarity``, solo se actualizan
        las métricas del existente en lugar de insertar un duplicado semántico.
        """
        emb = self._encode_normalized([code])[0]

        with self._lock:
            # Semantic dedupe: nearest neighbor above threshold → update metadata.
            if self.solutions and self.index.ntotal > 0 and self.dedupe_similarity > 0:
                try:
                    scores, idxs = self.index.search(emb.reshape(1, -1), 1)
                    sim = float(scores[0][0])
                    idx = int(idxs[0][0])
                    if idx >= 0 and sim >= self.dedupe_similarity and idx < len(self.solutions):
                        existing = self.solutions[idx]
                        merged = dict(existing.metrics)
                        merged.update(metrics)
                        # Prefer higher scalar score if present.
                        if float(metrics.get("score", float("-inf"))) >= float(
                            existing.metrics.get("score", float("-inf"))
                        ):
                            existing.code = code
                            existing.embedding = emb
                        existing.metrics = merged
                        self._dedupe_updates += 1
                        return
                except Exception:
                    pass

            old_len = len(self.solutions)
            will_evict = len(self.solutions) == self.max_size

            self.index.add(emb.reshape(1, -1))
            self.solutions.append(
                ArchivedSolution(code=code, metrics=metrics, embedding=emb)
            )

            if will_evict and len(self.solutions) == old_len:
                self._pending_prunes += 1

            if self._pending_prunes >= self.prune_threshold:
                self._rebuild_index()
                self._pending_prunes = 0

    def add_batch(self, items: List[Tuple[str, Dict[str, float]]]) -> None:
        """Agrega múltiples soluciones en una sola operación de embedding."""
        if not items:
            return
        codes = [code for code, _ in items]
        embeddings = self._encode_normalized(codes)

        with self._lock:
            old_len = len(self.solutions)
            self.index.add(embeddings)
            for (code, metrics), emb in zip(items, embeddings):
                self.solutions.append(
                    ArchivedSolution(code=code, metrics=metrics, embedding=emb)
                )

            evicted = max(0, old_len + len(items) - self.max_size)
            self._pending_prunes += evicted
            if self._pending_prunes >= self.prune_threshold:
                self._rebuild_index()
                self._pending_prunes = 0

    def nearest(self, code: str, k: int = 5) -> List[ArchivedSolution]:
        """Retorna las k soluciones más similares semánticamente."""
        with self._lock:
            if not self.solutions:
                return []

            if self._pending_prunes > 0:
                self._rebuild_index()
                self._pending_prunes = 0

            emb = self._encode_normalized([code])
            k = min(k, len(self.solutions))
            distances, indices = self.index.search(emb, k)
            solution_list = list(self.solutions)
            return [solution_list[i] for i in indices[0] if 0 <= i < len(solution_list)]

    def novelty_score(self, code: str, k: int = 10) -> float:
        """Devuelve la distancia promedio a los k vecinos más cercanos."""
        neighbors = self.nearest(code, k=k)
        if not neighbors:
            return 1.0

        emb = self._encode_normalized([code])[0]
        distances = [
            float(np.linalg.norm(emb - neighbor.embedding))
            for neighbor in neighbors
        ]
        if not distances:
            return 1.0
        return float(np.mean(distances))

    def get_diverse_sample(self, k: int = 5) -> List[str]:
        """Curriculum Learning: retorna k soluciones diversas del archivo."""
        with self._lock:
            n = len(self.solutions)
            if n == 0:
                return []
            if n <= k:
                return [s.code for s in self.solutions]

            embs = np.vstack(
                [s.embedding.reshape(1, -1) for s in self.solutions]
            ).astype("float32")
            kmeans = _get_faiss().Kmeans(
                d=self._dim, k=k, niter=20, verbose=False, gpu=False
            )
            kmeans.train(embs)
            _, assignments = kmeans.index.search(embs, 1)
            diverse: List[str] = []
            seen_clusters: set = set()
            for idx, cluster in enumerate(assignments.flatten()):
                cluster_id = int(cluster)
                if cluster_id not in seen_clusters:
                    seen_clusters.add(cluster_id)
                    diverse.append(self.solutions[idx].code)
                    if len(diverse) >= k:
                        break
            return diverse

    def save(self, path: str) -> None:
        """Persiste el archivo a disco: índice FAISS + metadatos."""
        faiss = _get_faiss()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        with self._lock:
            if self._pending_prunes > 0:
                self._rebuild_index()
                self._pending_prunes = 0

            faiss.write_index(self.index, f"{path}.index")

            meta = [
                {
                    "code": s.code,
                    "metrics": s.metrics,
                    "timestamp": s.timestamp,
                }
                for s in self.solutions
            ]
            with open(f"{path}.json", "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)

        logger.info(
            "SolutionArchive saved: %d solutions → %s",
            len(self.solutions), path,
        )

    @classmethod
    def load(
        cls,
        path: str,
        embedder_model: str = "all-MiniLM-L6-v2",
    ) -> "SolutionArchive":
        """Carga un archivo previamente persistido con ``save()``."""
        sentence_transformer = _get_sentence_transformer()
        faiss = _get_faiss()
        if sentence_transformer is None or faiss is None:
            raise ImportError(
                "SolutionArchive.load() requires faiss-cpu and sentence-transformers."
            )

        archive = cls.__new__(cls)
        archive.embedder = sentence_transformer(
            f"sentence-transformers/{embedder_model}"
        )
        archive._dim = archive.embedder.get_sentence_embedding_dimension()
        archive._lock = threading.RLock()
        archive._pending_prunes = 0

        archive.index = faiss.read_index(f"{path}.index")

        with open(f"{path}.json", "r", encoding="utf-8") as f:
            meta = json.load(f)

        archive.max_size = max(10_000, len(meta) * 2)
        archive.prune_threshold = 50
        archive.solutions = deque(maxlen=archive.max_size)

        for entry in meta:
            emb = archive._encode_normalized([entry["code"]])[0]
            archive.solutions.append(
                ArchivedSolution(
                    code=entry["code"],
                    metrics=entry.get("metrics", {}),
                    embedding=emb,
                    timestamp=entry.get("timestamp", 0.0),
                )
            )

        logger.info(
            "SolutionArchive loaded: %d solutions from %s",
            len(archive.solutions), path,
        )
        return archive

    def stats(self) -> Dict[str, object]:
        """Métricas de telemetría del archivo para monitoreo."""
        with self._lock:
            total = len(self.solutions)
            if total < 2:
                mean_sim = 0.0
            else:
                sample = min(total, 500)
                embs = np.vstack(
                    [self.solutions[i].embedding.reshape(1, -1)
                     for i in range(sample)]
                ).astype("float32")
                sims = embs @ embs.T
                np.fill_diagonal(sims, 0.0)
                mean_sim = float(np.mean(sims)) if sample > 1 else 0.0

            return {
                "total_solutions": total,
                "prunes_pending": self._pending_prunes,
                "mean_pairwise_similarity": round(mean_sim, 6),
                "embedding_dim": self._dim,
            }

    @property
    def size(self) -> int:
        return len(self.solutions)
