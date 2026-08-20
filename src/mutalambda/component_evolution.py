"""Component Evolution System – v3.5 flagship feature.

Extracts, analyzes, and evolves code components using coupling/cohesion
metrics, AST-based analysis, and genetic operators (crossover, mutation,
split, merge, interface evolution).
"""

from __future__ import annotations

import ast
import copy
import random
import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


# ── Enums ────────────────────────────────────────────────────────────────────

class CouplingLevel(str, enum.Enum):
    """Nivel de acoplamiento entre componentes."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @classmethod
    def from_score(cls, score: float) -> "CouplingLevel":
        """Convierte un score numérico a nivel."""
        if score < 0.3:
            return cls.LOW
        if score < 0.6:
            return cls.MEDIUM
        if score < 0.8:
            return cls.HIGH
        return cls.CRITICAL


# ── Data Classes ──────────────────────────────────────────────────────────────

@dataclass
class InterfaceSpec:
    """Contrato de un componente: firma pública y requisitos."""

    name: str
    input_types: Dict[str, str] = field(default_factory=dict)
    output_type: str = "Any"
    requirements: List[str] = field(default_factory=list)
    complexity_score: float = 0.0

    def crossover(self, other: "InterfaceSpec") -> "InterfaceSpec":
        """Uniform crossover between two interface specs."""
        rng = random.Random()
        new_inputs = {}
        for k, v in self.input_types.items():
            if rng.random() < 0.5:
                new_inputs[k] = v
        for k, v in other.input_types.items():
            if rng.random() < 0.5:
                new_inputs[k] = v
        new_reqs = list(self.requirements)
        for r in other.requirements:
            if rng.random() < 0.5:
                new_reqs.append(r)
        new_complexity = (self.complexity_score + other.complexity_score) / 2.0
        new_complexity += rng.gauss(0, 0.1)
        new_complexity = max(0.0, new_complexity)
        return InterfaceSpec(
            name=self.name,
            input_types=new_inputs,
            output_type=self.output_type if rng.random() < 0.5 else other.output_type,
            requirements=new_reqs,
            complexity_score=new_complexity,
        )

    def mutate(self, rng: random.Random) -> "InterfaceSpec":
        """Mutate the interface: add/remove requirements, change types."""
        mutant = copy.deepcopy(self)
        op = rng.randint(0, 4)

        if op == 0 and mutant.input_types:
            # Change an input type
            key = rng.choice(list(mutant.input_types.keys()))
            mutant.input_types[key] = rng.choice(["int", "float", "str", "list", "dict", "Any"])
        elif op == 1 and mutant.requirements:
            # Remove a requirement
            mutant.requirements.pop(rng.randrange(len(mutant.requirements)))
        elif op == 2:
            # Add a requirement
            mutant.requirements.append(f"req_{rng.randint(0, 999)}")
        elif op == 3:
            # Add a new input parameter
            mutant.input_types[f"param_{rng.randint(0, 999)}"] = rng.choice(
                ["int", "float", "str", "bool", "Any"]
            )
        elif op == 4:
            # Mutate output type
            mutant.output_type = rng.choice(["int", "float", "str", "list", "dict", "bool", "Any"])

        # Mutate complexity
        mutant.complexity_score += rng.gauss(0, 0.2)
        mutant.complexity_score = max(0.0, mutant.complexity_score)

        return mutant

    def __repr__(self) -> str:
        return (
            f"InterfaceSpec(name={self.name!r}, "
            f"input_types={self.input_types!r}, "
            f"output_type={self.output_type!r}, "
            f"requirements={self.requirements!r})"
        )


@dataclass
class Component:
    """Un componente extraíble del código fuente."""

    name: str
    source_code: str
    line_start: int
    line_end: int
    interface: InterfaceSpec
    coupling_score: float = 0.0  # CBO - lower is better
    cohesion_score: float = 0.0  # higher is better
    callers: Set[str] = field(default_factory=set)
    dependents: Set[str] = field(default_factory=set)

    def quality_score(self) -> float:
        """Combined quality metric: cohesion favored over low coupling."""
        return self.cohesion_score * 0.6 - self.coupling_score * 0.4


@dataclass
class ComponentGraph:
    """Grafo de componentes y sus relaciones de dependencia."""

    components: Dict[str, Component] = field(default_factory=dict)
    edges: Dict[str, Set[str]] = field(default_factory=dict)  # source -> {targets}

    def add_component(self, comp: Component) -> None:
        """Agrega un componente al grafo."""
        self.components[comp.name] = comp

    def add_edge(self, source: str, target: str) -> None:
        """Agrega una arista de dependencia source → target."""
        self.edges.setdefault(source, set()).add(target)
        # Also update the component's dependents field
        if source in self.components:
            self.components[source].dependents.add(target)
        if target in self.components:
            self.components[target].callers.add(source)

    def remove_edge(self, source: str, target: str) -> None:
        """Elimina una arista de dependencia."""
        if source in self.edges:
            self.edges[source].discard(target)
            if not self.edges[source]:
                del self.edges[source]
        if source in self.components:
            self.components[source].dependents.discard(target)
        if target in self.components:
            self.components[target].callers.discard(source)

    def remove_component(self, name: str) -> None:
        """Remove a component and all its edges."""
        self.components.pop(name, None)
        # Remove edges pointing to this component
        for src in list(self.edges.keys()):
            self.edges[src].discard(name)
            if not self.edges[src]:
                del self.edges[src]
        # Remove edges from this component
        self.edges.pop(name, None)

    def compute_coupling(self) -> float:
        """Compute overall CBO (Coupling Between Objects)."""
        if not self.components:
            return 0.0
        total = sum(len(deps) for deps in self.edges.values())
        return total / max(1, len(self.components))

    def find_extractable(self, code: str, min_functions: int = 2) -> List[Dict]:
        """Find functions that could be extracted as components."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return []

        results: List[Dict] = []
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            start = getattr(node, "lineno", 0)
            end = getattr(node, "end_lineno", start)
            source = ast.get_source_segment(code, node)
            if source is None:
                continue
            params = self._extract_params(node)
            results.append({
                "name": node.name,
                "source": source,
                "line_start": start,
                "line_end": end,
                "parameters": params,
                "complexity": self._node_complexity(node),
            })

        # Sort by complexity descending, filter by min_functions
        results.sort(key=lambda r: r["complexity"], reverse=True)
        if len(results) >= min_functions:
            return results
        return []

    def _extract_params(self, func_node: ast.FunctionDef) -> Dict[str, str]:
        """Extract parameter names and inferred types from annotations."""
        params: Dict[str, str] = {}
        for arg in func_node.args.args:
            name = arg.arg
            if arg.annotation:
                ann = ast.unparse(arg.annotation)
            else:
                ann = "Any"
            params[name] = ann
        if func_node.returns:
            params["return"] = ast.unparse(func_node.returns)
        return params

    @staticmethod
    def _node_complexity(node: ast.AST) -> float:
        """Estimate cyclomatic complexity of a node."""
        score = 1.0
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.ExceptHandler)):
                score += 1.0
            elif isinstance(child, ast.BoolOp):
                score += len(child.values) - 1
        return score

    def compute_cohesion(self, name: str) -> float:
        """Compute internal cohesion score for a component."""
        comp = self.components.get(name)
        if not comp:
            return 0.0
        # Cohesion based on complexity: more focused (lower complexity) = higher cohesion
        complexity = comp.interface.complexity_score
        return max(0.0, min(1.0, 1.0 - complexity / 10.0))


