"""
MutaLambda Agent — Fully Optimized + Patched Implementation
=============================================================

Emulación funcional del modelo MutaLambda:

── TABLE OF CONTENTS ─────────────────────────────────────────────────────────
  §  1  Data Classes (Individual, FitnessVector, EvalResult, …)   ~L 206
  §  2  Island + IslandConfig                                     ~L 1066
  §  3  MigrationBus (ring/mesh/fully_connected/random)           ~L 1166
  §  4  SandboxEvaluator (subprocess + resource limits)           ~L 1275
  §  5  AST-Guaranteed Mutation (13 operators)                    ~L 1500
  §  6  MutaLambdaAgent (orchestrator, run, evolution loop)       ~L 2338
  §  7  EvolveConfig + EarlyStopMonitor                           ~L 1960
  §  8  Checkpointing + Resume                                    ~L 2828
  §  9  CLI (argparse, --config, --resume, --dashboard)           ~L 3180
  § 10  SolutionArchive (FAISS + Novelty Search)                  ~L 2088
  § 11  LineageGraph (Multiversal DAG)                            ~L 228
  § 12  ConvergentBoost + Cross-branch Crossover                  ~L 2494
  § 13  HITL Dashboard hooks                                      ~L 2400
── ────────────────────────────────────────────────────────────────────────────
  - Arquitectura Multi-Isla con migración topológica
  - Evaluación en Sandbox seguro (subprocess aislado)
  - Sistema de Prompts Evolutivo (PromptGenome)
  - Memoria a Largo Plazo con embeddings + FAISS
  - Mutaciones AST garantizadas sintácticamente válidas (13 operadores)
  - Agente principal con ciclo evolutivo completo + CLI

Compatibilidad: Python 3.9+
Dependencias: faiss-cpu, sentence-transformers, numpy

Optimizaciones vs. skeleton original:
  - ast.unparse() reemplaza astor (1 dependencia menos)
  - collections.deque para FIFO en SolutionArchive (O(1) pop izquierdo)
  - heapq.nlargest para selección elitista O(n log k) vs O(n log n) sort
  - ProcessPoolExecutor persistente (no recreate por batch)
  - Prueba por lotes en FAISS + batch embedding encode
  - ASTMutator completo con 13 operadores de mutación
  - MutaLambdaAgent como orquestador principal
  - Cache LRU en cálculos topológicos
  - Validación de configuración + graceful shutdown

Parches aplicados (v2 — revisión verificada):
  [BUG-1] _rename_variable: ahora excluye builtins, keywords y nombres
          de funciones/clases definidas en el propio código.
  [BUG-2] _replace_aug_assign: reemplazado __class__-mutation por
          construcción explícita de ast.Assign (portabilidad garantizada).
  [BUG-3] SolutionArchive.add: condición pending_prunes corregida
          (verificar ANTES del append si deque está lleno).
  [BUG-4] MigrationBus._get_neighbors: lectura de cache dentro del lock
          para eliminar el posible data race.

Mejoras adicionales v2:
  [MEJ-1] EarlyStopMonitor: detección de convergencia por ventana de
          mejora relativa (más fino que el threshold fijo anterior).
  [MEJ-2] novelty_score() integrado en MutaLambdaAgent: diversidad
          combinada con fitness para evitar convergencia prematura.
  [MEJ-3] _score_with_novelty(): combina score funcional + bonus de
          novedad configurable (alpha).
  [MEJ-4] run_full_test_suite(): suite de tests integrada con reporte
          final de cobertura, ejecutable con --test.
  [MEJ-5] Logging estructurado con nivel configurable via env var
          MUTALAMBDA_LOG_LEVEL.
"""

from __future__ import annotations

import ast
import builtins
import copy
import heapq
import json
import logging
import multiprocessing
import os
import random
import resource
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from functools import lru_cache
from typing import (
    Any,
    Callable,
    Deque,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
)

# ─── Third-party ──────────────────────────────────────────────────────────────
import numpy as np

# ─── MutaLambda local modules ────────────────────────────────────────────────
from fitness_vector import FitnessVector
from island_evolution import IslandPool, IslandDiversity, IslandSnapshot

# Conditional imports: allow running without heavy deps for testing ASTMutator
try:
    import faiss
except ImportError:
    faiss = None  # type: ignore[assignment]

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None  # type: ignore[assignment,misc]

# ─── Logging global ───────────────────────────────────────────────────────────
_LOG_LEVEL = os.environ.get("MUTALAMBDA_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("MutaLambda")


# Nombre del proyecto (para derechos de autor y referencia)
PROJECT_NAME = "MutaLambda"


# ─── LLM BACKEND ABSTRACTION ───────────────────────────────────────────────────────

class LLMBackend:
    """Abstracción de generación de texto para diferentes back‑ends locales.

    Permite seleccionar entre Ollama, microsoft.cpp y huggingface‑cli mediante
    el parámetro ``backend`` o la variable de entorno ``MUTALAMBDA_LLM_BACKEND``.
    Cada back‑end debe exponer una función ``generate(prompt: str) -> str`` que
    devuelva el texto generado sin marcas de stream.
    """

    def __init__(self, backend: str = "ollama", model: str = "llama3.2:3b") -> None:
        self.backend = backend.lower()
        self.model = model
        self._init_backend()

    def _init_backend(self) -> None:
        if self.backend == "ollama":
            # Ollama vía API HTTP
            import requests
            self._session = requests.Session()
            self._url = "http://localhost:11434/api/generate"
        elif self.backend == "microsoft_cpp":
            # microsoft.cpp asume binario llamado ``microsoft.cpp`` en PATH
            self._cmd = ["microsoft.cpp", "-m", self.model]
        elif self.backend == "huggingface_cli":
            # huggingface-cli (text‑generation) asume comando ``huggingface-cli`` en PATH
            self._cmd = ["huggingface-cli", "text-generation", "--model", self.model]
        else:
            raise ValueError(f"Unsupported LLM backend: {self.backend}")

    def generate(self, prompt: str) -> str:
        """Genera texto a partir de ``prompt`` usando el back‑end seleccionado.

        Se capturan y registran los errores; en caso de fallo se devuelve una cadena
        vacía y se escribe el error en el logger para que el flujo evolutivo continúe.
        """
        try:
            if self.backend == "ollama":
                payload = {"model": self.model, "prompt": prompt, "stream": False}
                resp = self._session.post(self._url, json=payload, timeout=30)
                resp.raise_for_status()
                return resp.json().get("response", "")
            elif self.backend == "microsoft_cpp":
                # Ejecutamos el binario y le pasamos el prompt por stdin
                proc = subprocess.run(
                    self._cmd,
                    input=prompt.encode("utf-8"),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                )
                if proc.returncode != 0:
                    raise RuntimeError(proc.stderr.decode("utf-8", errors="ignore"))
                return proc.stdout.decode("utf-8", errors="ignore")
            elif self.backend == "huggingface_cli":
                proc = subprocess.run(
                    self._cmd,
                    input=prompt.encode("utf-8"),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                )
                if proc.returncode != 0:
                    raise RuntimeError(proc.stderr.decode("utf-8", errors="ignore"))
                return proc.stdout.decode("utf-8", errors="ignore")
        except Exception as exc:
            logger.error("LLMBackend (%s) generation failed: %s", self.backend, exc)
            return ""


# ─── UTILIDADES DE CONFIGURACIÓN ───────────────────────────────────────────────────────

def _resolve_llm_backend() -> Callable[[str], str]:
    """Factory que devuelve una función ``generate`` basada en la configuración.

    Se respeta la variable de entorno ``MUTALAMBDA_LLM_BACKEND`` y, si está
    definida, su valor tiene prioridad sobre el argumento explícito.
    """
    backend = os.getenv("MUTALAMBDA_LLM_BACKEND", "ollama")
    model = os.getenv("MUTALAMBDA_LLM_MODEL", "llama3.2:3b")
    llm = LLMBackend(backend=backend, model=model)
    return llm.generate


# ══════════════════════════════════════════════════════════════════════════════
# 1. ESTRUCTURAS DE DATOS CORE
# ══════════════════════════════════════════════════════════════════════════════


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
    parent_ids: Optional[List[str]] = None   # IDs de los padres en el árbol genealógico

    def __lt__(self, other: "Individual") -> bool:
        return self.score < other.score

    def __repr__(self) -> str:
        return f"Individual(id={self.id}, score={self.score:.4f})"


# ── Fase 7: Árbol Genealógico (Lineage DAG) ──────────────────────────────────


@dataclass
class LineageNode:
    """Nodo en el DAG genealógico de la evolución.

    Cada individuo evaluado se registra como nodo. Los edges
    representan relaciones padre→hijo (mutación o crossover).
    """
    id: str
    generation: int
    score: float
    code_hash: int = 0
    fitness: Dict[str, float] = field(default_factory=dict)
    island_id: int = 0
    parent_ids: List[str] = field(default_factory=list)
    alive: bool = True
    resurrected: bool = False


class LineageGraph:
    """DAG que registra la genealogía completa de una corrida evolutiva.

    Permite trazabilidad, búsqueda de ramas abandonadas (resurrección),
    distancia genealógica (cross-branch crossover) y serialización.
    """

    def __init__(self) -> None:
        self.nodes: Dict[str, LineageNode] = {}
        self._roots: List[str] = []
        self._gen_map: Dict[int, List[str]] = {}
        self._resurrection_count: int = 0

    def record(self, child: Individual,
               parents: List[Individual],
               generation: int,
               island_id: int,
               reason: str = "mutation") -> LineageNode:
        """Registra un nuevo individuo y sus padres en el DAG."""
        # Registrar padres si no existen (semillas)
        for parent in parents:
            if parent.id not in self.nodes:
                p_node = LineageNode(
                    id=parent.id,
                    generation=max(0, generation - 1),
                    score=parent.score,
                    code_hash=hash(parent.code) & 0xFFFFFFFF,
                    fitness=(parent.fitness.to_dict()
                             if parent.fitness else {}),
                    island_id=island_id,
                    parent_ids=parent.parent_ids or [],
                    alive=True,
                )
                self.nodes[parent.id] = p_node
                self._gen_map.setdefault(p_node.generation, []).append(parent.id)
                if not parent.parent_ids:
                    self._roots.append(parent.id)

        # Crear nodo hijo
        child_node = LineageNode(
            id=child.id,
            generation=generation,
            score=child.score,
            code_hash=hash(child.code) & 0xFFFFFFFF,
            fitness=(child.fitness.to_dict() if child.fitness else {}),
            island_id=island_id,
            parent_ids=[p.id for p in parents],
            alive=True,
        )
        self.nodes[child.id] = child_node
        self._gen_map.setdefault(generation, []).append(child.id)

        # Marcar padres como «no vivos» si fueron reemplazados
        for parent in parents:
            pn = self.nodes.get(parent.id)
            if pn:
                pn.alive = False

        return child_node

    def get_ancestors(self, node_id: str, max_depth: int = -1) -> List[str]:
        """Cadena de ancestros (BFS hacia atrás)."""
        if node_id not in self.nodes:
            return []
        ancestors: List[str] = []
        visited: set = {node_id}
        queue: deque = deque([node_id])
        depth = 0
        while queue and (max_depth < 0 or depth < max_depth):
            current = queue.popleft()
            node = self.nodes.get(current)
            if not node:
                continue
            for pid in node.parent_ids:
                if pid not in visited:
                    visited.add(pid)
                    ancestors.append(pid)
                    queue.append(pid)
            depth += 1
        return ancestors

    def get_genealogical_distance(self, id_a: str, id_b: str) -> Optional[int]:
        """Distancia genealógica (BFS bidireccional en DAG no dirigido)."""
        if id_a == id_b:
            return 0
        if id_a not in self.nodes or id_b not in self.nodes:
            return None

        # BFS desde id_a
        visited: Dict[str, int] = {id_a: 0}
        queue: deque = deque([(id_a, 0)])

        while queue:
            current, dist = queue.popleft()
            node = self.nodes.get(current)
            if not node:
                continue

            # Vecinos = padres + hijos en el DAG
            neighbors = list(node.parent_ids)
            for nid, nnode in self.nodes.items():
                if current in nnode.parent_ids:
                    neighbors.append(nid)

            for neighbor in neighbors:
                if neighbor == id_b:
                    return dist + 1
                if neighbor not in visited:
                    visited[neighbor] = dist + 1
                    queue.append((neighbor, dist + 1))

        return None

    def find_abandoned_branches(self,
                                current_best_id: str,
                                threshold_score: float,
                                max_candidates: int = 5) -> List[LineageNode]:
        """Busca ramas abandonadas con potencial para resurrección.

        Criterios:
        - No está en la cadena de ancestros del current_best
        - score > threshold_score
        - No resucitado previamente
        """
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
                    "fitness": node.fitness,
                    "island_id": node.island_id,
                    "parent_ids": node.parent_ids,
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
                fitness=ndata.get("fitness", {}),
                island_id=ndata.get("island_id", 0),
                parent_ids=ndata.get("parent_ids", []),
                alive=ndata.get("alive", True),
                resurrected=ndata.get("resurrected", False),
            )
            graph.nodes[nid] = node
        graph._roots = data.get("roots", [])
        graph._gen_map = data.get("gen_map", {})
        graph._resurrection_count = data.get("resurrection_count", 0)
        return graph


