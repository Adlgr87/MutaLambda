"""Advanced selection metrics for MutaLambda Evolution Upgrade v2.0."""

from __future__ import annotations

import ast
import math
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class AdvancedSelectionConfig:
    """Configuration for entropy and discovery-aware selection."""

    enabled: bool = False
    fitness_weight: float = 1.0
    novelty_weight: float = 0.15
    entropy_weight: float = 0.20
    discovery_weight: float = 0.35
    history_window: int = 1000


@dataclass
class AdvancedSelectionMetrics:
    """Telemetry emitted by the advanced selector."""

    population_entropy: float = 0.0
    discovery_score_avg: float = 0.0
    entropy_gain_per_gen: float = 0.0
    scored_individuals: int = 0
    last_scores: Dict[str, float] = field(default_factory=dict)


def _safe_parse_node_types(code: str) -> Counter:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return Counter()
    return Counter(type(node).__name__ for node in ast.walk(tree))


def _shannon(values: Iterable[Any]) -> float:
    counts = Counter(values)
    total = sum(counts.values())
    if total <= 1:
        return 0.0
    entropy = 0.0
    for count in counts.values():
        p = count / total
        entropy -= p * math.log2(p)
    return entropy / math.log2(total)


class AdvancedSelectionEngine:
    """Scores candidates by fitness, novelty, entropy and DAG discovery value."""

    def __init__(
        self,
        config: Optional[AdvancedSelectionConfig] = None,
        archive: Optional[Any] = None,
        lineage_graph: Optional[Any] = None,
    ) -> None:
        self.config = config or AdvancedSelectionConfig()
        self.archive = archive
        self.lineage_graph = lineage_graph
        self.metrics = AdvancedSelectionMetrics()
        self._entropy_history: deque[float] = deque(maxlen=self.config.history_window)

    def score_population(self, population: List[Any]) -> List[Any]:
        """Attach advanced selection telemetry and update scalar scores in-place."""
        if not self.config.enabled or not population:
            return population

        entropy = self.population_entropy(population)
        previous_entropy = self._entropy_history[-1] if self._entropy_history else entropy
        self._entropy_history.append(entropy)

        scored: Dict[str, float] = {}
        discovery_values: List[float] = []
        for ind in population:
            discovery = self.discovery_score(getattr(ind, "id", ""))
            novelty = self._novelty(ind)
            base_score = float(getattr(ind, "score", 0.0))
            final = (
                self.config.fitness_weight * base_score
                + self.config.novelty_weight * novelty
                + self.config.entropy_weight * entropy
                + self.config.discovery_weight * discovery
            )
            setattr(ind, "raw_score", base_score)
            setattr(ind, "advanced_score", final)
            setattr(ind, "discovery_score", discovery)
            setattr(ind, "selection_entropy", entropy)
            ind.score = final
            scored[getattr(ind, "id", "")] = final
            discovery_values.append(discovery)

        self.metrics = AdvancedSelectionMetrics(
            population_entropy=entropy,
            discovery_score_avg=sum(discovery_values) / len(discovery_values),
            entropy_gain_per_gen=entropy - previous_entropy,
            scored_individuals=len(population),
            last_scores=scored,
        )
        return population

    def population_entropy(self, population: List[Any]) -> float:
        """Blend structural, semantic-token and lineage entropy."""
        structural_labels: List[str] = []
        semantic_tokens: List[str] = []
        lineage_roots: List[str] = []

        for ind in population:
            code = getattr(ind, "code", "")
            structural_labels.extend(_safe_parse_node_types(code).elements())
            semantic_tokens.extend(code.replace("(", " ").replace(")", " ").split())
            parents = getattr(ind, "parent_ids", None) or []
            lineage_roots.append(parents[0] if parents else getattr(ind, "id", "root"))

        structural = _shannon(structural_labels)
        semantic = _shannon(semantic_tokens)
        lineage = _shannon(lineage_roots)
        return (structural + semantic + lineage) / 3.0

    def discovery_score(self, node_id: str) -> float:
        """Estimate future value by descendant improvement ratio in the lineage DAG."""
        graph = self.lineage_graph
        if not graph or not node_id or node_id not in getattr(graph, "nodes", {}):
            return 0.0

        node = graph.nodes[node_id]
        descendants = self._descendants(node_id)
        if not descendants:
            return 0.0

        improved = 0
        total_gain = 0.0
        base = float(getattr(node, "score", 0.0))
        for did in descendants:
            dnode = graph.nodes.get(did)
            if not dnode:
                continue
            gain = float(getattr(dnode, "score", 0.0)) - base
            if gain > 0:
                improved += 1
                total_gain += gain
        ratio = improved / max(1, len(descendants))
        magnitude = math.tanh(total_gain / max(1.0, abs(base) + 1.0))
        return max(0.0, min(1.0, 0.7 * ratio + 0.3 * magnitude))

    def _descendants(self, node_id: str) -> List[str]:
        graph = self.lineage_graph
        children: Dict[str, List[str]] = {}
        for nid, node in graph.nodes.items():
            for pid in getattr(node, "parent_ids", []):
                children.setdefault(pid, []).append(nid)

        found: List[str] = []
        queue = list(children.get(node_id, []))
        seen = set(queue)
        while queue:
            current = queue.pop(0)
            found.append(current)
            for child in children.get(current, []):
                if child not in seen:
                    seen.add(child)
                    queue.append(child)
        return found

    def _novelty(self, ind: Any) -> float:
        if self.archive is None:
            return 0.0
        try:
            return float(self.archive.novelty_score(getattr(ind, "code", ""), k=10))
        except Exception:
            return 0.0