# ── Module Extractor ──────────────────────────────────────────────────────────

class ModuleExtractor:
    """Extrae funciones/clases de código monolítico en componentes."""

    def __init__(self) -> None:
        self.graph = ComponentGraph()

    def analyze(self, code: str) -> ComponentGraph:
        """Parse code and build component graph with coupling/cohesion metrics."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return self.graph

        self.graph = ComponentGraph()

        # Extract top-level functions and classes
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                comp = self._make_component(code, node)
                self.graph.add_component(comp)
            elif isinstance(node, ast.ClassDef):
                # Treat class as a single component for now
                comp = self._make_class_component(code, node)
                self.graph.add_component(comp)

        # Build dependency edges via call graph analysis
        self._build_call_edges(tree)

        # Compute coupling scores
        for name in self.graph.components:
            self.graph.components[name].coupling_score = self._compute_coupling_for(name)
            self.graph.components[name].cohesion_score = self.graph.compute_cohesion(name)

        return self.graph

    def extract_candidate(self, code: str, rng: random.Random) -> Optional[Dict]:
        """Find best extraction candidate from code."""
        candidates = self.graph.find_extractable(code, min_functions=1)
        if not candidates:
            return None
        # Pick the highest complexity candidate (or random if tied)
        best = max(candidates, key=lambda c: c["complexity"])
        return best

    def apply_extraction(self, code: str, candidate: Dict) -> str:
        """Apply the extraction, returning modified code with component extracted."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return code

        # Find and remove the function from the module body
        new_body = []
        extracted_node = None
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == candidate["name"]:
                extracted_node = node
                continue
            new_body.append(node)
        if extracted_node is None:
            return code

        # Replace calls to the extracted function with a pass or stub
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == candidate["name"]:
                    # We'll just keep the call; the function will be defined elsewhere
                    pass

        # Append extracted function at the end (as a component)
        extracted_code = ast.unparse(extracted_node)
        new_body.append(extracted_node)

        tree.body = new_body
        ast.fix_missing_locations(tree)

        result = ast.unparse(tree)
        try:
            ast.parse(result)
            return result
        except SyntaxError:
            return code

    def compute_metrics(self, graph: ComponentGraph) -> Dict[str, float]:
        """Compute quality metrics for a component graph."""
        if not graph.components:
            return {
                "coupling": 0.0,
                "cohesion": 0.0,
                "avg_quality": 0.0,
                "component_count": 0,
                "edge_count": 0,
            }

        coupling = graph.compute_coupling()
        cohesion_vals = [graph.compute_cohesion(n) for n in graph.components]
        avg_cohesion = sum(cohesion_vals) / len(cohesion_vals)
        quality_vals = [c.quality_score() for c in graph.components.values()]
        avg_quality = sum(quality_vals) / len(quality_vals)
        edge_count = sum(len(deps) for deps in graph.edges.values())

        return {
            "coupling": coupling,
            "cohesion": avg_cohesion,
            "avg_quality": avg_quality,
            "component_count": float(len(graph.components)),
            "edge_count": float(edge_count),
        }

    def _make_component(
        self, code: str, node: ast.FunctionDef
    ) -> Component:
        """Create a Component from a FunctionDef AST node."""
        start = getattr(node, "lineno", 0)
        end = getattr(node, "end_lineno", start)
        source = ast.get_source_segment(code, node) or ""

        # Build interface spec
        input_types: Dict[str, str] = {}
        for arg in node.args.args:
            if arg.annotation:
                input_types[arg.arg] = ast.unparse(arg.annotation)
            else:
                input_types[arg.arg] = "Any"

        output_type = "Any"
        if node.returns:
            output_type = ast.unparse(node.returns)

        complexity = self._complexity_of_node(node)
        interface = InterfaceSpec(
            name=node.name,
            input_types=input_types,
            output_type=output_type,
            complexity_score=complexity,
        )

        return Component(
            name=node.name,
            source_code=source,
            line_start=start,
            line_end=end,
            interface=interface,
        )

    def _make_class_component(
        self, code: str, node: ast.ClassDef
    ) -> Component:
        """Create a Component from a ClassDef AST node."""
        start = getattr(node, "lineno", 0)
        end = getattr(node, "end_lineno", start)
        source = ast.get_source_segment(code, node) or ""

        interface = InterfaceSpec(
            name=node.name,
            output_type=f"{node.name}",
            complexity_score=self._complexity_of_node(node),
        )

        return Component(
            name=node.name,
            source_code=source,
            line_start=start,
            line_end=end,
            interface=interface,
        )

    def _build_call_edges(self, tree: ast.Module) -> None:
        """Build dependency edges by analyzing call sites."""
        # Collect all top-level function/class names
        top_names = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                top_names.add(node.name)

        # Walk the tree and record calls between top-level definitions
        calls_by_func: Dict[str, Set[str]] = {name: set() for name in top_names}
        current_func: Optional[str] = None

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                current_func = node.name
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name) and child.func.id in top_names:
                            if child.func.id != current_func:
                                calls_by_func[current_func].add(child.func.id)
            elif isinstance(node, ast.ClassDef):
                current_func = None
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name) and child.func.id in top_names:
                            calls_by_func[node.name].add(child.func.id)

        for source, targets in calls_by_func.items():
            for target in targets:
                self.graph.add_edge(source, target)

    def _compute_coupling_for(self, name: str) -> float:
        """Compute coupling score for a single component (normalized)."""
        deps = self.graph.edges.get(name, set())
        callers = self.graph.components.get(name, Component(
            name=name, source_code="", line_start=0, line_end=0,
            interface=InterfaceSpec(name=name),
        )).callers
        total = len(deps) + len(callers)
        # Normalize: 0.0 = no coupling, 1.0 = high coupling
        return min(1.0, total / 10.0)

    @staticmethod
    def _complexity_of_node(node: ast.AST) -> float:
        """Estimate complexity of an AST node."""
        score = 1.0
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.ExceptHandler)):
                score += 1.5
            elif isinstance(child, ast.BoolOp):
                score += len(child.values) - 1
            elif isinstance(child, ast.Call):
                score += 0.5
        return score