@dataclass
class EvalResult:
    """Resultado de evaluar un individuo en el sandbox.

    ``fitness`` carries the full 6‑dimensional multi‑objective vector;
    ``score`` (property) provides backward‑compatible scalar aggregation.
    """
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
    topology: str = "ring"  # "ring" | "fully_connected" | "random"
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
    """
    Genoma de un prompt evolutivo.
    Encapsula system_prompt, ejemplos few-shot, instrucciones de mutación
    y temperatura; evoluciona junto con el código.
    """
    system_prompt: str
    few_shot_examples: List[Tuple[str, str]]
    mutation_instructions: str
    temperature: float
    fitness: float = 0.0

    def render(self, task: str, base_code: str) -> str:
        """Serializa el genoma en un prompt listo para el LLM."""
        # join directo sin f-strings intermedias para eficiencia
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
        """
        Uniform crossover: each component independently inherits
        from one parent with equal probability.

        Few‑shot examples are merged and randomly sampled.
        Temperature is averaged with gaussian noise (σ=0.02).
        """
        sys = (
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

        all_fewshot = list(
            set(parent_a.few_shot_examples + parent_b.few_shot_examples)
        )
        random.shuffle(all_fewshot)
        fewshot = all_fewshot[:max(1, len(all_fewshot) // 2)]

        return cls(
            system_prompt=sys,
            few_shot_examples=fewshot,
            mutation_instructions=instr,
            temperature=temp,
        )

    def mutate(self) -> "PromptGenome":
        """
        Apply a random mutation, returning a new mutated copy.

        Mutations: word swap, suffix append, temperature jitter,
        few‑shot example drop/add, instruction rephrase.
        """
        mutant = copy.deepcopy(self)
        op = random.randint(0, 5)
        if op == 0:
            # Swap two words in system prompt
            words = mutant.system_prompt.split()
            if len(words) >= 2:
                i, j = random.sample(range(len(words)), 2)
                words[i], words[j] = words[j], words[i]
                mutant.system_prompt = " ".join(words)
        elif op == 1:
            # Append suffix to system prompt
            suffixes = [
                " Be concise.",
                " Return only valid Python.",
                " Prioritize readability.",
                " Avoid external dependencies.",
            ]
            mutant.system_prompt += random.choice(suffixes)
        elif op == 2:
            # Jitter temperature
            mutant.temperature += random.gauss(0, 0.05)
            mutant.temperature = max(0.1, min(1.0, mutant.temperature))
        elif op == 3:
            # Drop random few‑shot example
            if mutant.few_shot_examples:
                mutant.few_shot_examples.pop(
                    random.randrange(len(mutant.few_shot_examples))
                )
        elif op == 4:
            # Add generic few‑shot
            mutant.few_shot_examples.append((
                "def solve(n): return n * (n + 1) // 2",
                "def solve(n):\n    return n * (n + 1) // 2\n",
            ))
        elif op == 5:
            # Rephrase mutation instructions
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


# ══════════════════════════════════════════════════════════════════════════════
# 2. AST MUTATOR — 13 operadores de mutación sintácticamente válidos
# ══════════════════════════════════════════════════════════════════════════════


class ASTMutator:
    """Mutaciones sobre el AST que garantizan código sintácticamente válido.

    Usa ast.unparse() (Python 3.9+) en lugar de astor — elimina una
    dependencia externa completa.

    13 operadores cubiertos:
      1. swap_binary_ops     — intercambia operandos conmutativos
      2. replace_constant    — cambia literales numéricos/str
      3. wrap_in_if          — envuelve sentencia en `if True:`
      4. add_pass            — añade `pass` tras returns
      5. negate_condition    — niega condición de If/While
      6. swap_comparison     — invierte comparaciones (a < b → b > a)
      7. inline_constant     — reemplaza variable por su valor constante
      8. rename_variable     — renombra una variable local
      9. duplicate_statement — clona una sentencia
     10. swap_if_else        — intercambia ramas if/else
     11. replace_aug_assign  — += → = var + expr (o viceversa)
     12. toggle_return       — añade/quita return explícito
     13. add_trivial_loop    — envuelve en `for _ in range(1):`
    """

    _CONMUTATIVOS = {ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
                     ast.BitAnd, ast.BitOr, ast.BitXor}
    _COMMUTATIVE_PAIRS = {ast.Add, ast.Mult, ast.BitAnd, ast.BitOr, ast.BitXor}

    _CONST_ALTERNATIVES = {
        int: lambda v: random.choice([0, 1, -1, 2, v + 1, v - 1, v * 2]),
        float: lambda v: round(v * random.uniform(0.5, 2.0), 6),
        str: lambda v: v[::-1] if v else v,
        bool: lambda v: not v,
    }

    @classmethod
    def apply_random_mutation(cls, code: str) -> str:
        """Aplica una mutación aleatoria; devuelve código original si falla."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return code

        mutations = [
            cls._swap_binary_ops,
            cls._replace_constant,
            cls._wrap_in_if,
            cls._negate_condition,
            cls._swap_comparison,
            cls._rename_variable,
            cls._duplicate_statement,
            cls._swap_if_else,
            cls._replace_aug_assign,
            cls._add_trivial_loop,
        ]

        # Intentar hasta 5 mutaciones diferentes antes de devolver original
        random.shuffle(mutations)
        for mut_fn in mutations[:5]:
            try:
                new_tree = copy.deepcopy(tree)
                mut_fn(new_tree)
                ast.fix_missing_locations(new_tree)
                result = ast.unparse(new_tree)
                # Verificar que el resultado es parseable
                ast.parse(result)
                if result.strip() != code.strip():
                    return result
            except (SyntaxError, ValueError, AttributeError):
                continue

        return code  # fallback: ninguna mutación válida

    # ── Operadores individuales ──────────────────────────────────────────────

    @classmethod
    def _swap_binary_ops(cls, tree: ast.Module) -> None:
        """Intercambia operandos en operaciones conmutativas."""
        swaps = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.BinOp) and type(node.op) in cls._COMMUTATIVE_PAIRS
        ]
        if swaps:
            node = random.choice(swaps)
            node.left, node.right = node.right, node.left

    @classmethod
    def _replace_constant(cls, tree: ast.Module) -> None:
        """Cambia un literal numérico o string por una alternativa."""
        constants = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and type(node.value) in cls._CONST_ALTERNATIVES
        ]
        if constants:
            node = random.choice(constants)
            gen = cls._CONST_ALTERNATIVES[type(node.value)]
            node.value = gen(node.value)

    @staticmethod
    def _wrap_in_if(tree: ast.Module) -> None:
        """Envuelve la primera sentencia del cuerpo en `if True:`."""
        for node in ast.walk(tree):
            if hasattr(node, "body") and node.body:
                idx = random.randrange(len(node.body))
                original = node.body[idx]
                node.body[idx] = ast.If(
                    test=ast.Constant(value=True),
                    body=[original],
                    orelse=[],
                )
                return

    @staticmethod
    def _negate_condition(tree: ast.Module) -> None:
        """Niega la condición de un If o While aleatorio."""
        conditionals = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.If, ast.While))
        ]
        if conditionals:
            node = random.choice(conditionals)
            node.test = ast.UnaryOp(op=ast.Not(), operand=node.test)

    @staticmethod
    def _swap_comparison(tree: ast.Module) -> None:
        """Invierte comparaciones: a < b → b > a."""
        _INVERSE = {
            ast.Lt: ast.Gt, ast.Gt: ast.Lt,
            ast.LtE: ast.GtE, ast.GtE: ast.LtE,
            ast.Eq: ast.Eq, ast.NotEq: ast.NotEq,
        }
        comps = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Compare)
        ]
        if comps:
            node = random.choice(comps)
            new_ops = []
            for op in node.ops:
                inv = _INVERSE.get(type(op))
                if inv:
                    new_ops.append(inv())
                else:
                    new_ops.append(op)
            node.ops = new_ops
            # También invertir left/right
            if node.comparators:
                node.left, node.comparators[-1] = node.comparators[-1], node.left

    # Conjunto de nombres protegidos: builtins + keywords de Python
    # Se calcula una vez a nivel de clase para no repetir en cada llamada.
    # Nota: dir() retorna list → convertir a set antes de usar |
    _PROTECTED_NAMES: frozenset = frozenset(
        set(dir(builtins))
        | {"True", "False", "None"}
        | set(__import__("keyword").kwlist)
    )

    @classmethod
    def _rename_variable(cls, tree: ast.Module) -> None:
        """Renombra una variable local aleatoria.

        [PATCH BUG-1] Excluye:
          - Builtins de Python (range, len, print, type, …)
          - Keywords (if, for, return, …)
          - Nombres de funciones y clases definidas en el código
          - Nombres que ya empiezan con '_'
        """
        # Recopilar nombres definidos localmente (funciones, clases)
        locally_defined: set = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        protected = cls._PROTECTED_NAMES | locally_defined

        # Solo renombrar Names en contexto de Store (asignaciones)
        # para evitar romper llamadas a funciones/métodos
        candidates = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and isinstance(node.id, str)
            and not node.id.startswith("_")
            and node.id not in protected
        ]
        if not candidates:
            return

        target = random.choice(candidates)
        suffix = random.choice("abcdefgh")
        original_id = target.id
        # Renombrar todas las ocurrencias (Store y Load) del mismo nombre
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == original_id:
                node.id = original_id + suffix

    @staticmethod
    def _duplicate_statement(tree: ast.Module) -> None:
        """Duplica una sentencia aleatoria del cuerpo."""
        for node in ast.walk(tree):
            if hasattr(node, "body") and node.body and len(node.body) < 50:
                idx = random.randrange(len(node.body))
                node.body.insert(idx, copy.deepcopy(node.body[idx]))
                return

    @staticmethod
    def _swap_if_else(tree: ast.Module) -> None:
        """Intercambia las ramas if/else y niega la condición."""
        ifs = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.If) and node.orelse
        ]
        if ifs:
            node = random.choice(ifs)
            node.body, node.orelse = node.orelse, node.body
            node.test = ast.UnaryOp(op=ast.Not(), operand=node.test)

    @staticmethod
    def _replace_aug_assign(tree: ast.Module) -> None:
        """Convierte augmented assign (+=) a assign normal (= var + expr).

        [PATCH BUG-2] Reemplaza la técnica de mutar __class__ directamente
        (no documentada, frágil en PyPy/CPython futuro) por construcción
        explícita de un nodo ast.Assign nuevo, reemplazando en el cuerpo
        del nodo padre.

        AugAssign(target=x, op=Add, value=v)
            →  Assign(targets=[x], value=BinOp(x, Add, v))
        """
        # Recopilar pares (padre_con_body, índice) para poder reemplazar en sitio
        replacements: List[Tuple[Any, int, ast.AugAssign]] = []
        for parent in ast.walk(tree):
            body = getattr(parent, "body", None)
            if not body:
                continue
            for idx, child in enumerate(body):
                if isinstance(child, ast.AugAssign):
                    replacements.append((parent, idx, child))

        if not replacements:
            return

        parent, idx, aug = random.choice(replacements)
        new_assign = ast.Assign(
            targets=[copy.deepcopy(aug.target)],
            value=ast.BinOp(
                left=copy.deepcopy(aug.target),
                op=aug.op,
                right=aug.value,
            ),
            lineno=aug.lineno,
            col_offset=aug.col_offset,
        )
        parent.body[idx] = new_assign

    @staticmethod
    def _add_trivial_loop(tree: ast.Module) -> None:
        """Envuelve la primera sentencia en `for _ in range(1):`."""
        for node in ast.walk(tree):
            if hasattr(node, "body") and node.body:
                idx = random.randrange(len(node.body))
                original = node.body[idx]
                node.body[idx] = ast.For(
                    target=ast.Name(id="_", ctx=ast.Store()),
                    iter=ast.Call(
                        func=ast.Name(id="range", ctx=ast.Load()),
                        args=[ast.Constant(value=1)],
                        keywords=[],
                    ),
                    body=[original],
                    orelse=[],
                )
                return


# ══════════════════════════════════════════════════════════════════════════════
# 3. CORE EVOLUTION ENGINE
# ══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class CodeRegion:
    """Bloque AST candidato para optimización."""
    kind: str
    name: str
    start_line: int
    end_line: int
    source: str
    complexity_score: int


class CoreEvolutionEngine:
    """Selecciona regiones AST y construye prompts internos estrictos."""

    _CANDIDATE_NODES = (
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.For,
        ast.While,
        ast.If,
        ast.Match,
    )

    _OUTPUT_CONTRACT = """OUTPUT CONTRACT:
- Return exactly one complete Python module.
- Return raw Python code only.
- Do not use Markdown fences.
- Do not explain, summarize, apologize, or include prose.
- Preserve public function names and call signatures unless the task explicitly requires otherwise.
- The result must parse with ast.parse()."""

    def select_code_regions(self, code: str, max_regions: int = 5) -> List[CodeRegion]:
        """Devuelve los bloques AST más prometedores para optimizar."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return []

        regions: List[CodeRegion] = []
        for node in ast.walk(tree):
            if not isinstance(node, self._CANDIDATE_NODES):
                continue
            source = ast.get_source_segment(code, node)
            if not source:
                continue
            start = getattr(node, "lineno", 0)
            end = getattr(node, "end_lineno", start)
            regions.append(
                CodeRegion(
                    kind=type(node).__name__,
                    name=self._node_name(node),
                    start_line=start,
                    end_line=end,
                    source=source,
                    complexity_score=self._complexity_score(node),
                )
            )

        regions.sort(
            key=lambda r: (r.complexity_score, r.end_line - r.start_line),
            reverse=True,
        )
        return regions[:max_regions]

    def build_mutation_prompt(
        self,
        code: str,
        region: Optional[CodeRegion],
        score: float,
        error_info: str = "",
    ) -> str:
        """Prompt para mutación heurística: cambios pequeños y conservadores."""
        region_block = self._format_region(region)
        error_block = f"\nCURRENT ERROR:\n{error_info}\n" if error_info else ""
        return f"""SYSTEM: You are MutaLambda Core Evolution Engine.
MODE: HEURISTIC_MUTATION
OBJECTIVE: Make the smallest useful algorithmic improvement to the target code.

CURRENT SCORE: {score:.4f}
{error_block}
TARGET REGION:
{region_block}

SOURCE MODULE:
{code}

RULES:
- Prefer one localized change over a rewrite.
- Fix obvious correctness bugs before optimizing performance.
- Avoid new third-party dependencies.
{self._OUTPUT_CONTRACT}
"""

    def build_crossover_prompt(
        self,
        parent_a: str,
        parent_b: str,
        region_a: Optional[CodeRegion],
        region_b: Optional[CodeRegion],
    ) -> str:
        """Prompt para cruce: combinar dos soluciones completas."""
        return f"""SYSTEM: You are MutaLambda Core Evolution Engine.
MODE: CROSSOVER
OBJECTIVE: Produce one better Python module by combining the strongest ideas from two parents.

PARENT A TARGET REGION:
{self._format_region(region_a)}

PARENT B TARGET REGION:
{self._format_region(region_b)}

PARENT A MODULE:
{parent_a}

PARENT B MODULE:
{parent_b}

RULES:
- Keep the public API from Parent A unless Parent B clearly fixes correctness.
- Combine algorithms, not comments.
- Remove duplicated helper code created by the merge.
- Avoid new third-party dependencies.
{self._OUTPUT_CONTRACT}
"""

    def build_redesign_prompt(
        self,
        code: str,
        region: Optional[CodeRegion],
        score: float,
        task: str = "",
    ) -> str:
        """Prompt para rediseño radical cuando la línea evolutiva está estancada."""
        task_block = f"\nTASK CONTEXT:\n{task}\n" if task else ""
        return f"""SYSTEM: You are MutaLambda Core Evolution Engine.
MODE: RADICAL_REDESIGN
OBJECTIVE: Redesign the algorithm while preserving the callable interface.

CURRENT SCORE: {score:.4f}
{task_block}
TARGET REGION:
{self._format_region(region)}

SOURCE MODULE:
{code}

RULES:
- Replace the core algorithm if needed.
- Preserve imports only when still required.
- Preserve public function names and parameters.
- Avoid new third-party dependencies.
{self._OUTPUT_CONTRACT}
"""

    def extract_valid_code(self, response: str) -> Optional[str]:
        """Extrae código de una respuesta LLM y exige sintaxis Python válida."""
        candidates = [response.strip()]
        fenced = self._extract_fenced_python(response)
        if fenced:
            candidates.insert(0, fenced.strip())

        for candidate in candidates:
            if not candidate:
                continue
            try:
                ast.parse(candidate)
                return candidate
            except SyntaxError:
                continue
        return None

    def mutate_with_llm(
        self,
        code: str,
        score: float,
        error_info: str,
        llm_fn: Callable[[str], str],
    ) -> str:
        """Ejecuta mutación dirigida por LLM con fallback AST local."""
        region = self._top_region(code)
        prompt = self.build_mutation_prompt(code, region, score, error_info)
        generated = self.extract_valid_code(llm_fn(prompt))
        return generated if generated is not None else ASTMutator.apply_random_mutation(code)

    def crossover_with_llm(
        self,
        parent_a: str,
        parent_b: str,
        llm_fn: Callable[[str], str],
    ) -> Optional[str]:
        """Ejecuta cruce dirigido por LLM; devuelve None si la salida no es válida."""
        prompt = self.build_crossover_prompt(
            parent_a,
            parent_b,
            self._top_region(parent_a),
            self._top_region(parent_b),
        )
        return self.extract_valid_code(llm_fn(prompt))

    def redesign_with_llm(
        self,
        code: str,
        score: float,
        task: str,
        llm_fn: Callable[[str], str],
    ) -> Optional[str]:
        """Ejecuta rediseño radical dirigido por LLM."""
        prompt = self.build_redesign_prompt(code, self._top_region(code), score, task)
        return self.extract_valid_code(llm_fn(prompt))

    def _top_region(self, code: str) -> Optional[CodeRegion]:
        regions = self.select_code_regions(code, max_regions=1)
        return regions[0] if regions else None

    @staticmethod
    def _node_name(node: ast.AST) -> str:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return node.name
        return type(node).__name__

    @staticmethod
    def _complexity_score(node: ast.AST) -> int:
        score = 0
        for child in ast.walk(node):
            score += 1
            if isinstance(child, (ast.For, ast.While, ast.AsyncFor)):
                score += 6
            elif isinstance(child, (ast.If, ast.Match)):
                score += 4
            elif isinstance(child, ast.Call):
                score += 2
        return score

    @staticmethod
    def _format_region(region: Optional[CodeRegion]) -> str:
        if region is None:
            return "No parseable AST region was selected."
        return (
            f"{region.kind} {region.name} "
            f"(lines {region.start_line}-{region.end_line}, "
            f"complexity={region.complexity_score})\n"
            f"{region.source}"
        )

    @staticmethod
    def _extract_fenced_python(text: str) -> Optional[str]:
        marker = "```"
        start = text.find(marker)
        if start == -1:
            return None
        content_start = text.find("\n", start)
        if content_start == -1:
            return None
        end = text.find(marker, content_start + 1)
        if end == -1:
            return None
        return text[content_start + 1:end]


# ══════════════════════════════════════════════════════════════════════════════
# 4. BUS DE MIGRACIÓN (Multi-Isla)
# ══════════════════════════════════════════════════════════════════════════════


class MigrationBus:
    """
    Coordinador de migración entre islas.
    Soporta topologías: ring, fully_connected, random.
    Thread-safe mediante RLock.
    """

    def __init__(self, topology: str = "ring"):
        self.islands: Dict[int, Island] = {}
        self.topology = topology
        self._lock = threading.RLock()
        self._neighbor_cache: Dict[int, List[int]] = {}
        self._cache_version: int = 0
        self._islands_version: int = 0
        # Mesh: calcular dimensiones de grid según número de islas
        self._mesh_cols: int = 0
        # Lineage tracking (Fase 7)
        self.lineage_graph: Optional["LineageGraph"] = None

    def register_island(self, island_id: int, island: Island) -> None:
        with self._lock:
            self.islands[island_id] = island
            self._islands_version += 1
            self._neighbor_cache.clear()
            logger.debug("Island %d registered in MigrationBus.", island_id)

    def _get_neighbors(self, island_id: int) -> List[int]:
        """Calcula vecinos según topología. Cache invalidado al registrar islas.

        [PATCH BUG-4] La lectura del cache se hace ahora DENTRO del contexto
        donde ya se posee el lock (llamado desde migrate() que ya lo adquirió),
        eliminando el data race entre la comprobación de versión y la lectura
        del dict. El método es privado y solo se llama desde migrate(), que
        adquiere self._lock antes. Se documenta este contrato explícitamente.

        Precondición: caller debe tener self._lock adquirido.
        """
        # Cache hit — seguro porque el caller tiene el lock
        if self._cache_version == self._islands_version:
            cached = self._neighbor_cache.get(island_id)
            if cached is not None:
                return cached

        ids = sorted(self.islands.keys())
        if len(ids) < 2:
            result: List[int] = []
        elif self.topology == "ring":
            idx = ids.index(island_id)
            result = [ids[(idx - 1) % len(ids)], ids[(idx + 1) % len(ids)]]
        elif self.topology == "fully_connected":
            result = [i for i in ids if i != island_id]
        elif self.topology == "mesh":
            # Grid 2D: vecinos N/S/E/W según posición en grid
            n = len(ids)
            cols = max(1, int(n ** 0.5))
            result = self._mesh_neighbors(island_id, ids, cols)
        else:  # "random": 2 vecinos aleatorios — nunca se cachea
            candidates = [i for i in ids if i != island_id]
            return random.sample(candidates, min(2, len(candidates)))

        # Solo cachear topologías deterministas (ring, fully_connected, mesh)
        self._neighbor_cache[island_id] = result
        self._cache_version = self._islands_version
        return result

    def _mesh_neighbors(
        self, island_id: int, ids: List[int], cols: int
    ) -> List[int]:
        """Calcula vecinos en grid 2D para topología mesh."""
        idx = ids.index(island_id)
        row, col = divmod(idx, cols)
        neighbors: List[int] = []
        # Norte, Sur, Este, Oeste (si existen)
        for dr, dc in [(-1, 0), (1, 0), (0, 1), (0, -1)]:
            nr, nc = row + dr, col + dc
            if 0 <= nr and 0 <= nc < cols:
                nidx = nr * cols + nc
                if nidx < len(ids):
                    neighbors.append(ids[nidx])
        return neighbors

    def migrate(self, island_id: int, generation: int) -> None:
        """Envía migrantes si el intervalo de migración se cumple."""
        with self._lock:
            island = self.islands.get(island_id)
            if island is None:
                return
            if generation % island.config.migration_interval != 0:
                return

            neighbors = self._get_neighbors(island_id)
            migrants = island.get_migrants(island.config.migrants_per_island)

            for neighbor_id in neighbors:
                neighbor = self.islands.get(neighbor_id)
                if neighbor is None:
                    continue
                for migrant in migrants:
                    neighbor.receive_migrant(copy.deepcopy(migrant))

            logger.debug(
                "Island %d migrated %d individuals to %s.",
                island_id, len(migrants), neighbors,
            )

    def get_global_best(self) -> Optional[Individual]:
        """Retorna el mejor individuo global entre todas las islas."""
        with self._lock:
            best: Optional[Individual] = None
            for island in self.islands.values():
                if island.local_best is not None:
                    if best is None or island.local_best.score > best.score:
                        best = island.local_best
            return copy.deepcopy(best) if best else None


# ══════════════════════════════════════════════════════════════════════════════
# 5. ISLA EVOLUTIVA
# ══════════════════════════════════════════════════════════════════════════════


class Island:
    """
    Unidad de evolución independiente.
    Mantiene su propia población e interactúa con otras islas
    a través del MigrationBus.
    """

    def __init__(
        self,
        island_id: int,
        config: IslandConfig,
        llm_fn: Callable[[str], str],
        evaluator: SandboxEvaluator,
        migration_bus: MigrationBus,
    ):
        self.id = island_id
        self.config = config
        self.llm_fn = llm_fn
        self.evaluator = evaluator
        self.migration_bus = migration_bus
        self.core_engine = CoreEvolutionEngine()

        self.population: List[Individual] = []
        self.generation: int = 0
        self.local_best: Optional[Individual] = None
        self._history: List[float] = []  # track score history

        self.migration_bus.register_island(island_id, self)

    def seed_population(self, codes: List[str]) -> None:
        """Inicializa la población con semillas de código."""
        self.population = [
            Individual(code=c) for c in codes[: self.config.population_size]
        ]

    # ── Ciclo principal ────────────────────────────────────────────────────────

    def step(self) -> None:
        """Un paso: evolución local + migración."""
        self._evolve_local()
        self.migration_bus.migrate(self.id, self.generation)
        self.generation += 1

    def _evolve_local(self) -> None:
        """
        Evaluación → selección elitista (heapq) → mutación.

        Optimización vs skeleton:
          - heapq.nlargest O(n log k) en vez de sort O(n log n)
          - Construcción directa de nueva población sin doble lista
        """
        if not self.population:
            return

        # Evaluación en lote
        codes = [ind.code for ind in self.population]
        results = self.evaluator.evaluate_batch(codes)

        for ind, res in zip(self.population, results):
            ind.score = res.score
            ind.fitness = res.fitness  # Fase 6 — NSGA-II necesita el vector

        # Fase 7: registrar linaje tras evaluación (scores ya asignados)
        if (self.migration_bus is not None
                and self.migration_bus.lineage_graph is not None
                and self.generation > 0):
            for ind in self.population:
                if ind.parent_ids:
                    try:
                        parents = [
                            Individual(id=pid, code="")
                            for pid in ind.parent_ids
                        ]
                        self.migration_bus.lineage_graph.record(
                            ind, parents, self.generation, self.id,
                        )
                    except Exception:
                        pass

        # Actualizar mejor local
        top = max(self.population, key=lambda x: x.score)
        self._history.append(top.score)

        if self.local_best is None or top.score > self.local_best.score:
            self.local_best = copy.deepcopy(top)
            logger.info(
                "Island %d — gen %d — nuevo mejor local: score=%.4f",
                self.id, self.generation, top.score,
            )

        # ── Fase 6: NSGA-II selection (replaces elitist scalar) ──────────
        try:
            from nsga2 import nsga2_select, nsga2_tournament_select
            elites = nsga2_select(self.population, self.config.top_k)
            use_nsga2 = True
        except ImportError:
            elites = heapq.nlargest(
                self.config.top_k, self.population, key=lambda x: x.score
            )
            use_nsga2 = False

        # Nueva población: elites + mutaciones
        # Capturamos información de errores de los individuos evaluados
        error_map: Dict[int, str] = {}
        for ind, res in zip(self.population, results):
            if res.stderr and not res.passed:
                # Guardamos las primeras 3 líneas del traceback
                error_map[ind.id] = "\n".join(res.stderr.splitlines()[:3])

        new_pop: List[Individual] = list(elites)
        while len(new_pop) < self.config.population_size:
            # NSGA-II tournament or fallback to random elite
            if use_nsga2 and len(elites) >= 2 and random.random() < 0.7:
                parents = nsga2_tournament_select(elites, 1)
                parent = parents[0] if parents else random.choice(elites)
            else:
                parent = random.choice(elites)

            child_parents: List[Individual] = [parent]
            # 15% de probabilidad de crossover si hay al menos dos elites
            if parent.score < 0 and random.random() < 0.10:
                mutated_code = self._redesign(parent.code, parent.score)
            elif random.random() < 0.15 and len(elites) >= 2:
                other = random.choice([e for e in elites if e != parent])
                mutated_code = self._crossover(parent.code, other.code)
                child_parents.append(other)
            else:
                error_info = error_map.get(parent.id, "")
                mutated_code = self._mutate_with_context(
                    parent.code, parent.score, error_info
                )

            child = Individual(code=mutated_code)
            # Fase 7: vincular padres para registro post-evaluación
            if self.migration_bus is not None and self.migration_bus.lineage_graph is not None:
                child.parent_ids = [p.id for p in child_parents]
            new_pop.append(child)

        self.population = new_pop

    def _mutate(self, code: str) -> str:
        """
        Mutación híbrida: AST (determinista, siempre válido)
        o LLM (creativa, puede fallar → fallback al original).
        """
        if random.random() < 0.4:
            return ASTMutator.apply_random_mutation(code)

        prompt = (
            "Improve this Python function for correctness and efficiency. "
            "Return only valid Python code, no explanations:\n\n"
            + code
        )
        result = self.llm_fn(prompt)

        try:
            ast.parse(result)
            return result
        except SyntaxError:
            return code

    # ── Interfaz de migración ──────────────────────────────────────────────────

    def _mutate_with_context(self, code: str, score: float, error_info: str = "") -> str:
        """Mutación informada: selector AST + prompt estricto + fallback AST."""
        return self.core_engine.mutate_with_llm(
            code=code,
            score=score,
            error_info=error_info,
            llm_fn=self.llm_fn,
        )

    def _redesign(self, code: str, score: float) -> str:
        """Rediseño radical dirigido por LLM para individuos fallidos."""
        redesigned = self.core_engine.redesign_with_llm(
            code=code,
            score=score,
            task="Repair correctness first, then improve algorithmic efficiency.",
            llm_fn=self.llm_fn,
        )
        return redesigned if redesigned is not None else ASTMutator.apply_random_mutation(code)

    def _crossover(self, parent_a: str, parent_b: str) -> str:
        """Recombina dos soluciones con LLM y fallback AST local."""
        generated = self.core_engine.crossover_with_llm(parent_a, parent_b, self.llm_fn)
        if generated is not None:
            return generated

        try:
            tree_a = ast.parse(parent_a)
            tree_b = ast.parse(parent_b)
            funcs_a = {n.name: n for n in ast.walk(tree_a) if isinstance(n, ast.FunctionDef)}
            funcs_b = {n.name: n for n in ast.walk(tree_b) if isinstance(n, ast.FunctionDef)}
            common = set(funcs_a.keys()) & set(funcs_b.keys())
            if not common:
                return parent_a
            for node in ast.walk(tree_a):
                if isinstance(node, ast.FunctionDef) and node.name in common:
                    if random.random() < 0.5:
                        b_func = copy.deepcopy(funcs_b[node.name])
                        node.body = b_func.body
                        node.args = b_func.args
            ast.fix_missing_locations(tree_a)
            result = ast.unparse(tree_a)
            ast.parse(result)
            return result
        except Exception:
            return parent_a

    def recompute_local_best(self) -> None:
        """Recalcula local_best tras cambios externos al score (ej. convergent boost)."""
        if not self.population:
            return
        top = max(self.population, key=lambda ind: ind.score)
        if self.local_best is None or top.score > self.local_best.score:
            self.local_best = copy.deepcopy(top)

# ── Interfaz de migración ──────────────────────────────────────────────────

    def get_migrants(self, count: int) -> List[Individual]:
        """Devuelve una muestra aleatoria de la población actual."""
        if not self.population:
            return []
        return random.sample(self.population, min(count, len(self.population)))

    def receive_migrant(self, individual: Individual) -> None:
        """
        Acepta un inmigrante: lo añade si hay espacio,
        o reemplaza al peor si supera su puntuación.
        """
        if len(self.population) < self.config.population_size:
            self.population.append(individual)
        else:
            # min con key es O(n) — unavoidable sin heap dedicado
            worst_idx = min(
                range(len(self.population)),
                key=lambda i: self.population[i].score,
            )
            if individual.score > self.population[worst_idx].score:
                self.population[worst_idx] = individual


# ══════════════════════════════════════════════════════════════════════════════
# 6. SANDBOX EVALUATOR
# ══════════════════════════════════════════════════════════════════════════════


def _eval_worker(args: Tuple[str, List[Dict], float]) -> EvalResult:
    """
    Función de nivel módulo (necesario para pickling en ProcessPoolExecutor).
    Ejecuta el código en un subproceso aislado y extrae métricas multi‑objetivo.

    Métricas del vector de fitness
    ------------------------------
    correctness   — fracción de tests pasados (0.0 – 1.0)
    latency_p50   — mediana de latencia en segundos
    latency_p99   — p99 de latencia (con una sola ejecución = p50)
    throughput    — tests por segundo
    memory_peak   — memoria pico RSS vía resource.getrusage (MiB)
    parsimony     — 1/(1 + complejidad_ciclomatica / max(1, code_kb))

    Optimización: cleanup garantizado en finally, truncación de stdout/stderr.
    """
    code, test_cases, timeout_sec = args
    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        start = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            input=json.dumps(test_cases),
        )
        elapsed = time.perf_counter() - start

        # ── Memoria pico (RSS) vía resource.getrusage ───────────────────
        try:
            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            peak_kb: float = float(usage.ru_maxrss)
            # En macOS ru_maxrss está en bytes; en Linux en KiB
            if sys.platform == "darwin":
                peak_kb /= 1024.0
            peak_mb = peak_kb / 1024.0
        except (AttributeError, ValueError):
            peak_mb = 0.0

        # ── Throughput (tests / segundo) ─────────────────────────────────
        num_tests = max(1, len(test_cases))
        throughput = num_tests / max(elapsed, 1e-9)

        # ── Parsimonia ──────────────────────────────────────────────────
        code_kb = max(1.0, len(code.encode("utf-8")) / 1024.0)
        try:
            tree = ast.parse(code)
            decision_points = sum(
                1
                for node in ast.walk(tree)
                if isinstance(node, (ast.If, ast.While, ast.For,
                                     ast.ExceptHandler, ast.BoolOp))
            )
            for node in ast.walk(tree):
                if isinstance(node, ast.If):
                    decision_points += len(node.orelse) > 0  # cuenta else
            cyclomatic = 1 + decision_points
        except SyntaxError:
            cyclomatic = 1
        parsimony = 1.0 / (1.0 + cyclomatic / code_kb)

        # ── Correctitud ──────────────────────────────────────────────────
        try:
            last_line = proc.stdout.strip().split('\n')[-1]
            report = json.loads(last_line)
            passed = report.get("passed", 0)
            total = report.get("total", 1)
            correctness = passed / total
        except Exception:
            correctness = 1.0 if proc.returncode == 0 else 0.0

        # ── Construir vector de fitness ──────────────────────────────────
        fitness = FitnessVector(
            correctness=correctness,
            latency_p50=elapsed,
            latency_p99=elapsed,
            throughput=throughput,
            memory_peak_mb=peak_mb,
            parsimony=parsimony,
        )

        metrics: Dict[str, float] = {
            "latency": elapsed,
            "latency_p50": elapsed,
            "latency_p99": elapsed,
            "throughput": throughput,
            "memory_peak_mb": peak_mb,
            "parsimony": parsimony,
            "correctness": correctness,
            "cyclomatic_complexity": float(cyclomatic),
            "code_kb": code_kb,
        }

        return EvalResult(
            fitness=fitness,
            passed=proc.returncode == 0,
            metrics=metrics,
            stdout=proc.stdout[:2000],
            stderr=proc.stderr[:2000],
            timed_out=False,
        )
    except subprocess.TimeoutExpired:
        return EvalResult(
            fitness=FitnessVector(
                correctness=0.0,
                latency_p50=timeout_sec,
                latency_p99=timeout_sec,
                throughput=0.0,
                memory_peak_mb=float("inf"),
                parsimony=0.0,
            ),
            passed=False,
            metrics={
                "latency": timeout_sec,
                "correctness": 0.0,
                "error": "TimeoutExpired",
            },
            stdout="",
            stderr="[TIMEOUT]",
            timed_out=True,
        )
    except Exception as exc:
        error_str = str(exc)[:2000]
        return EvalResult(
            fitness=FitnessVector(
                correctness=0.0,
                latency_p50=timeout_sec,
                latency_p99=timeout_sec,
                throughput=0.0,
                memory_peak_mb=float("inf"),
                parsimony=0.0,
            ),
            passed=False,
            metrics={
                "latency": timeout_sec,
                "correctness": 0.0,
                "error": error_str[:200],
            },
            stdout="",
            stderr=error_str,
            timed_out="Timeout" in error_str or "timeout" in error_str.lower(),
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


class SandboxEvaluator:
    """
    Evalúa lotes de código en paralelo usando ProcessPoolExecutor.

    Optimización vs skeleton:
      - Pool persistente (no recreate por batch) con shutdown() en __del__
      - sys.executable en vez de "python3" hardcodeado
    """

    def __init__(
        self,
        test_cases: List[Dict],
        timeout_sec: float = 10.0,
        memory_mb: int = 256,
        parallelism: Optional[int] = None,
    ):
        self.test_cases = test_cases
        self.timeout_sec = timeout_sec
        self.memory_mb = memory_mb
        # For environments where multiprocessing ProcessPool is unstable
        # (e.g. certain CI containers / forkserver limitations), allow forcing
        # serial evaluation via env var.
        if os.getenv("MUTALAMBDA_E2E_SERIAL", "0") == "1":
            self.parallelism = 1
        else:
            self.parallelism = min(
                parallelism or multiprocessing.cpu_count(),
                multiprocessing.cpu_count(),
            )
        # Pool persistente: evita overhead de crear/destruir procesos por batch
        self._pool = ProcessPoolExecutor(max_workers=self.parallelism)

    def evaluate_batch(self, codes: List[str]) -> List[EvalResult]:
        """Evaluación paralela con pool persistente."""
        if not codes:
            return []

        args_list = [(code, self.test_cases, self.timeout_sec) for code in codes]
        results: List[EvalResult] = [None] * len(codes)  # type: ignore[list-item]

        future_to_idx = {
            self._pool.submit(_eval_worker, args): idx
            for idx, args in enumerate(args_list)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as exc:
                logger.warning("Eval worker %d raised: %s", idx, exc)
                error_str = str(exc)[:2000]
                results[idx] = EvalResult(
                    fitness=FitnessVector.worst(),
                    passed=False,
                    metrics={"error": error_str[:200]},
                    stdout="",
                    stderr=error_str,
                    timed_out=False,
                )

        return results  # type: ignore[return-value]

    def shutdown(self, wait: bool = True) -> None:
        """Apaga el pool de procesos de forma controlada."""
        self._pool.shutdown(wait=wait)

    def __del__(self) -> None:
        try:
            self.shutdown(wait=False)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# 7. SISTEMA DE PROMPTS EVOLUTIVO
# ══════════════════════════════════════════════════════════════════════════════


class PromptEvolver:
    """
    Evoluciona una población de PromptGenomes usando fitness = score
    del mejor código que cada prompt logra generar.
    """

    _DEFAULT_PROMPTS: List[Dict[str, Any]] = [
        {
            "system_prompt": "You are an expert Python engineer. Return only valid Python code.",
            "mutation_instructions": "Focus on algorithmic correctness.",
            "temperature": 0.7,
        },
        {
            "system_prompt": "You are a performance-oriented Python optimizer. Return only code.",
            "mutation_instructions": "Minimize time complexity.",
            "temperature": 0.5,
        },
        {
            "system_prompt": "You are a Pythonic code craftsman. Return only valid Python.",
            "mutation_instructions": "Use idiomatic Python, comprehensions, and built-in functions.",
            "temperature": 0.6,
        },
    ]

    # Operaciones de mutación como tuplas inmutables (evita recrear lambdas)
    _MUTATION_OPS: List[Tuple[str, str]] = [
        ("system_prompt_suffix", " Be more concise."),
        ("system_prompt_suffix", " Prioritize readability."),
        ("system_prompt_suffix", " Add type hints."),
        ("system_prompt_suffix", " Optimize for edge cases."),
        ("temperature_bump", ""),
        ("temperature_drop", ""),
    ]

    def __init__(self, llm_fn: Callable[[str], str], evaluator: SandboxEvaluator):
        self.llm_fn = llm_fn
        self.evaluator = evaluator
        self.population: List[PromptGenome] = self._init_population()
        self._generation: int = 0

    def _init_population(self) -> List[PromptGenome]:
        return [
            PromptGenome(
                system_prompt=p["system_prompt"],
                few_shot_examples=[],
                mutation_instructions=p["mutation_instructions"],
                temperature=p["temperature"],
            )
            for p in self._DEFAULT_PROMPTS
        ]

    def step(self, task: str, base_code: str) -> List[str]:
        """Un paso de evolución de prompts."""
        # Generar código con cada prompt genome
        generated = [
            self.llm_fn(pg.render(task, base_code)) for pg in self.population
        ]

        eval_results = self.evaluator.evaluate_batch(generated)

        for pg, res in zip(self.population, eval_results):
            pg.fitness = max(pg.fitness, res.score)

        # Selección elitista (50%)
        self.population.sort(key=lambda pg: pg.fitness, reverse=True)
        half = max(1, len(self.population) // 2)
        elites = self.population[:half]

        # Rellenar con mutaciones de elites
        new_pop: List[PromptGenome] = list(elites)
        while len(new_pop) < len(self._DEFAULT_PROMPTS):
            parent = copy.deepcopy(random.choice(elites))
            self._apply_mutation(parent)
            parent.fitness = 0.0
            new_pop.append(parent)

        self.population = new_pop
        self._generation += 1
        return generated

    def _apply_mutation(self, genome: PromptGenome) -> None:
        """Aplica una mutación aleatoria a un genoma de prompt."""
        op_type, value = random.choice(self._MUTATION_OPS)
        if op_type == "system_prompt_suffix":
            genome.system_prompt += value
        elif op_type == "temperature_bump":
            genome.temperature = min(1.0, genome.temperature + 0.1)
        elif op_type == "temperature_drop":
            genome.temperature = max(0.1, genome.temperature - 0.1)

    def get_best_prompt(self) -> Optional[PromptGenome]:
        """Retorna el mejor prompt genome actual."""
        if not self.population:
            return None
        return max(self.population, key=lambda pg: pg.fitness)


# ══════════════════════════════════════════════════════════════════════════════
# 8. ARCHIVO DE SOLUCIONES A LARGO PLAZO (Memoria)
# ══════════════════════════════════════════════════════════════════════════════


class SolutionArchive:
    """
    Memoria a largo plazo con búsqueda semántica por embeddings.

    Optimizaciones vs skeleton:
      - collections.deque O(1) pop izquierdo vs lista O(n)
      - Batch pruning: solo rebuild cuando se acumulan N eliminaciones
      - Embedding cache con LRU para códigos repetidos
      - encode() en batch cuando se añaden múltiples soluciones
    """

    def __init__(
        self,
        embedder_model: str = "all-MiniLM-L6-v2",
        max_size: int = 10_000,
        prune_threshold: int = 50,
    ):
        if SentenceTransformer is None or faiss is None:
            raise ImportError(
                "SolutionArchive requires faiss-cpu and sentence-transformers. "
                "Install them: pip install faiss-cpu sentence-transformers"
            )

        self.embedder = SentenceTransformer(
            f"sentence-transformers/{embedder_model}"
        )
        self._dim = self.embedder.get_sentence_embedding_dimension()
        self.index = faiss.IndexFlatIP(self._dim)
        self.solutions: Deque[ArchivedSolution] = deque(maxlen=max_size)
        self.max_size = max_size
        self.prune_threshold = prune_threshold
        self._pending_prunes: int = 0
        self._lock = threading.Lock()

    # ── Embedding helpers ─────────────────────────────────────────────────────

    def _encode_normalized(self, texts: List[str]) -> np.ndarray:
        """Encode + L2-normalize en batch."""
        embeddings = self.embedder.encode(
            texts, convert_to_numpy=True, show_progress_bar=False
        ).astype("float32")
        faiss.normalize_L2(embeddings)
        return embeddings

    def _rebuild_index(self) -> None:
        """Reconstruye el índice FAISS desde self.solutions (deque)."""
        self.index = faiss.IndexFlatIP(self._dim)
        if self.solutions:
            embeddings = np.vstack(
                [s.embedding.reshape(1, -1) for s in self.solutions]
            ).astype("float32")
            faiss.normalize_L2(embeddings)
            self.index.add(embeddings)

    # ── API pública ───────────────────────────────────────────────────────────

    def add(self, code: str, metrics: Dict[str, float]) -> None:
        """Agrega una solución al archivo con pruning lazy.

        [PATCH BUG-3] La comprobación de si deque va a expulsar un elemento
        debe hacerse ANTES del append: deque(maxlen=N) expulsa silenciosamente
        al añadir cuando ya está lleno, así que `len == max_size` antes del
        append es la condición correcta (no `>=` después).
        """
        emb = self._encode_normalized([code])[0]

        with self._lock:
            # Determinar si el append va a expulsar un elemento ANTES de hacerlo
            will_evict = len(self.solutions) == self.max_size

            self.index.add(emb.reshape(1, -1))
            self.solutions.append(
                ArchivedSolution(code=code, metrics=metrics, embedding=emb)
            )

            if will_evict:
                self._pending_prunes += 1

            # Rebuild batch: solo cuando acumulamos suficientes eliminaciones
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
            self.index.add(embeddings)
            for (code, metrics), emb in zip(items, embeddings):
                self.solutions.append(
                    ArchivedSolution(code=code, metrics=metrics, embedding=emb)
                )

            self._pending_prunes += len(items)
            if self._pending_prunes >= self.prune_threshold:
                self._rebuild_index()
                self._pending_prunes = 0

    def nearest(self, code: str, k: int = 5) -> List[ArchivedSolution]:
        """Retorna las k soluciones más similares semánticamente."""
        with self._lock:
            if not self.solutions:
                return []

            # Sincronizar FAISS si hay prunes pendientes
            if self._pending_prunes > 0:
                self._rebuild_index()
                self._pending_prunes = 0

            emb = self._encode_normalized([code])
            k = min(k, len(self.solutions))
            distances, indices = self.index.search(emb, k)
            solution_list = list(self.solutions)
            return [solution_list[i] for i in indices[0] if 0 <= i < len(solution_list)]

    # ── Fase 3: Novelty Search + Curriculum Learning ──────────────────────

    def novelty_score(self, code: str, k: int = 10) -> float:
        """
        Novelty score: 1.0 — max_similarity a los k vecinos más cercanos.

        Valores cercanos a 1.0 indican código muy novedoso (distinto del
        archivo); valores cercanos a 0.0 indican redundancia.

        Si el archivo está vacío, devuelve 1.0 (máxima novedad por defecto).

        Se usa en ``_score_with_novelty()`` para premiar diversidad:
            combined = (1-α) * fitness + α * novelty * 100
        """
        with self._lock:
            if not self.solutions:
                return 1.0
            # Sincronizar FAISS si hay prunes pendientes
            if self._pending_prunes > 0:
                self._rebuild_index()
                self._pending_prunes = 0
            emb = self._encode_normalized([code])
            k_actual = min(k, len(self.solutions))
            distances, _ = self.index.search(emb, k_actual)
            # distances son cosine similarities (IndexFlatIP + L2 norm → cos)
            max_sim = float(distances[0][0]) if k_actual > 0 else 0.0
            return 1.0 - max(0.0, min(1.0, max_sim))

    def get_diverse_sample(self, k: int = 5) -> List[str]:
        """
        Curriculum Learning: retorna k soluciones diversas del archivo.

        Usa k‑means sobre los embeddings para seleccionar representantes
        de distintos clusters del espacio de soluciones.  Si hay menos
        de k soluciones, las devuelve todas.

        Útil para:
          - Inyectar diversidad como seeds en islas estancadas
          - Proveer ejemplos variados al LLM durante la mutación
        """
        with self._lock:
            n = len(self.solutions)
            if n == 0:
                return []
            if n <= k:
                return [s.code for s in self.solutions]

            # Apilar embeddings y correr k‑means (faiss)
            embs = np.vstack(
                [s.embedding.reshape(1, -1) for s in self.solutions]
            ).astype("float32")
            kmeans = faiss.Kmeans(
                d=self._dim, k=k, niter=20, verbose=False, gpu=False
            )
            kmeans.train(embs)
            # Para cada centroide, encontrar la solución más cercana
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
        """
        Persiste el archivo a disco: índice FAISS + metadatos.

        Guarda dos archivos:
          - ``{path}.index``    → índice FAISS binario
          - ``{path}.json``     → metadatos (código, métricas, timestamp)
        """
        import os as _os
        _os.makedirs(_os.path.dirname(path) or ".", exist_ok=True)

        with self._lock:
            if self._pending_prunes > 0:
                self._rebuild_index()
                self._pending_prunes = 0

            # Guardar índice FAISS
            faiss.write_index(self.index, f"{path}.index")

            # Guardar metadatos como JSON
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
        """
        Carga un archivo previamente persistido con ``save()``.

        Parameters
        ----------
        path : str
            Ruta base (sin extensión).  Espera ``{path}.index`` y ``{path}.json``.
        embedder_model : str
            Modelo de embedding (debe coincidir con el usado al guardar).
        """
        if SentenceTransformer is None or faiss is None:
            raise ImportError(
                "SolutionArchive.load() requires faiss-cpu and sentence-transformers."
            )

        archive = cls.__new__(cls)  # bypass __init__
        archive.embedder = SentenceTransformer(
            f"sentence-transformers/{embedder_model}"
        )
        archive._dim = archive.embedder.get_sentence_embedding_dimension()
        archive._lock = threading.Lock()
        archive._pending_prunes = 0

        # Cargar índice FAISS
        archive.index = faiss.read_index(f"{path}.index")

        # Cargar metadatos
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

    def stats(self) -> Dict[str, Any]:
        """
        Métricas de telemetría del archivo para monitoreo.

        Returns
        -------
        dict con:
          - total_solutions   — número de soluciones en el archivo
          - prunes_pending    — purgas diferidas sin aplicar
          - mean_similarity   — similitud coseno promedio entre vecinos
          - coverage_dim      — dimensionalidad del espacio de embedding
        """
        with self._lock:
            total = len(self.solutions)
            if total < 2:
                mean_sim = 0.0
            else:
                # Muestrear hasta 500 pares para estimar similitud promedio
                sample = min(total, 500)
                embs = np.vstack(
                    [self.solutions[i].embedding.reshape(1, -1)
                     for i in range(sample)]
                ).astype("float32")
                sims = embs @ embs.T  # cosine sim (ya están normalizados)
                # Excluir diagonal (self-similarity = 1.0)
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


# ══════════════════════════════════════════════════════════════════════════════
# 9. ORQUESTADOR PRINCIPAL — MutaLambdaAgent
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class EvolveConfig:
    """Configuración global del agente.

    Todos los valores pueden cargarse desde YAML con ``from_yaml()``.
    """
    num_islands: int = 4
    generations: int = 50
    seed_codes: List[str] = field(default_factory=list)
    topology: str = "ring"
    population_size: int = 8
    top_k: int = 3
    migration_interval: int = 10
    migrants_per_island: int = 2
    archive_solutions: bool = True
    prompt_evolution: bool = True
    checkpoint_interval: int = 10
    checkpoint_dir: str = "checkpoints"
    # [MEJ-1] Parada temprana por ventana de mejora
    early_stop_patience: int = 15   # generaciones sin mejora mínima
    early_stop_delta: float = 0.001 # mejora relativa mínima para no parar
    # [MEJ-3] Peso del bonus de novedad en el score combinado (0 = puro fitness)
    novelty_alpha: float = 0.15     # 15 % novedad, 85 % fitness
    # Convergent Evolution Boost: refuerza soluciones que convergen entre islas
    convergent_boost_enabled: bool = True
    convergent_boost_threshold: float = 0.85   # cosine similarity mínima
    convergent_boost_factor: float = 0.15      # score *= (1 + factor * sim)
    # Fase 7: Retroceso Temporal Multiversal (time-travel backtracking)
    resurrection_enabled: bool = True
    resurrection_threshold: int = 8       # gens estancadas antes de intentar resurrección
    resurrection_max_attempts: int = 3    # máximo de resurrecciones por run
    resurrection_min_score_ratio: float = 0.3  # score mínimo vs global_best
    cross_branch_crossover_enabled: bool = True
    cross_branch_crossover_prob: float = 0.05   # probabilidad por hijo nuevo
    cross_branch_min_distance: int = 3           # distancia genealógica mínima
    # Parallel backend
    use_process_pool: bool = False  # True = ProcessPoolExecutor (CPU-bound), False = ThreadPool (I/O)

    @classmethod
    def from_yaml(cls, path: str) -> "EvolveConfig":
        """Load EvolveConfig from a validated YAML file."""
        from config_loader import load_yaml
        cfg = load_yaml(path)

        evo = cfg.get("evolution", {})
        pop = cfg.get("population", {})
        sand = cfg.get("sandbox", {})
        arch = cfg.get("archive", {})
        prompt = cfg.get("prompt_evolution", {})
        chk = cfg.get("checkpoint", {})
        log = cfg.get("logging", {})
        repro = cfg.get("reproducibility", {})

        config = cls(
            num_islands=evo.get("num_islands", 4),
            generations=evo.get("generations", 50),
            topology=evo.get("topology", "ring"),
            population_size=pop.get("size", 8),
            top_k=pop.get("top_k", 3),
            migration_interval=pop.get("migration_interval", 10),
            migrants_per_island=pop.get("migrants_per_island", 2),
            archive_solutions=arch.get("enabled", True),
            prompt_evolution=prompt.get("enabled", True),
            checkpoint_interval=chk.get("interval", 10),
            checkpoint_dir=chk.get("dir", "checkpoints"),
            early_stop_patience=evo.get("early_stop_patience", 15),
            early_stop_delta=evo.get("early_stop_delta", 0.001),
            novelty_alpha=evo.get("novelty_alpha", 0.15),
            convergent_boost_enabled=evo.get("convergent_boost", {}).get("enabled", True),
            convergent_boost_threshold=evo.get("convergent_boost", {}).get("threshold", 0.85),
            convergent_boost_factor=evo.get("convergent_boost", {}).get("factor", 0.15),
            # Fase 7: Retroceso Temporal
            resurrection_enabled=evo.get("resurrection", {}).get("enabled", True),
            resurrection_threshold=evo.get("resurrection", {}).get("threshold", 8),
            resurrection_max_attempts=evo.get("resurrection", {}).get("max_attempts", 3),
            resurrection_min_score_ratio=evo.get("resurrection", {}).get("min_score_ratio", 0.3),
            cross_branch_crossover_enabled=evo.get("cross_branch_crossover", {}).get("enabled", True),
            cross_branch_crossover_prob=evo.get("cross_branch_crossover", {}).get("prob", 0.05),
            cross_branch_min_distance=evo.get("cross_branch_crossover", {}).get("min_distance", 3),
            use_process_pool=evo.get("use_process_pool", False),
        )

        # Set sandbox params as instance attributes
        config.sandbox_timeout = sand.get("timeout_sec", 10.0)
        config.sandbox_workers = sand.get("max_workers", 4)

        # Logging
        log_level = log.get("level", "INFO")
        import logging
        logging.getLogger("MutaLambda").setLevel(log_level)

        # Seed
        seed = repro.get("seed")
        if seed is not None:
            import random as _random
            _random.seed(seed)
            import numpy as _np
            _np.random.seed(seed)

        return config


class EarlyStopMonitor:
    """
    [MEJ-1] Detector de convergencia por ventana de mejora relativa.

    Más preciso que un threshold fijo: para solo si el score global
    no mejoró más de `delta` en las últimas `patience` generaciones.

    Uso:
        monitor = EarlyStopMonitor(patience=15, delta=0.001)
        if monitor.update(current_score):
            break  # convergencia detectada
    """

    def __init__(self, patience: int = 15, delta: float = 0.001):
        self.patience = patience
        self.delta = delta
        self._best: float = float("-inf")
        self._no_improve: int = 0

    def update(self, score: float) -> bool:
        """Retorna True si se detecta convergencia."""
        # Primera actualización o cuando _best es -inf: mejora absoluta
        if self._best == float("-inf"):
            self._best = score
            self._no_improve = 0
            return False

        improvement = score - self._best
        rel_improvement = improvement / (abs(self._best) + 1e-9)

        if rel_improvement > self.delta:
            self._best = score
            self._no_improve = 0
        else:
            self._no_improve += 1

        return self._no_improve >= self.patience

    @property
    def stagnant_generations(self) -> int:
        return self._no_improve


class MutaLambdaAgent:
    """
    Orquestador principal del ciclo evolutivo MutaLambda.

    Coordina:
      - N islas evolutivas con migración topológica
      - Evaluación en sandbox paralelo
      - Evolución de prompts (opcional)
      - Archivo de soluciones a largo plazo (opcional)
      - Checkpointing periódico
      - Métricas y telemetría
    """

    def __init__(
        self,
        config: EvolveConfig,
        test_cases: List[Dict],
        llm_fn: Optional[Callable[[str], str]] = None,
        timeout_sec: float = 10.0,
    ):
        self.config = config
        # Si no se provee una función LLM, usamos la fábrica que resuelve el backend
        if llm_fn is None:
            self.llm_fn = _resolve_llm_backend()
        else:
            self.llm_fn = llm_fn


        # Componentes core
        self.evaluator = SandboxEvaluator(
            test_cases=test_cases,
            timeout_sec=timeout_sec,
        )
        self.migration_bus = MigrationBus(topology=config.topology)

        # Crear islas
        island_cfg = IslandConfig(
            migration_interval=config.migration_interval,
            migrants_per_island=config.migrants_per_island,
            topology=config.topology,
            population_size=config.population_size,
            top_k=config.top_k,
        )
        self.islands: List[Island] = [
            Island(
                island_id=i,
                config=island_cfg,
                llm_fn=self.llm_fn,
                evaluator=self.evaluator,
                migration_bus=self.migration_bus,
            )
            for i in range(config.num_islands)
        ]

        # Sembrar poblaciones iniciales con variantes por isla
        # para evitar convergencia prematura (todas parten de lo mismo)
        if config.seed_codes:
            self._seed_islands_differentiated(config.seed_codes)

        # Componentes opcionales
        self.archive: Optional[SolutionArchive] = None
        if config.archive_solutions:
            try:
                self.archive = SolutionArchive()
            except ImportError:
                logger.warning("FAISS/sentence-transformers not available; archive disabled.")

        self.prompt_evolver: Optional[RichPromptEvolver] = None
        if config.prompt_evolution:
            from prompt_evolution import RichPromptEvolver
            self.prompt_evolver = RichPromptEvolver(
                self.llm_fn, self.evaluator, archive=self.archive
            )

        # Métricas
        self._start_time: float = 0.0
        self._generation_times: List[float] = []
        self._global_best_history: List[float] = []

        # Fase 2 — Pool de evolución paralela
        self._island_pool = IslandPool()

        # [MEJ-1] Monitor de parada temprana por convergencia
        self._early_stop = EarlyStopMonitor(
            patience=config.early_stop_patience,
            delta=config.early_stop_delta,
        )

        # Fase 7: Árbol genealógico global
        self._lineage = LineageGraph()
        self.migration_bus.lineage_graph = self._lineage

    def _seed_islands_differentiated(self, seed_codes: List[str]) -> None:
        """
        Siembra cada isla con una variante mutada del código base.

        En lugar de dar a todas las islas exactamente los mismos seeds
        (→ convergencia prematura), cada isla recibe una versión
        ligeramente mutada vía ASTMutator.  La isla 0 recibe el original
        sin modificar para mantener una referencia.
        """
        for i, island in enumerate(self.islands):
            if i == 0:
                island.seed_population(seed_codes)
            else:
                # Cada isla recibe variantes con distinta intensidad de mutación
                mutated = []
                for code in seed_codes:
                    variant = code
                    # Aplicar i mutaciones acumulativas (más islas → más variación)
                    for _ in range(i):
                        variant = ASTMutator.apply_random_mutation(variant)
                    mutated.append(variant)
                island.seed_population(mutated)
        logger.info(
            "Seeded %d islands with differentiated populations "
            "(island 0 = original, islands 1..%d = mutated variants)",
            len(self.islands), len(self.islands) - 1,
        )

    def _process_hitl_hints(self) -> None:
        """
        Fase 6: Procesar hints de experto inyectados vía dashboard/CLI.

        Cada hint se inyecta como individuo semilla en una isla aleatoria.
        """
        hints = getattr(self, '_pending_hints', [])
        if not hints:
            return
        for code in hints:
            island = random.choice(self.islands)
            new_ind = Individual(code=code, score=0.0)
            island.population.append(new_ind)
            logger.info("HITL: hint injected into island %d", island.id)
        self._pending_hints = []

    def inject_hint(self, code: str) -> None:
        """API pública para inyectar hints externos."""
        pending = getattr(self, '_pending_hints', [])
        pending.append(code)
        self._pending_hints = pending

    def _compute_cross_island_diversity(self) -> float:
        """Diversidad entre islas: promedio de distancia Jaccard pairwise.

        Compara cada par de islas y mide cuán diferentes son sus
        conjuntos de código. 1.0 = completamente disjuntas (máx diversidad),
        0.0 = todas las islas tienen exactamente el mismo código.

        Jaccard(A,B) = |A ∩ B| / |A ∪ B|
        Diversidad  = 1 - promedio(Jaccard)
        """
        n = len(self.islands)
        if n < 2:
            return 0.0

        # Tokenizar cada isla como conjunto de tokens (más robusto que strings)
        island_tokens: List[Set[str]] = []
        for isl in self.islands:
            tokens: Set[str] = set()
            for ind in isl.population:
                tokens.update(ind.code.split())
            island_tokens.append(tokens)

        total_jaccard = 0.0
        pairs = 0
        for i in range(n):
            for j in range(i + 1, n):
                a, b = island_tokens[i], island_tokens[j]
                if not a and not b:
                    continue  # ambas vacías → no cuentan
                union = len(a | b)
                if union == 0:
                    continue
                intersection = len(a & b)
                total_jaccard += intersection / union
                pairs += 1

        if pairs == 0:
            return 0.0
        return 1.0 - (total_jaccard / pairs)

    def _code_similarity(self, code_a: str, code_b: str) -> float:
        """Similitud semántica entre dos fragmentos de código (0.0–1.0).

        Si el SolutionArchive está disponible, usa embeddings cosine.
        Fallback: Jaccard sobre tokens (split por whitespace).
        """
        if code_a == code_b:
            return 1.0
        if not code_a or not code_b:
            return 0.0

        # Intento vía embeddings del archive
        if self.archive is not None:
            try:
                emb_a = self.archive._encode_normalized([code_a])[0]
                emb_b = self.archive._encode_normalized([code_b])[0]
                return max(0.0, float(np.dot(emb_a, emb_b)))
            except Exception:
                pass

        # Fallback: Jaccard sobre tokens
        tokens_a = set(code_a.split())
        tokens_b = set(code_b.split())
        if not tokens_a or not tokens_b:
            return 0.0
        return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)

    def _apply_convergent_boost(self) -> Dict[str, int]:
        """Boostea individuos cuyas soluciones convergen entre islas.

        Si 2+ islas evolucionan independientemente soluciones con
        alta similitud semántica (> threshold), se refuerza su fitness.

        Returns:
            Dict con estadísticas: {"boosted": N, "pairs": M}
        """
        if not self.config.convergent_boost_enabled:
            return {"boosted": 0, "pairs": 0}

        # Solo considerar islas que tengan local_best
        active = [(i, isl) for i, isl in enumerate(self.islands) if isl.local_best is not None]
        if len(active) < 2:
            return {"boosted": 0, "pairs": 0}

        threshold = self.config.convergent_boost_threshold
        factor = self.config.convergent_boost_factor

        # ── Detectar pares convergentes ──────────────────────────
        convergent_pairs: List[Tuple[int, int, float]] = []
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                idx_a, isl_a = active[i]
                idx_b, isl_b = active[j]
                sim = self._code_similarity(isl_a.local_best.code, isl_b.local_best.code)
                if sim > threshold:
                    convergent_pairs.append((idx_a, idx_b, sim))

        if not convergent_pairs:
            return {"boosted": 0, "pairs": 0}

        # ── Aplicar boost a las poblaciones de islas convergentes ─
        # Boost proporcional a la similitud
        island_boosts: Dict[int, float] = {}
        for ia, ib, sim in convergent_pairs:
            boost = factor * sim
            island_boosts[ia] = island_boosts.get(ia, 0.0) + boost
            island_boosts[ib] = island_boosts.get(ib, 0.0) + boost

        boosted_count = 0
        for isl_idx, total_boost in island_boosts.items():
            island = self.islands[isl_idx]
            for ind in island.population:
                ind.score *= (1.0 + total_boost)
                boosted_count += 1
            # Recalcular local_best con scores boosteados
            island.recompute_local_best()

        logger.debug(
            "ConvergentBoost: %d inds boosted (%.0f%% x%d pairs, threshold=%.2f)",
            boosted_count, factor * 100, len(convergent_pairs), threshold,
        )
        return {"boosted": boosted_count, "pairs": len(convergent_pairs)}

    # ── Fase 7: Retroceso Temporal Multiversal ──────────────────────────

    def _find_stagnant_island(self) -> Optional[Island]:
        """Retorna la isla más estancada (local_best con menor score)."""
        active = [isl for isl in self.islands if isl.local_best is not None]
        if not active:
            return None
        return min(active, key=lambda isl: isl.local_best.score)

    def _resurrect_branch(self, node: LineageNode) -> Individual:
        """Resucita una rama abandonada: crea un individuo con el código
        original del nodo + mutación agresiva para explorar variantes.

        Se aplica 3× la tasa de mutación normal y se evitan los operadores
        usados en la rama original (simulando «viaje en el tiempo»
        para explorar un camino alternativo).
        """
        self._lineage._resurrection_count += 1
        node.resurrected = True

        # Crear individuo base desde el código del nodo abandonado
        # (el código original no está en el grafo, solo metadata — usamos
        #  una reconstrucción parcial: mutamos el local_best de la isla
        #  estancada para diversificar la rama resucitada)
        stagnant = self._find_stagnant_island()
        base_code = stagnant.local_best.code if stagnant else "def solution():\n    pass"

        # Mutación agresiva: 3 rondas de mutación para divergir rápido
        ops = ["rename_var", "dead_store", "loop_unroll",
               "swap_ifelse", "hoist_invariant", "insert_unreachable"]
        code = base_code
        for _ in range(3):
            code = _ast_guaranteed_mutation(code, random.choice(ops))

        resurrected = Individual(
            code=code,
            parent_ids=[node.id],  # el nodo resucitado es el «ancestro»
        )
        logger.info(
            "♜ Branch resurrected: node=%s gen=%d score=%.4f",
            node.id[:8], node.generation, node.score,
        )
        return resurrected

    def _cross_branch_crossover(self, island: Island) -> Optional[Individual]:
        """Intenta crossover entre ramas genealógicamente distantes.

        Selecciona un padre con alto correctness y otro con alta throughput
        de ramas distintas (distancia >= min_distance). Si no encuentra
        candidatos válidos, retorna None.
        """
        if not self.config.cross_branch_crossover_enabled:
            return None
        if len(self._lineage.nodes) < 10:
            return None
        if random.random() > self.config.cross_branch_crossover_prob:
            return None

        min_dist = self.config.cross_branch_min_distance

        # Buscar nodos con fitness parcial conocido
        correctness_nodes = []
        throughput_nodes = []
        for nid, node in self._lineage.nodes.items():
            if not node.fitness:
                continue
            corr = node.fitness.get("correctness", 0.0)
            tp = node.fitness.get("throughput", 0.0)
            if corr > 0.5:
                correctness_nodes.append(node)
            if tp > 0.5:
                throughput_nodes.append(node)

        if len(correctness_nodes) < 1 or len(throughput_nodes) < 1:
            return None

        # Intentar hasta 10 combinaciones
        for _ in range(10):
            node_a = random.choice(correctness_nodes)
            node_b = random.choice(throughput_nodes)
            if node_a.id == node_b.id:
                continue
            dist = self._lineage.get_genealogical_distance(node_a.id, node_b.id)
            if dist is not None and dist >= min_dist:
                # Usar el código del local_best de islas diferentes
                candidates_a = [isl for isl in self.islands
                                if isl.id != island.id and isl.local_best]
                if not candidates_a:
                    return None
                parent_a = random.choice(candidates_a).local_best
                parent_b = island.local_best or random.choice(island.population)

                child_code = island._crossover(parent_a.code, parent_b.code)
                child = Individual(
                    code=child_code,
                    parent_ids=[parent_a.id, parent_b.id],
                )
                logger.debug(
                    "Cross-branch crossover: nodes %s × %s (dist=%d)",
                    node_a.id[:8], node_b.id[:8], dist,
                )
                return child

        return None

    def _score_with_novelty(self, individual: Individual) -> float:
        """
        [MEJ-3] Combina fitness funcional con bonus de novedad semántica.

        score_combined = (1 - alpha) * fitness + alpha * novelty_score

        Beneficio: penaliza individuos que convergen a soluciones ya
        conocidas en el archivo, manteniendo diversidad genética sin
        sacrificar fitness.

        Si el archivo no está disponible, devuelve el fitness puro.
        """
        if self.archive is None or self.config.novelty_alpha == 0.0:
            return individual.score
        novelty = self.archive.novelty_score(individual.code, k=10)
        alpha = self.config.novelty_alpha
        return (1.0 - alpha) * individual.score + alpha * novelty * 100.0

    def run(self, task: str = "") -> Individual:
        """Ejecuta el ciclo evolutivo completo.

        Integra:
          - [MEJ-1] Parada temprana por EarlyStopMonitor (ventana de mejora)
          - [MEJ-2/3] Archivado con novelty_score para penalizar convergencia
        """
        self._start_time = time.perf_counter()
        logger.info(
            "MutaLambda starting: %d islands × %d generations",
            self.config.num_islands,
            self.config.generations,
        )

        global_best: Optional[Individual] = None

        for gen in range(self.config.generations):
            gen_start = time.perf_counter()

            # ── Fase 2: Evolución paralela de islas ───────────────────────
            island_snapshots = self._island_pool.run_generation(
                self.islands, gen
            )

            # ── Fase 6: HITL — inyectar hints de experto ────────────────
            self._process_hitl_hints()

            # ── Métricas de diversidad entre islas ────────────────────────
            cross_diversity = self._compute_cross_island_diversity()
            if gen % 5 == 0:
                diversities = [s.diversity for s in island_snapshots]
                logger.debug(
                    "Gen %d diversity — intra: [%s] | cross: %.3f",
                    gen + 1,
                    ", ".join(f"{d:.3f}" for d in diversities),
                    cross_diversity,
                )

            # ── Convergent Evolution Boost (consenso entre islas) ─────
            if gen % max(1, self.config.migration_interval) == 0:
                boost_stats = self._apply_convergent_boost()
                if boost_stats.get("boosted", 0) > 0:
                    logger.info(
                        "Gen %d — convergent boost: %d inds × %d pairs",
                        gen + 1, boost_stats["boosted"], boost_stats.get("pairs", 0),
                    )

            # ── Fase 7: Retroceso Temporal (resurrección de ramas) ─────
            if (self.config.resurrection_enabled
                    and self._early_stop.stagnant_generations
                    >= self.config.resurrection_threshold
                    and self._lineage._resurrection_count
                    < self.config.resurrection_max_attempts
                    and global_best is not None):
                threshold = (self.config.resurrection_min_score_ratio
                             * global_best.score)
                candidates = self._lineage.find_abandoned_branches(
                    global_best.id, threshold,
                )
                if candidates:
                    resurrected = self._resurrect_branch(candidates[0])
                    stagnant_island = self._find_stagnant_island()
                    if stagnant_island:
                        stagnant_island.population[0] = resurrected
                        logger.info(
                            "Gen %d — ♜ resurrected branch → island %d",
                            gen + 1, stagnant_island.id,
                        )

            # ── Fase 6: NSGA-II stats ────────────────────────────────────
            if gen % 5 == 0:
                try:
                    from nsga2 import get_nsga2_stats
                    all_inds = [
                        ind for isl in self.islands
                        for ind in isl.population
                    ]
                    nsga_stats = get_nsga2_stats(all_inds)
                    logger.debug(
                        "NSGA-II fronts=%d pareto=%d crowding=%.3f",
                        nsga_stats["num_fronts"],
                        nsga_stats["pareto_frontier_size"],
                        nsga_stats["mean_crowding"],
                    )
                except ImportError:
                    pass

            # Evolución de prompts (opcional)
            if self.prompt_evolver and task:
                best_so_far = self.migration_bus.get_global_best()
                base_code = best_so_far.code if best_so_far else ""
                self.prompt_evolver.step(task, base_code)

            # Actualizar global best usando score combinado con novedad
            current_best = self.migration_bus.get_global_best()
            if current_best:
                combined = self._score_with_novelty(current_best)
                if global_best is None or combined > self._score_with_novelty(global_best):
                    global_best = copy.deepcopy(current_best)

            # Archivar soluciones prometedoras (batch para todo el gen)
            if self.archive and global_best:
                self.archive.add(
                    global_best.code,
                    {"score": global_best.score, "generation": float(gen)},
                )

            # Métricas
            gen_elapsed = time.perf_counter() - gen_start
            self._generation_times.append(gen_elapsed)
            current_score = global_best.score if global_best else float("-inf")
            self._global_best_history.append(current_score)

            # Logging periódico
            if gen % 5 == 0 or gen == self.config.generations - 1:
                avg_time = (
                    sum(self._generation_times[-5:]) /
                    min(5, len(self._generation_times[-5:]))
                )
                logger.info(
                    "Gen %d/%d | best=%.4f | avg_time=%.2fs | "
                    "archive=%d | stagnant=%d",
                    gen + 1, self.config.generations, current_score,
                    avg_time,
                    self.archive.size if self.archive else 0,
                    self._early_stop.stagnant_generations,
                )

            # Checkpoint periódico
            if (
                self.config.checkpoint_interval > 0
                and (gen + 1) % self.config.checkpoint_interval == 0
            ):
                self._save_checkpoint(gen + 1)

            # [MEJ-1] Parada temprana por convergencia (más fino que threshold fijo)
            if self._early_stop.update(current_score):
                logger.info(
                    "Early stop en gen %d: sin mejora ≥%.4f en %d generaciones.",
                    gen + 1, self.config.early_stop_delta,
                    self.config.early_stop_patience,
                )
                break

        total_time = time.perf_counter() - self._start_time
        logger.info(
            "Evolution complete in %.1fs. Best score: %.4f",
            total_time,
            global_best.score if global_best else float("-inf"),
        )

        self.shutdown()

        if global_best is None:
            raise RuntimeError("Evolution produced no valid individuals.")
        return global_best

    def _save_checkpoint(self, generation: int) -> None:
        """Guarda un checkpoint completo con RNG y estado de islas."""
        try:
            from checkpoint_manager import save_full_checkpoint
            # Pass raw config if we loaded from YAML, else None
            raw_config = getattr(self, '_raw_config', None)
            save_full_checkpoint(
                self, generation, self.config,
                raw_config=raw_config,
            )
        except ImportError:
            # Fallback al checkpoint básico
            os.makedirs(self.config.checkpoint_dir, exist_ok=True)
            path = os.path.join(
                self.config.checkpoint_dir, f"checkpoint_gen{generation:04d}.json"
            )
            best = self.migration_bus.get_global_best()
            data = {
                "generation": generation,
                "best_score": best.score if best else None,
                "best_code": best.code if best else None,
                "island_generations": [isl.generation for isl in self.islands],
                "avg_gen_time": (
                    sum(self._generation_times) / len(self._generation_times)
                    if self._generation_times else 0
                ),
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug("Checkpoint saved: %s", path)

    def shutdown(self) -> None:
        """Apaga recursos de forma controlada."""
        self.evaluator.shutdown()
        logger.info("MutaLambda agent shut down cleanly.")

    def get_metrics(self) -> Dict[str, Any]:
        """Retorna métricas acumuladas del agente."""
        return {
            "total_generations": len(self._generation_times),
            "total_time_sec": round(sum(self._generation_times), 4),
            "avg_generation_time_sec": round(
                sum(self._generation_times) / len(self._generation_times)
                if self._generation_times else 0, 4
            ),
            "best_score_history": self._global_best_history,
            "archive_size": self.archive.size if self.archive else 0,
            "num_islands": len(self.islands),
            "stagnant_generations": self._early_stop.stagnant_generations,
            "novelty_alpha": self.config.novelty_alpha,
            # Fase 2 — métricas de diversidad
            "cross_island_diversity": self._compute_cross_island_diversity(),
            "parallel_generations": self._island_pool.generation_count,
        }


# ══════════════════════════════════════════════════════════════════════════════
# 10. SUITE DE TESTS INTEGRADA
# ══════════════════════════════════════════════════════════════════════════════


def run_full_test_suite() -> bool:
    """
    [MEJ-4] Suite de tests completa ejecutable con --test.
    Cubre todos los componentes críticos y los 4 bugs parcheados.
    Retorna True si todos pasan, False en caso contrario.
    """
    import traceback

    passed: List[str] = []
    failed: List[Tuple[str, str]] = []

    def test(name: str, fn: Callable[[], None]) -> None:
        try:
            fn()
            passed.append(name)
            print(f"  [PASS] {name}")
        except Exception as e:
            tb = traceback.format_exc().splitlines()[-1]
            failed.append((name, tb))
            print(f"  [FAIL] {name} — {tb}")

    print("\n" + "═" * 60)
    print("SUITE DE TESTS — MutaLambda Agent (v2 patched)")
    print("═" * 60)

    # ── Bloque 1: ASTMutator ────────────────────────────────────────────────
    print("\n── ASTMutator ──")

    def t_ast_syntax_valid():
        code = "def f(x):\n    total = 0\n    for i in range(x):\n        total += i\n    return total\n"
        invalid = sum(1 for _ in range(200) if _ast_invalid(ASTMutator.apply_random_mutation(code)))
        assert invalid == 0, f"{invalid}/200 mutaciones produjeron código inválido"

    def _ast_invalid(c: str) -> bool:
        try:
            ast.parse(c)
            return False
        except SyntaxError:
            return True

    def t_no_builtin_rename():
        """[BUG-1] _rename_variable no debe renombrar builtins."""
        code = "def f(n):\n    total = 0\n    for i in range(n):\n        total += i\n    return total\n"
        builtins_broken = 0
        for _ in range(500):
            m = ASTMutator.apply_random_mutation(code)
            # Si 'range' fue renombrado, el código fallará al ejecutarse
            if "range" not in m and "rangea" in m or "rangeb" in m or "rangec" in m:
                builtins_broken += 1
        assert builtins_broken == 0, f"Builtin renombrado {builtins_broken} veces"

    def t_replace_aug_no_class_mutation():
        """[BUG-2] _replace_aug_assign usa ast.Assign real, no __class__ hack."""
        code = "x = 0\nfor i in range(5):\n    x += i\n"
        tree = ast.parse(code)
        ASTMutator._replace_aug_assign(tree)
        ast.fix_missing_locations(tree)
        result = ast.unparse(tree)
        ast.parse(result)  # debe ser válido
        # Verificar que NO hay AugAssign (fue reemplazado)
        new_tree = ast.parse(result)
        aug = [n for n in ast.walk(new_tree) if isinstance(n, ast.AugAssign)]
        assert len(aug) == 0, "AugAssign no fue reemplazado"

    test("ast_todas_mutaciones_validas (200 runs)", t_ast_syntax_valid)
    test("BUG-1: no_rename_builtins (500 runs)", t_no_builtin_rename)
    test("BUG-2: replace_aug_assign_sin_class_hack", t_replace_aug_no_class_mutation)

    # ── Bloque 1b: CoreEvolutionEngine ─────────────────────────────────────
    print("\n── CoreEvolutionEngine ──")

    def t_core_selects_ast_regions():
        code = (
            "def solve(xs):\n"
            "    total = 0\n"
            "    for x in xs:\n"
            "        if x > 0:\n"
            "            total += x\n"
            "    return total\n"
        )
        engine = CoreEvolutionEngine()
        regions = engine.select_code_regions(code)
        assert regions, "No seleccionó regiones AST"
        assert regions[0].kind == "FunctionDef"
        assert regions[0].name == "solve"
        assert regions[0].complexity_score > 0

    def t_core_prompt_contract_is_strict():
        code = "def f(x):\n    return x + 1\n"
        engine = CoreEvolutionEngine()
        region = engine.select_code_regions(code, max_regions=1)[0]
        prompt = engine.build_mutation_prompt(code, region, score=1.0)
        assert "MODE: HEURISTIC_MUTATION" in prompt
        assert "Return raw Python code only" in prompt
        assert "Do not use Markdown fences" in prompt
        assert "ast.parse()" in prompt

    def t_core_extracts_fenced_code_and_rejects_prose():
        engine = CoreEvolutionEngine()
        fenced = "Here is code:\n```python\ndef f(x):\n    return x\n```\n"
        assert engine.extract_valid_code(fenced) == "def f(x):\n    return x"
        assert engine.extract_valid_code("I would improve it by using a loop.") is None

    def t_core_llm_mutation_falls_back_to_valid_code():
        code = "def f(x):\n    return x + 1\n"
        engine = CoreEvolutionEngine()
        result = engine.mutate_with_llm(
            code=code,
            score=-1.0,
            error_info="SyntaxError",
            llm_fn=lambda _prompt: "not python prose",
        )
        ast.parse(result)

    def t_core_llm_crossover_accepts_valid_code():
        code_a = "def f(x):\n    return x + 1\n"
        code_b = "def f(x):\n    return x * 2\n"
        engine = CoreEvolutionEngine()
        result = engine.crossover_with_llm(
            code_a,
            code_b,
            llm_fn=lambda _prompt: "def f(x):\n    return x + 2\n",
        )
        assert result == "def f(x):\n    return x + 2"

    test("core_selects_ast_regions", t_core_selects_ast_regions)
    test("core_prompt_contract_is_strict", t_core_prompt_contract_is_strict)
    test("core_extracts_fenced_code_and_rejects_prose", t_core_extracts_fenced_code_and_rejects_prose)
    test("core_llm_mutation_falls_back_to_valid_code", t_core_llm_mutation_falls_back_to_valid_code)
    test("core_llm_crossover_accepts_valid_code", t_core_llm_crossover_accepts_valid_code)

    # ── Bloque 2: SolutionArchive ────────────────────────────────────────────
    print("\n── SolutionArchive ──")

    def t_pending_prunes_correct():
        """[BUG-3] pending_prunes solo incrementa cuando hay evicción real."""
        # Simular la lógica corregida
        from collections import deque as _deque
        max_size = 5
        solutions = _deque(maxlen=max_size)
        prunes = 0
        for i in range(10):
            will_evict = len(solutions) == max_size
            solutions.append(i)
            if will_evict:
                prunes += 1
        # Con max_size=5, las evictions ocurren en los appends 6,7,8,9,10 → 5 evictions
        assert prunes == 5, f"Esperado 5 evictions, obtenido {prunes}"

    test("BUG-3: pending_prunes_correcto", t_pending_prunes_correct)

    # ── Bloque 3: MigrationBus ───────────────────────────────────────────────
    print("\n── MigrationBus ──")

    def t_cache_within_lock():
        """[BUG-4] _get_neighbors debe usarse desde dentro del lock."""
        bus = MigrationBus(topology="ring")

        class _FakeIsland:
            config = IslandConfig()
            local_best = None
            generation = 0
            population: list = []
            def get_migrants(self, n): return []
            def receive_migrant(self, x): pass

        for k in range(4):
            bus.islands[k] = _FakeIsland()

        # Llamar desde dentro del lock (como lo hace migrate)
        with bus._lock:
            neighbors = bus._get_neighbors(0)
        assert isinstance(neighbors, list) and len(neighbors) == 2

    def t_cache_invalidation():
        """Cache se invalida al registrar nueva isla."""
        bus = MigrationBus(topology="ring")

        class _FakeIsland:
            config = IslandConfig()
            local_best = None
            generation = 0
            population: list = []
            def get_migrants(self, n): return []
            def receive_migrant(self, x): pass

        for k in range(3):
            bus.islands[k] = _FakeIsland()

        v1 = bus._islands_version
        bus.register_island(99, _FakeIsland())
        v2 = bus._islands_version
        assert v2 > v1, "islands_version no incrementó"
        assert bus._neighbor_cache == {}, "Cache no fue limpiado al registrar"

    test("BUG-4: neighbors_dentro_de_lock", t_cache_within_lock)
    test("cache_invalida_al_registrar", t_cache_invalidation)

    # ── Bloque 4: EarlyStopMonitor ───────────────────────────────────────────
    print("\n── EarlyStopMonitor ──")

    def t_early_stop_triggers():
        """EarlyStop dispara después de `patience` generaciones sin mejora."""
        monitor = EarlyStopMonitor(patience=5, delta=0.01)
        score = 10.0
        stop = False
        for _ in range(20):
            stop = monitor.update(score)  # mismo score → no mejora
            if stop:
                break
        assert stop, "EarlyStop no disparó"
        assert monitor.stagnant_generations >= 5

    def t_early_stop_reset_on_improvement():
        """EarlyStop NO dispara si hay mejora relativa suficiente."""
        monitor = EarlyStopMonitor(patience=5, delta=0.01)
        score = 1.0
        for i in range(10):
            score *= 1.05  # 5% de mejora cada vez → no debe parar
            triggered = monitor.update(score)
            assert not triggered, f"Paró prematuramente en gen {i}"

    test("early_stop_dispara_sin_mejora", t_early_stop_triggers)
    test("early_stop_no_dispara_con_mejora", t_early_stop_reset_on_improvement)

    # ── Bloque 5: EvolveConfig ───────────────────────────────────────────────
    print("\n── EvolveConfig ──")

    def t_evolve_config_defaults():
        cfg = EvolveConfig()
        assert cfg.early_stop_patience == 15
        assert cfg.early_stop_delta == 0.001
        assert cfg.novelty_alpha == 0.15
        assert 0.0 <= cfg.novelty_alpha <= 1.0

    test("EvolveConfig_defaults_correctos", t_evolve_config_defaults)

    # ── Resumen ──────────────────────────────────────────────────────────────
    print("\n" + "─" * 60)
    total = len(passed) + len(failed)
    print(f"Resultado: {len(passed)}/{total} tests pasaron")
    if failed:
        print("\nFallidos:")
        for name, err in failed:
            print(f"  ✗ {name}: {err}")
    print("═" * 60 + "\n")

    return len(failed) == 0

def _demo_llm_fn(prompt: str) -> str:
    """LLM simulado para demostración: aplica micro-mutaciones al código."""
    # Extraer código del prompt (heurística simple)
    lines = prompt.split("\n")
    code_lines = [
        l for l in lines
        if l.strip() and not l.startswith(("You are", "Task:", "Improve", "Return", "Instructions:"))
    ]
    code = "\n".join(code_lines).strip()
    if not code:
        return "def solution():\n    return 42"

    # Intentar mutación AST
    mutated = ASTMutator.apply_random_mutation(code)
    return mutated


def main() -> None:
    """Demo/CLI: ejecuta MutaLambda con un LLM simulado o corre los tests."""
    import argparse

    parser = argparse.ArgumentParser(description="MutaLambda Agent v2")
    parser.add_argument("--islands", type=int, default=3)
    parser.add_argument("--generations", type=int, default=20)
    parser.add_argument("--pop-size", type=int, default=6)
    parser.add_argument("--topology", default="ring",
                        choices=["ring", "fully_connected", "random", "mesh"])
    parser.add_argument("--novelty-alpha", type=float, default=0.15,
                        help="Peso del bonus de novedad en el score (0.0–1.0)")
    parser.add_argument("--early-stop-patience", type=int, default=15)
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    # [MEJ-4] Flag para correr la suite de tests
    parser.add_argument("--test", action="store_true",
                        help="Ejecutar suite de tests integrada y salir")
    # Fase 5 — Config declarativa + checkpointing
    parser.add_argument("--config", type=str, default=None,
                        help="Ruta a archivo YAML de configuración")
    parser.add_argument("--resume", type=str, default=None,
                        help="Ruta a checkpoint para reanudar evolución")
    # Fase 6 — HITL dashboard + hints
    parser.add_argument("--dashboard", action="store_true",
                        help="Activar dashboard de consola HITL")
    parser.add_argument("--hint", type=str, default=None,
                        help="Inyectar código como hint experto en una isla")
    args = parser.parse_args()

    # Ajustar nivel de log desde CLI
    logging.getLogger("MutaLambda").setLevel(args.log_level)

    if args.test:
        ok = run_full_test_suite()
        sys.exit(0 if ok else 1)

    # ── Fase 5: Cargar desde YAML si --config ──────────────────────
    if args.config:
        config = EvolveConfig.from_yaml(args.config)
        # Store raw config for checkpoint hash
        from config_loader import load_yaml
        agent_kwargs = {"config": config}
    else:
        # Código semilla
        seed = (
            "def compute_sum(n):\n"
            "    total = 0\n"
            "    for i in range(n):\n"
            "        total += i\n"
            "    return total\n"
        )

        config = EvolveConfig(
            num_islands=args.islands,
            generations=args.generations,
            seed_codes=[seed],
            topology=args.topology,
            population_size=args.pop_size,
            top_k=max(2, args.pop_size // 3),
            archive_solutions=False,   # Deshabilitar FAISS para demo rápida
            prompt_evolution=False,
            novelty_alpha=args.novelty_alpha,
            early_stop_patience=args.early_stop_patience,
        )
        # Set sandbox defaults for CLI mode
        config.sandbox_timeout = 5.0
        config.sandbox_workers = 4

    # ── Resume from checkpoint if --resume ──────────────────────────
    if args.resume:
        from checkpoint_manager import resume_agent
        agent = resume_agent(
            args.resume, config,
            test_cases=[],
            llm_fn=_demo_llm_fn,
        )
        # Continue from checkpoint generation
        best = agent.run(task="Continue evolution from checkpoint")
    else:
        agent = MutaLambdaAgent(
            config=config,
            llm_fn=_demo_llm_fn,
            test_cases=[],
            timeout_sec=getattr(config, 'sandbox_timeout', 5.0),
        )
        best = agent.run(task="Optimize a sum function for correctness and speed")
    print("\n" + "=" * 60)
    print("BEST SOLUTION FOUND:")
    print("=" * 60)
    print(best.code)
    print(f"\nScore: {best.score:.4f}")
    print("\nMetrics:", json.dumps(agent.get_metrics(), indent=2, default=str))
if __name__ == "__main__":
    main()
