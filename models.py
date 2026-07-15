"""Core data structures shared by MutaLambda modules."""

from __future__ import annotations

import copy
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from code_hash import stable_code_hash
from fitness_vector import FitnessVector

# Re-export for backward-compatible imports (tests, external callers).
__all__ = [
    "stable_code_hash",
    "Individual",
    "LineageNode",
    "LineageGraph",
    "EvalResult",
    "IslandConfig",
    "ArchivedSolution",
    "PromptGenome",
]


@dataclass
class Individual:
    """Unidad evolutiva: un fragmento de código con su puntuación.

    ``score`` es el escalar agregado (retrocompatible).
    ``fitness`` es el vector multi‑objetivo completo (Fase 1/NSGA‑II).
    """

    code: str
    score: float = float("-inf")
    fitness: Optional[FitnessVector] = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    parent_ids: Optional[List[str]] = None
    tier: str = "laboratory"
    passed: bool = False
    record_lineage: bool = True
    evaluation_key: str = ""
    evaluated_at: float = 0.0
    benchmark_samples: List[float] = field(default_factory=list)

    def __lt__(self, other: "Individual") -> bool:
        return self.score < other.score

    def __repr__(self) -> str:
        return f"Individual(id={self.id}, score={self.score:.4f})"


@dataclass
class LineageNode:
    """Nodo en el DAG genealógico de la evolución.

    Cada individuo evaluado se registra como nodo. Los edges representan
    relaciones padre→hijo (mutación o crossover).
    """

    id: str
    generation: int
    score: float
    code_hash: str = ""  # stable sha256 hex; was unstable hash() int
    code: str = ""
    fitness: Dict[str, float] = field(default_factory=dict)
    island_id: int = 0
    parent_ids: List[str] = field(default_factory=list)
    imported_fragments: List[str] = field(default_factory=list)
    creation_reason: str = "mutation"
    alive: bool = True
    resurrected: bool = False
    # Lifecycle flags (ML-L04) — alive kept for backward compatibility.
    in_current_population: bool = False
    survived_last_generation: bool = False
    historical_node: bool = True


