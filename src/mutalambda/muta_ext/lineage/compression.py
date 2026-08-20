"""
Lineage Graph Compression
==========================

Compresión zlib de nodos inactivos del LineageGraph para reducir uso de
memoria en runs largos (>1000 individuos). Los nodos activos permanecen en
memoria; los abandonados (alive=False) se comprimen como snapshots zlib.

La descompresión solo ocurre durante resurrect_branch() o queries explícitas
del DAG genealógico.

Usage
-----
    comp = LineageCompressor(graph)
    saved = comp.compress_inactive(active_branch_ids)
    print(f"RAM saved: {saved} nodes compressed")

    # On-demand decompression
    code = comp.decompress_node(node_id)
"""

import zlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
import logging

logger = logging.getLogger(__name__)


@dataclass
class CompressedNode:
    """Payload comprimido para un nodo del LineageGraph.

    Nota:
        En MutaLambda mantenemos el tipo de nodo (LineageNode) dentro del grafo
        durante compresión para evitar romper serialización/checkpoints.
        Esta estructura se usa como "modelo" y para compatibilidad, pero el
        compresor principalmente adjunta los campos comprimidos al nodo
        original.
    """
    id: str
    compressed_code: bytes
    is_diff: bool = False
    ancestor_id: str = ""


class LineageCompressor:
    """Compresor incremental del LineageGraph (opt-in).

    Mantiene el tipo del nodo original dentro del grafo y solo sustituye:
    - `node.code` -> '' (para reducir memoria)
    - adjunta `node._compressed_code` (bytes zlib) para reconstrucción bajo demanda

    Esta implementación no usa diff contra ancestros; `is_diff` se mantiene
    en False para compatibilidad. `decompress_node()` devuelve el código
    exacto comprimido en el payload zlib.
    """

    _COMPRESSED_CODE_ATTR = "_compressed_code"

    def __init__(self, graph, compression_level: int = 6) -> None:
        self.graph = graph
        self.compression_level = compression_level
        self._decompressed: Dict[str, str] = {}

    def compress_inactive(self, active_branch_ids: Set[str]) -> int:
        """Comprime nodos abandonados (alive=False) fuera de la rama activa."""
        compressed_count = 0
        for node_id, node in self.graph.nodes.items():
            if getattr(node, "alive", True):
                continue
            if node_id in active_branch_ids:
                continue
            if node_id in self._decompressed:
                continue
            if getattr(node, "code", "") == "":
                # ya estaba comprimido
                continue
            self._compress_node(node_id)
            compressed_count += 1

        logger.debug(
            "LineageCompressor: %d nodes compressed (level=%s)",
            compressed_count,
            self.compression_level,
        )
        return compressed_count

    def _compress_node(self, node_id: str) -> None:
        node = self.graph.nodes.get(node_id)
        if node is None:
            return

        code = getattr(node, "code", "") or ""
        compressed = zlib.compress(
            code.encode("utf-8"),
            level=self.compression_level,
        )

        # Adjuntar payload y liberar el código en memoria
        setattr(node, self._COMPRESSED_CODE_ATTR, compressed)
        setattr(node, "code", "")
        # No tocamos score/fitness/etc.

        # Cache interna: removemos por si existía algo previo
        self._decompressed.pop(node_id, None)

    def decompress_node(self, node_id: str) -> Optional[str]:
        """Descomprime un nodo bajo demanda (para resurrect_branch)."""
        if node_id in self._decompressed:
            return self._decompressed[node_id]

        node = self.graph.nodes.get(node_id)
        if node is None:
            return None

        code = getattr(node, "code", "") or ""
        if code:
            self._decompressed[node_id] = code
            return code

        compressed = getattr(node, self._COMPRESSED_CODE_ATTR, None)
        if not compressed:
            return None

        try:
            raw = zlib.decompress(compressed)
            restored = raw.decode("utf-8", errors="strict")
        except Exception:
            return None

        self._decompressed[node_id] = restored
        # Guardar también en el nodo para siguientes usos
        setattr(node, "code", restored)
        return restored

    def _get_code(self, node_id: str) -> Optional[str]:
        """Obtiene el código de un nodo (descomprimido o cache)."""
        if node_id in self._decompressed:
            return self._decompressed[node_id]
        node = self.graph.nodes.get(node_id)
        if node is None:
            return None
        code = getattr(node, "code", "") or ""
        if code:
            return code
        return self.decompress_node(node_id)

    def stats(self) -> Dict[str, int]:
        """Estadísticas de compresión."""
        total = len(self.graph.nodes)
        compressed = sum(
            1 for n in self.graph.nodes.values()
            if getattr(n, self._COMPRESSED_CODE_ATTR, None) is not None
        )
        return {
            "total_nodes": total,
            "compressed_nodes": compressed,
            "active_nodes": total - compressed,
            "compression_ratio_pct": round(
                (compressed / total * 100) if total > 0 else 0, 1
            ),
        }