# ── Component Mutator ────────────────────────────────────────────────────────

class ComponentMutator:
    """Mutates component structures during evolution."""

    def __init__(self, rng: Optional[random.Random] = None) -> None:
        self.rng = rng or random.Random()

    def split_component(self, comp: Component) -> Optional[Component]:
        """Split a large component into two smaller ones."""
        if comp.interface.complexity_score < 3.0:
            return None

        # Create a half-complexity sibling
        new_complexity = comp.interface.complexity_score / 2.0
        new_name = f"{comp.name}__part2"
        new_interface = InterfaceSpec(
            name=new_name,
            input_types=dict(comp.interface.input_types),
            output_type=comp.interface.output_type,
            requirements=list(comp.interface.requirements),
            complexity_score=new_complexity,
        )
        # Reduce input types to simulate a smaller component
        if len(new_interface.input_types) > 1:
            keys = list(new_interface.input_types.keys())
            new_interface.input_types = {keys[0]: new_interface.input_types[keys[0]]}

        return Component(
            name=new_name,
            source_code=comp.source_code,
            line_start=comp.line_start,
            line_end=comp.line_end,
            interface=new_interface,
            coupling_score=comp.coupling_score * 0.7,  # Less coupling when smaller
            cohesion_score=comp.cohesion_score * 0.8,
            callers=set(comp.callers),
            dependents=set(comp.dependents),
        )

    def merge_components(
        self, comp_a: Component, comp_b: Component
    ) -> Optional[Component]:
        """Merge two related components into one."""
        # Check for any dependency relationship (either direction)
        related = (
            comp_b.name in comp_a.dependents
            or comp_a.name in comp_b.dependents
            or comp_b.name in comp_a.callers
            or comp_a.name in comp_b.callers
        )
        if not related:
            return None

        merged_name = f"{comp_a.name}+{comp_b.name}"
        merged_inputs = {**comp_a.interface.input_types, **comp_b.interface.input_types}
        merged_reqs = list(set(comp_a.interface.requirements + comp_b.interface.requirements))
        merged_complexity = (
            comp_a.interface.complexity_score + comp_b.interface.complexity_score
        )
        merged_coupling = max(comp_a.coupling_score, comp_b.coupling_score)

        return Component(
            name=merged_name,
            source_code=f"{comp_a.source_code}\n\n{comp_b.source_code}",
            line_start=min(comp_a.line_start, comp_b.line_start),
            line_end=max(comp_a.line_end, comp_b.line_end),
            interface=InterfaceSpec(
                name=merged_name,
                input_types=merged_inputs,
                output_type=comp_a.interface.output_type,
                requirements=merged_reqs,
                complexity_score=merged_complexity,
            ),
            coupling_score=merged_coupling,
            cohesion_score=min(comp_a.cohesion_score, comp_b.cohesion_score),
            callers=comp_a.callers | comp_b.callers,
            dependents=comp_a.dependents | comp_b.dependents,
        )

    def evolve_interface(self, comp: Component) -> Component:
        """Evolve the interface: add params, change types, etc."""
        new_interface = comp.interface.mutate(self.rng)
        return Component(
            name=comp.name,
            source_code=comp.source_code,
            line_start=comp.line_start,
            line_end=comp.line_end,
            interface=new_interface,
            coupling_score=comp.coupling_score,
            cohesion_score=comp.cohesion_score,
            callers=set(comp.callers),
            dependents=set(comp.dependents),
        )


