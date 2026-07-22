"""Static call-graph extractor para UAST/Python AST."""

from __future__ import annotations
import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger("MutaLambda.UAST.CallGraph")


@dataclass(frozen=True)
class CallGraphNode:
    """Nodo en el call graph."""
    name: str
    file_path: str
    line_number: int = 0
    is_hot: bool = False


@dataclass(frozen=True)
class CallGraphEdge:
    """Arista dirigida en el call graph."""
    caller: CallGraphNode
    callee: CallGraphNode


@dataclass
class CallGraph:
    """Call graph representado como grafo directional."""
    nodes: Dict[str, CallGraphNode] = field(default_factory=dict)
    edges: List[CallGraphEdge] = field(default_factory=list)
    entry_points: Set[str] = field(default_factory=set)

    def add_node(self, node: CallGraphNode) -> None:
        """Añade un nodo al grafo."""
        key = f"{node.file_path}:{node.name}"
        if key not in self.nodes:
            self.nodes[key] = node
        elif not self.nodes[key].is_hot and node.is_hot:
            self.nodes[key] = CallGraphNode(node.name, node.file_path,
                                             node.line_number, True)

    def add_edge(self, caller: str, callee: str, caller_file: str = "", callee_file: str = "") -> None:
        """Añade una arista al grafo."""
        cn = self._find_or_create(caller, caller_file)
        cl = self._find_or_create(callee, callee_file)
        edge = CallGraphEdge(caller=cn, callee=cl)
        if edge not in self.edges:
            self.edges.append(edge)

    def _find_or_create(self, name: str, file_path: str) -> CallGraphNode:
        """Encuentra o crea un nodo."""
        key = f"{file_path}:{name}"
        if key in self.nodes:
            return self.nodes[key]
        node = CallGraphNode(name=name, file_path=file_path)
        self.nodes[key] = node
        return node

    def hot_subgraph(self, hot_names: Set[str], depth: int = 1) -> "CallGraph":
        """Extrae subgrafo alrededor de funciones hot con profundidad dada."""
        if depth < 0:
            depth = 0

        # Mark hot nodes
        for key, node in self.nodes.items():
            if node.name in hot_names:
                self.nodes[key] = CallGraphNode(node.name, node.file_path,
                                                 node.line_number, True)

        hot_keys = {k for k, n in self.nodes.items() if n.name in hot_names and n.is_hot}
        current = set(hot_keys)

        # Expand by depth (bidirectional - callers and callees)
        for _ in range(depth):
            nxt = set(current)
            for e in self.edges:
                ck = f"{e.caller.file_path}:{e.caller.name}"
                clk = f"{e.callee.file_path}:{e.callee.name}"
                if ck in current:
                    nxt.add(clk)
                if clk in current:
                    nxt.add(ck)
            current = nxt

        sub = CallGraph(entry_points=set(self.entry_points))
        for k, n in self.nodes.items():
            if k in current:
                sub.nodes[k] = n
        for e in self.edges:
            ck = f"{e.caller.file_path}:{e.caller.name}"
            clk = f"{e.callee.file_path}:{e.callee.name}"
            if ck in current and clk in current:
                sub.edges.append(e)
        return sub

    def edges_set(self) -> Set[Tuple[str, str]]:
        """Retorna conjunto de tuplas (caller, callee)."""
        return {(e.caller.name, e.callee.name) for e in self.edges}

    def __len__(self) -> int:
        """Número de nodos en el grafo."""
        return len(self.nodes)


# ── Extractors ────────────────────────────────────────────────

_BUILTINS: Set[str] = set(dir(__builtins__)) if hasattr(__builtins__, '__dir__') else set()
_EXTERNAL_PREFIXES = {"math.", "np.", "numpy.", "torch.", "tf.", "scipy.",
                      "pandas.", "pd.", "plt.", "random.", "os.", "sys."}


def extract_call_graph_from_ast(tree: ast.AST, file_path: str = "<single>") -> CallGraph:
    """Extrae call graph desde un árbol AST de Python.

    Args:
        tree: Árbol AST parseado
        file_path: Ruta del archivo fuente

    Returns:
        CallGraph con nodos y aristas
    """
    graph = CallGraph()

    # Add function definitions as nodes
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            graph.add_node(CallGraphNode(node.name, file_path, node.lineno))
            if node.name in ("main",) or node.name.startswith("entry"):
                graph.entry_points.add(node.name)

    # Add call edges
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            caller = node.name
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    callee = _extract_call_name(child)
                    if callee and not _is_external(callee):
                        graph.add_edge(caller, callee, file_path, file_path)

    return graph


def extract_call_graph_from_source(source: str, file_path: str = "<single>") -> Optional[CallGraph]:
    """Parsea código fuente y extrae call graph.

    Args:
        source: Código fuente Python
        file_path: Nombre del archivo

    Returns:
        CallGraph o None si hay error de sintaxis
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    return extract_call_graph_from_ast(tree, file_path)


def extract_call_graph_multi_file(file_paths: List[str]) -> CallGraph:
    """Extrae call graph de múltiples archivos.

    Args:
        file_paths: Lista de rutas a archivos fuente

    Returns:
        CallGraph combinado
    """
    sources: Dict[str, str] = {}
    for fp in file_paths:
        try:
            sources[fp] = Path(fp).read_text(encoding="utf-8")
        except (IOError, FileNotFoundError):
            logger.warning("Cannot read %s", fp)

    return extract_call_graph_from_sources(sources)


def extract_call_graph_from_sources(sources: Dict[str, str]) -> CallGraph:
    """Extrae call graph de múltiples fuentes.

    Args:
        sources: Dict {file_path: source_code}

    Returns:
        CallGraph combinado con tracking de imports
    """
    import_map: Dict[str, str] = {}
    all_graphs: Dict[str, CallGraph] = {}

    for file_path, source in sources.items():
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        # Track imports for cross-file resolution
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    import_map[alias.asname or alias.name] = file_path
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    import_map[alias.asname or alias.name] = file_path

        all_graphs[file_path] = extract_call_graph_from_ast(tree, file_path)

    merged = CallGraph()
    for g in all_graphs.values():
        for k, n in g.nodes.items():
            merged.add_node(n)
        merged.edges.extend(g.edges)
        merged.entry_points.update(g.entry_points)

    return merged


def _extract_call_name(call_node: ast.Call) -> Optional[str]:
    """Extrae el nombre de una llamada de función."""
    if isinstance(call_node.func, ast.Name):
        return call_node.func.id
    elif isinstance(call_node.func, ast.Attribute):
        return call_node.func.attr
    return None


def _is_external(name: str) -> bool:
    """Determina si un nombre es una función externa/builtin."""
    return name in _BUILTINS or any(name.startswith(p) for p in _EXTERNAL_PREFIXES)