class LineageGraph:
    """DAG que registra la genealogía completa de una corrida evolutiva.

    Mantiene índices de adyacencia ``parents_of`` / ``children_of`` (ML-L02)
    para BFS O(E) en lugar de barridos O(N²) sobre todos los nodos.
    """

    def __init__(self) -> None:
        self.nodes: Dict[str, LineageNode] = {}
        self._roots: List[str] = []
        self._gen_map: Dict[int, List[str]] = {}
        self._resurrection_count: int = 0
        # Adjacency indexes (id → list of related ids)
        self.parents_of: Dict[str, List[str]] = {}
        self.children_of: Dict[str, List[str]] = {}

    def _index_edge(self, parent_id: str, child_id: str) -> None:
        self.parents_of.setdefault(child_id, [])
        if parent_id not in self.parents_of[child_id]:
            self.parents_of[child_id].append(parent_id)
        self.children_of.setdefault(parent_id, [])
        if child_id not in self.children_of[parent_id]:
            self.children_of[parent_id].append(child_id)

    def record(
        self,
        child: Individual,
        parents: List[Individual],
        generation: int,
        island_id: int,
        reason: str = "mutation",
    ) -> LineageNode:
        """Registra un nuevo individuo y sus padres en el DAG."""
        for parent in parents:
            parent_exists = parent.id in self.nodes
            if not parent_exists:
                # Prefer real parent code when available (ML-L03).
                p_code = parent.code or ""
                p_node = LineageNode(
                    id=parent.id,
                    generation=max(0, generation - 1),
                    score=parent.score,
                    code_hash=stable_code_hash(p_code) if p_code else "",
                    code=p_code,
                    fitness=(parent.fitness.to_dict() if parent.fitness else {}),
                    island_id=island_id,
                    parent_ids=parent.parent_ids or [],
                    alive=True,
                )
                self.nodes[parent.id] = p_node
                self._gen_map.setdefault(p_node.generation, []).append(parent.id)
                if not parent.parent_ids:
                    self._roots.append(parent.id)
                self.parents_of.setdefault(parent.id, list(parent.parent_ids or []))
                self.children_of.setdefault(parent.id, [])
            elif parent.code and not self.nodes[parent.id].code:
                # Fill placeholder empty code if we later see the real parent.
                self.nodes[parent.id].code = parent.code
                self.nodes[parent.id].code_hash = stable_code_hash(parent.code)

        child_node = LineageNode(
            id=child.id,
            generation=generation,
            score=child.score,
            code_hash=stable_code_hash(child.code),
            code=child.code,
            fitness=(child.fitness.to_dict() if child.fitness else {}),
            island_id=island_id,
            parent_ids=[p.id for p in parents],
            imported_fragments=list(getattr(child, "imported_fragments", [])),
            creation_reason=getattr(child, "creation_reason", reason),
            alive=True,
        )
        self.nodes[child.id] = child_node
        self._gen_map.setdefault(generation, []).append(child.id)
        self.parents_of[child.id] = [p.id for p in parents]
        self.children_of.setdefault(child.id, [])
        for parent in parents:
            self._index_edge(parent.id, child.id)
            pn = self.nodes.get(parent.id)
            if pn:
                pn.alive = False
                pn.survived_last_generation = False

        return child_node

    def get_ancestors(self, node_id: str, max_depth: int = -1) -> List[str]:
        """Cadena de ancestros (BFS hacia atrás vía parents_of)."""
        if node_id not in self.nodes:
            return []
        ancestors: List[str] = []
        visited: set = {node_id}
        queue: List[str] = [node_id]
        depth = 0
        while queue and (max_depth < 0 or depth < max_depth):
            current = queue.pop(0)
            parents = self.parents_of.get(current)
            if parents is None:
                node = self.nodes.get(current)
                parents = list(node.parent_ids) if node else []
            for pid in parents:
                if pid not in visited:
                    visited.add(pid)
                    ancestors.append(pid)
                    queue.append(pid)
            depth += 1
        return ancestors

    def get_descendants(self, node_id: str, max_depth: int = -1) -> List[str]:
        """BFS hacia adelante vía children_of."""
        if node_id not in self.nodes:
            return []
        out: List[str] = []
        visited: set = {node_id}
        queue: List[str] = [node_id]
        depth = 0
        while queue and (max_depth < 0 or depth < max_depth):
            current = queue.pop(0)
            for cid in self.children_of.get(current, []):
                if cid not in visited:
                    visited.add(cid)
                    out.append(cid)
                    queue.append(cid)
            depth += 1
        return out

    def get_genealogical_distance(self, id_a: str, id_b: str) -> Optional[int]:
        """Distancia genealógica (BFS no dirigido sobre índices)."""
        if id_a == id_b:
            return 0
        if id_a not in self.nodes or id_b not in self.nodes:
            return None

        visited: Dict[str, int] = {id_a: 0}
        queue: List[Tuple[str, int]] = [(id_a, 0)]

        while queue:
            current, dist = queue.pop(0)
            parents = self.parents_of.get(current)
            if parents is None:
                node = self.nodes.get(current)
                parents = list(node.parent_ids) if node else []
            children = self.children_of.get(current, [])
            neighbors = list(parents) + list(children)

            for neighbor in neighbors:
                if neighbor == id_b:
                    return dist + 1
                if neighbor not in visited:
                    visited[neighbor] = dist + 1
                    queue.append((neighbor, dist + 1))

        return None

    def find_abandoned_branches(
        self,
        current_best_id: str,
        threshold_score: float,
        max_candidates: int = 5,
    ) -> List[LineageNode]:
        """Busca ramas abandonadas con potencial para resurrección."""
        active_ancestors = set(self.get_ancestors(current_best_id))
        active_ancestors.add(current_best_id)

        candidates: List[LineageNode] = []
        for node_id, node in self.nodes.items():
            if node_id in active_ancestors:
                continue
            if node.score <= threshold_score:
                continue
            if node.resurrected:
                continue
            candidates.append(node)

        candidates.sort(key=lambda n: n.score, reverse=True)
        return candidates[:max_candidates]

    def stats(self) -> Dict[str, Any]:
        """Estadísticas resumidas del grafo genealógico."""
        if not self.nodes:
            return {"total_nodes": 0, "max_depth": 0, "branches": 0,
                    "resurrections": 0, "generations": 0}
        depths = [len(self.get_ancestors(n.id)) for n in self.nodes.values()]
        return {
            "total_nodes": len(self.nodes),
            "max_depth": max(depths),
            "avg_depth": round(sum(depths) / len(depths), 1),
            "branches": len(self._roots),
            "resurrections": self._resurrection_count,
            "generations": len(self._gen_map),
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serializa el grafo para checkpointing."""
        return {
            "nodes": {
                nid: {
                    "id": node.id,
                    "generation": node.generation,
                    "score": node.score,
                    "code_hash": node.code_hash,
                    "code": node.code,
                    "fitness": node.fitness,
                    "island_id": node.island_id,
                    "parent_ids": node.parent_ids,
                    "imported_fragments": node.imported_fragments,
                    "creation_reason": node.creation_reason,
                    "alive": node.alive,
                    "resurrected": node.resurrected,
                }
                for nid, node in self.nodes.items()
            },
            "roots": self._roots,
            "gen_map": self._gen_map,
            "resurrection_count": self._resurrection_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LineageGraph":
        """Restaura el grafo desde un checkpoint."""
        graph = cls()
        for nid, ndata in data.get("nodes", {}).items():
            node = LineageNode(
                id=ndata["id"],
                generation=ndata["generation"],
                score=ndata["score"],
                code_hash=ndata.get("code_hash", 0),
                code=ndata.get("code", ""),
                fitness=ndata.get("fitness", {}),
                island_id=ndata.get("island_id", 0),
                parent_ids=ndata.get("parent_ids", []),
                imported_fragments=ndata.get("imported_fragments", []),
                creation_reason=ndata.get("creation_reason", "mutation"),
                alive=ndata.get("alive", True),
                resurrected=ndata.get("resurrected", False),
            )
            graph.nodes[nid] = node
            graph.parents_of[nid] = list(ndata.get("parent_ids", []))
            graph.children_of.setdefault(nid, [])
        for nid, node in graph.nodes.items():
            for pid in node.parent_ids:
                graph.children_of.setdefault(pid, [])
                if nid not in graph.children_of[pid]:
                    graph.children_of[pid].append(nid)
        graph._roots = data.get("roots", [])
        graph._gen_map = data.get("gen_map", {})
        graph._resurrection_count = data.get("resurrection_count", 0)
        return graph


@dataclass
class EvalResult:
    """Resultado de evaluar un individuo en el sandbox."""

    fitness: FitnessVector = field(default_factory=FitnessVector)
    passed: bool = False
    metrics: Dict[str, float] = field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def score(self) -> float:
        """Backward-compatible scalar score via weighted sum."""
        return self.fitness.to_scalar()


@dataclass
class IslandConfig:
    """Configuración por isla evolutiva."""

    migration_interval: int = 10
    migrants_per_island: int = 2
    topology: str = "ring"
    population_size: int = 8
    top_k: int = 3

    def __post_init__(self) -> None:
        if self.top_k > self.population_size:
            raise ValueError(
                f"top_k ({self.top_k}) must be <= population_size ({self.population_size})"
            )
        if self.population_size < 2:
            raise ValueError("population_size must be >= 2")


@dataclass
class PromptGenome:
    """Genoma de un prompt evolutivo."""

    system_prompt: str
    few_shot_examples: List[Tuple[str, str]]
    mutation_instructions: str
    temperature: float
    fitness: float = 0.0

    def render(self, task: str, base_code: str) -> str:
        """Serializa el genoma en un prompt listo para el LLM."""
        parts: List[str] = [
            self.system_prompt,
            "\nTask: ",
            task,
            "\nBase Code:\n",
            base_code,
        ]
        for inp, out in self.few_shot_examples:
            parts.extend(("\nExample Input:\n", inp, "\nOutput:\n", out))
        if self.mutation_instructions:
            parts.extend(("\nInstructions: ", self.mutation_instructions))
        return "".join(parts)

    @classmethod
    def crossover(
        cls,
        parent_a: "PromptGenome",
        parent_b: "PromptGenome",
    ) -> "PromptGenome":
        """Uniform crossover between two prompt genomes."""
        sys_prompt = (
            parent_a.system_prompt
            if random.random() < 0.5
            else parent_b.system_prompt
        )
        instr = (
            parent_a.mutation_instructions
            if random.random() < 0.5
            else parent_b.mutation_instructions
        )
        temp = (parent_a.temperature + parent_b.temperature) / 2.0
        temp += random.gauss(0, 0.02)
        temp = max(0.1, min(1.0, temp))

        all_fewshot = list(set(parent_a.few_shot_examples + parent_b.few_shot_examples))
        random.shuffle(all_fewshot)
        fewshot = all_fewshot[:max(1, len(all_fewshot) // 2)]

        return cls(
            system_prompt=sys_prompt,
            few_shot_examples=fewshot,
            mutation_instructions=instr,
            temperature=temp,
        )

    def mutate(self) -> "PromptGenome":
        """Apply a random mutation, returning a new mutated copy."""
        mutant = copy.deepcopy(self)
        op = random.randint(0, 5)
        if op == 0:
            words = mutant.system_prompt.split()
            if len(words) >= 2:
                i, j = random.sample(range(len(words)), 2)
                words[i], words[j] = words[j], words[i]
                mutant.system_prompt = " ".join(words)
        elif op == 1:
            suffixes = [
                " Be concise.",
                " Return only valid Python.",
                " Prioritize readability.",
                " Avoid external dependencies.",
            ]
            mutant.system_prompt += random.choice(suffixes)
        elif op == 2:
            mutant.temperature += random.gauss(0, 0.05)
            mutant.temperature = max(0.1, min(1.0, mutant.temperature))
        elif op == 3:
            if mutant.few_shot_examples:
                mutant.few_shot_examples.pop(random.randrange(len(mutant.few_shot_examples)))
        elif op == 4:
            mutant.few_shot_examples.append((
                "def solve(n): return n * (n + 1) // 2",
                "def solve(n):\n    return n * (n + 1) // 2\n",
            ))
        elif op == 5:
            synonyms = {
                "optimize": "enhance", "ensure": "guarantee",
                "avoid": "prevent", "use": "employ",
            }
            words = mutant.mutation_instructions.split()
            for i, w in enumerate(words):
                low = w.lower().rstrip(",.;")
                if low in synonyms:
                    words[i] = synonyms[low] + (
                        w[len(low):] if len(w) > len(low) else ""
                    )
                    break
            mutant.mutation_instructions = " ".join(words)
        return mutant


@dataclass
class ArchivedSolution:
    """Solución almacenada en el archivo a largo plazo."""

    code: str
    metrics: Dict[str, float]
    embedding: np.ndarray
    timestamp: float = field(default_factory=time.time)
