"""
Canonical AST Evaluation Cache
================================

Caché de evaluaciones keyeado por hash canónico del AST (no por string
de código). Si un mutante genera un AST idéntico a uno ya evaluado,
recupera el FitnessVector directamente sin ejecutar el sandbox.

Integración con SolutionArchive
--------------------------------
- El caché es independiente del índice FAISS (que almacena embeddings).
- Hits en caché evitan evaluación en sandbox, acelerando runs con
  mutaciones que producen código equivalente.

Security
--------
- NUNCA almacena código ejecutable. Solo hashes y métricas serializadas.
- El hash se computa sobre AST normalizado (sin nombres de variables,
  sin whitespace, sin comentarios).
"""

import ast
import hashlib
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


@dataclass
class CacheStats:
    """Estadísticas de uso del caché."""
    hits: int = 0
    misses: int = 0
    sandbox_saves: int = 0  # evaluaciones evitadas
    total_queries: int = 0

    @property
    def hit_ratio(self) -> float:
        if self.total_queries == 0:
            return 0.0
        return self.hits / self.total_queries


class CanonicalCache:
    """Caché thread-safe de evaluaciones por hash canónico de AST.

    Attributes
    ----------
    max_size : int
        Tamaño máximo del caché. LRU eviction cuando se excede.
    """
    def __init__(self, max_size: int = 10000):
        self._cache: Dict[str, dict] = {}
        self._lock = threading.RLock()
        self._max_size = max_size
        self._stats = CacheStats()

    @staticmethod
    def canonical_ast_hash(code: str) -> str:
        """Hash canónico del AST de un fragmento de código.

        Normaliza el AST eliminando nombres de variables (se reemplazan
        por placeholders), whitespace y comentarios. Dos fragmentos con
        la misma estructura pero distinto naming producen el mismo hash.

        Args:
            code: Código fuente Python.

        Returns:
            Hash SHA256 hexadecimal del AST normalizado.
        """
        try:
            tree = ast.parse(code)

            # Normalizar nombres de variables
            class _Normalizer(ast.NodeTransformer):
                def __init__(self):
                    self._counter = 0

                def visit_Name(self, node):
                    if isinstance(node.ctx, (ast.Store, ast.Load)):
                        self._counter += 1
                        return ast.Name(id=f"v{self._counter}", ctx=node.ctx)
                    return node

                def visit_arg(self, node):
                    self._counter += 1
                    return ast.arg(arg=f"a{self._counter}",
                                   annotation=node.annotation,
                                   type_comment=node.type_comment)

                def visit_FunctionDef(self, node):
                    self._counter += 1
                    node.name = f"f{self._counter}"
                    return self.generic_visit(node)

            normalizer = _Normalizer()
            normalized = normalizer.visit(tree)
            ast.fix_missing_locations(normalized)

            # Strip all position metadata (lineno, col_offset, end_lineno, end_col_offset)
            for node in ast.walk(normalized):
                for attr in ("lineno", "col_offset", "end_lineno", "end_col_offset"):
                    if hasattr(node, attr):
                        setattr(node, attr, 0)

            # Serializar a string canónico
            canonical = ast.dump(normalized, annotate_fields=False)
            return hashlib.sha256(canonical.encode()).hexdigest()
        except SyntaxError:
            # Código con errores de sintaxis — hash no normalizado
            return hashlib.sha256(code.encode()).hexdigest()

    def get(self, code: str) -> Optional[dict]:
        """Consulta el caché para un fragmento de código.

        Args:
            code: Código fuente Python.

        Returns:
            FitnessVector serializado como dict, o None si no está en caché.
        """
        key = self.canonical_ast_hash(code)
        with self._lock:
            self._stats.total_queries += 1
            if key in self._cache:
                self._stats.hits += 1
                return self._cache[key]
            self._stats.misses += 1
        return None

    def put(self, code: str, fitness_dict: dict) -> None:
        """Almacena una evaluación en el caché.

        Args:
            code: Código fuente evaluado.
            fitness_dict: FitnessVector serializado a dict.
        """
        key = self.canonical_ast_hash(code)
        with self._lock:
            if len(self._cache) >= self._max_size:
                # LRU simple: eliminar la entrada más antigua
                oldest = next(iter(self._cache))
                del self._cache[oldest]
            self._cache[key] = fitness_dict

    def stats(self) -> CacheStats:
        """Retorna estadísticas actuales del caché."""
        with self._lock:
            return CacheStats(
                hits=self._stats.hits,
                misses=self._stats.misses,
                sandbox_saves=self._stats.hits,
                total_queries=self._stats.total_queries,
            )

    def clear(self) -> None:
        """Limpia el caché completamente."""
        with self._lock:
            self._cache.clear()
            self._stats = CacheStats()