# ── Utility Functions ─────────────────────────────────────────────────────────

def run_component_evolution(
    code: str,
    rng: Optional[random.Random] = None,
    generations: int = 5,
) -> Dict[str, Any]:
    """High-level entry point for component evolution on a code string."""
    extractor = ModuleExtractor()
    mutator = ComponentMutator(rng)
    graph = extractor.analyze(code)

    results = {
        "initial_graph": graph,
        "initial_metrics": extractor.compute_metrics(graph),
        "evolved_graphs": [],
    }

    current_graph = graph
    for gen in range(generations):
        # Pick a random component to mutate
        if not current_graph.components:
            break
        name = rng.choice(list(current_graph.components.keys()))
        comp = current_graph.components[name]

        op = rng.choice(["split", "merge", "evolve"])
        if op == "split":
            split = mutator.split_component(comp)
            if split:
                current_graph.add_component(split)
        elif op == "merge" and len(current_graph.components) > 1:
            other_name = rng.choice([n for n in current_graph.components if n != name])
            merged = mutator.merge_components(comp, current_graph.components[other_name])
            if merged:
                current_graph.add_component(merged)
                current_graph.remove_component(name)
                current_graph.remove_component(other_name)
        elif op == "evolve":
            evolved = mutator.evolve_interface(comp)
            current_graph.components[name] = evolved

        results["evolved_graphs"].append({
            "generation": gen + 1,
            "metrics": extractor.compute_metrics(current_graph),
        })

    results["final_graph"] = current_graph
    results["final_metrics"] = extractor.compute_metrics(current_graph)
    return results
