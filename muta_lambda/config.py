"""Configuration model for MutaLambda (Phase 2D extraction).

``EvolveConfig`` is the single source of truth for runtime configuration. It is
re-exported from ``muta_lambda/__init__.py`` so existing callers
(``from muta_lambda import EvolveConfig``) are unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

__all__ = ["EvolveConfig"]


@dataclass
class EvolveConfig:
    """Configuración global del agente."""

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
    checkpoint_enabled: bool = True
    checkpoint_interval: int = 10
    checkpoint_dir: str = "checkpoints"
    checkpoint_format: str = "auto"  # 'auto' (threshold-based), 'json', or 'msgpack'
    early_stop_patience: int = 15
    early_stop_delta: float = 0.001
    novelty_alpha: float = 0.15
    workflow_enabled: bool = True
    workflow_max_retries: int = 1
    workflow_correctness_threshold: float = 1.0
    workflow_require_score_improvement: bool = False
    workflow_enforce_security: bool = True
    workflow_trace_limit: int = 200
    convergent_boost_enabled: bool = True
    convergent_boost_threshold: float = 0.85
    convergent_boost_factor: float = 0.15
    resurrection_enabled: bool = True
    resurrection_threshold: int = 8
    resurrection_max_attempts: int = 3
    resurrection_min_score_ratio: float = 0.3
    cross_branch_crossover_enabled: bool = True
    cross_branch_crossover_prob: float = 0.05
    cross_branch_min_distance: int = 3
    use_process_pool: bool = False
    llm_backend: str = "ollama"
    llm_model: str = "llama3.2:3b"
    observability_enabled: bool = True
    observability_metrics_port: int = 9100
    llm_timeout_sec: float = 60.0
    llm_temperature: float = 0.2
    prompt_pop_size: int = 6
    prompt_elite_frac: float = 0.5
    hfc_enabled: bool = False
    hfc_tier1_size: int = 100
    hfc_tier2_size: int = 50
    hfc_tier3_size: int = 10
    hfc_lambda_clones: int = 8
    hfc_top_down_distillation: bool = True
    hfc_top_down_interval: int = 5
    hfc_promotion_correctness: float = 1.0
    thc_enabled: bool = False
    thc_max_transfers_per_generation: int = 1
    thc_min_donor_score: float = 0.0
    thc_validate_in_sandbox: bool = True
    advanced_selection_enabled: bool = False
    advanced_fitness_weight: float = 1.0
    advanced_novelty_weight: float = 0.15
    advanced_entropy_weight: float = 0.20
    advanced_discovery_weight: float = 0.35
    dialectic_enabled: bool = False
    dialectic_critique_intensity: str = "medium"
    spatial_enabled: bool = False
    spatial_neighborhood: str = "moore"
    pattern_memory_enabled: bool = False
    allow_untested: bool = True
    # UAST feature flags — disabled by default for safe opt-in
    use_uast: bool = False
    uast_supported_languages: List[str] = field(default_factory=lambda: ["python", "rust"])
    uast_endpoint: str = ""
    uast_timeout_sec: float = 30.0
    uast_cache_enabled: bool = True
    uast_cache_dir: str = ".uast_cache"
    runner_mode: str = "subprocess"  # subprocess | container | microvm
    allow_expression_eval: bool = False
    enforce_ast_scan: bool = True
    require_tests: bool = False  # CLI sets True unless --allow-untested
    enforce_api_fingerprint: bool = False
    enforce_differential: bool = False
    benchmark_warmups: int = 0
    benchmark_samples: int = 1
    benchmark_operations_per_case: int = 1
    privacy_allow_external_llm: bool = False
    llm_max_retries: int = 3
    llm_max_calls_per_generation: int = 0
    llm_max_total_calls: int = 0
    llm_replay_log: str = ""
    master_seed: Optional[int] = None
    operator_bandit_enabled: bool = True
    operator_bandit_strategy: str = "ucb1"
    fitness_normalize: bool = True
    archive_dedupe_similarity: float = 0.98
    autodoc_elites: bool = True
    write_run_artifacts: bool = True
    privacy_redact_secrets: bool = True
    target_source_file: str = ""
    target_entrypoint: str = ""
    target_task: str = ""
    target_tests_file: str = ""
    target_benchmark_file: str = ""
    target_api_policy: str = "strict"

    @classmethod
    def from_yaml(cls, path: str) -> "EvolveConfig":
        """Load EvolveConfig from a validated YAML file.

        Preferred path: unified Pydantic ``MutaLambdaConfig`` (CLI + core).
        """
        try:
            from muta_config import MutaLambdaConfig

            return MutaLambdaConfig.from_yaml(path).to_evolve_config()
        except Exception as _mlc_exc:
            # Legacy fallback keeps older call sites working if schema drifts.
            import logging as _logging
            _logging.getLogger("MutaLambda").debug(
                "MutaLambdaConfig path failed (%s); using legacy from_yaml", _mlc_exc
            )
        from config_loader import load_yaml

        cfg = load_yaml(path)

        evo = cfg.get("evolution", {})
        pop = cfg.get("population", {})
        sand = cfg.get("sandbox", {})
        arch = cfg.get("archive", {})
        prompt = cfg.get("prompt_evolution", {})
        chk = cfg.get("checkpoint", {})
        log = cfg.get("logging", {})
        llm = cfg.get("llm", {})
        repro = cfg.get("reproducibility", {})
        hfc = cfg.get("hfc", {})
        thc = cfg.get("thc", {})
        advanced = cfg.get("advanced_selection", {})
        dialectic = cfg.get("dialectic", {})
        spatial = cfg.get("spatial", {})
        patterns = cfg.get("pattern_memory", {})
        privacy = cfg.get("privacy", {})
        target = cfg.get("target", {})

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
            checkpoint_enabled=chk.get("enabled", True),
            checkpoint_interval=chk.get("interval", 10),
            checkpoint_dir=chk.get("dir", "checkpoints"),
            checkpoint_format=chk.get("format", "auto"),
            early_stop_patience=evo.get("early_stop_patience", 15),
            early_stop_delta=evo.get("early_stop_delta", 0.001),
            novelty_alpha=evo.get("novelty_alpha", 0.15),
            workflow_enabled=cfg.get("workflow", {}).get("enabled", True),
            workflow_max_retries=cfg.get("workflow", {}).get("max_retries", 1),
            workflow_correctness_threshold=cfg.get("workflow", {}).get("correctness_threshold", 1.0),
            workflow_require_score_improvement=cfg.get("workflow", {}).get("require_score_improvement", False),
            workflow_enforce_security=cfg.get("workflow", {}).get("enforce_security", True),
            workflow_trace_limit=cfg.get("workflow", {}).get("trace_limit", 200),
            convergent_boost_enabled=evo.get("convergent_boost", {}).get("enabled", True),
            convergent_boost_threshold=evo.get("convergent_boost", {}).get("threshold", 0.85),
            convergent_boost_factor=evo.get("convergent_boost", {}).get("factor", 0.15),
            resurrection_enabled=evo.get("resurrection", {}).get("enabled", True),
            resurrection_threshold=evo.get("resurrection", {}).get("threshold", 8),
            resurrection_max_attempts=evo.get("resurrection", {}).get("max_attempts", 3),
            resurrection_min_score_ratio=evo.get("resurrection", {}).get("min_score_ratio", 0.3),
            cross_branch_crossover_enabled=evo.get("cross_branch_crossover", {}).get("enabled", True),
            cross_branch_crossover_prob=evo.get("cross_branch_crossover", {}).get("prob", 0.05),
            cross_branch_min_distance=evo.get("cross_branch_crossover", {}).get("min_distance", 3),
            use_process_pool=evo.get("use_process_pool", False),
            llm_backend=llm.get("backend", "ollama"),
            llm_model=llm.get("model", "llama3.2:3b"),
            llm_timeout_sec=llm.get("timeout_sec", 60.0),
            llm_temperature=llm.get("temperature", 0.2),
            prompt_pop_size=prompt.get("pop_size", 6),
            prompt_elite_frac=prompt.get("elite_frac", 0.5),
            hfc_enabled=hfc.get("enabled", False),
            hfc_tier1_size=hfc.get("tier1_size", 100),
            hfc_tier2_size=hfc.get("tier2_size", 50),
            hfc_tier3_size=hfc.get("tier3_size", 10),
            hfc_lambda_clones=hfc.get("lambda_clones", 8),
            hfc_top_down_distillation=hfc.get("top_down_distillation", True),
            hfc_top_down_interval=hfc.get("top_down_interval", 5),
            hfc_promotion_correctness=hfc.get("promotion_correctness", 1.0),
            thc_enabled=thc.get("enabled", False),
            thc_max_transfers_per_generation=thc.get("max_transfers_per_generation", 1),
            thc_min_donor_score=thc.get("min_donor_score", 0.0),
            thc_validate_in_sandbox=thc.get("validate_in_sandbox", True),
            advanced_selection_enabled=advanced.get("enabled", False),
            advanced_fitness_weight=advanced.get("fitness_weight", 1.0),
            advanced_novelty_weight=advanced.get("novelty_weight", 0.15),
            advanced_entropy_weight=advanced.get("entropy_weight", 0.20),
            advanced_discovery_weight=advanced.get("discovery_weight", 0.35),
            dialectic_enabled=dialectic.get("enabled", False),
            dialectic_critique_intensity=dialectic.get("critique_intensity", "medium"),
            spatial_enabled=spatial.get("enabled", False),
            spatial_neighborhood=spatial.get("neighborhood", "moore"),
            pattern_memory_enabled=patterns.get("enabled", False),
            enforce_api_fingerprint=cfg.get("workflow", {}).get("enforce_api_fingerprint",
                cfg.get("target", {}).get("enforce_api_fingerprint", False)),
            enforce_differential=cfg.get("workflow", {}).get("enforce_differential",
                cfg.get("target", {}).get("enforce_differential", False)),
            benchmark_warmups=cfg.get("benchmark", {}).get("warmups", 0),
            benchmark_samples=cfg.get("benchmark", {}).get("samples", 1),
            benchmark_operations_per_case=cfg.get("benchmark", {}).get("operations_per_case", 1),
            allow_untested=cfg.get("allow_untested", True),
            runner_mode=sand.get("runner", sand.get("mode", "subprocess")),
            allow_expression_eval=sand.get("allow_expression_eval", False),
            enforce_ast_scan=sand.get("enforce_ast_scan", True),
            privacy_allow_external_llm=privacy.get("allow_external_llm", False),
            privacy_redact_secrets=privacy.get("redact_secrets", True),
            target_source_file=target.get("source_file", ""),
            target_entrypoint=target.get("entrypoint", ""),
            target_task=target.get("task", ""),
            target_tests_file=target.get("tests_file", ""),
            target_benchmark_file=target.get("benchmark_file", ""),
            target_api_policy=target.get("api_policy", "strict"),
            use_uast=cfg.get("uast", {}).get("use_uast", False),
            uast_supported_languages=cfg.get("uast", {}).get(
                "supported_languages", ["python", "rust"]
            ),
            uast_endpoint=cfg.get("uast", {}).get("uast_endpoint", ""),
            uast_timeout_sec=cfg.get("uast", {}).get("uast_timeout_sec", 30.0),
            uast_cache_enabled=cfg.get("uast", {}).get("cache_enabled", True),
            uast_cache_dir=cfg.get("uast", {}).get("cache_dir", ".uast_cache"),
        )

        config.sandbox_timeout = sand.get("timeout_sec", 10.0)
        config.sandbox_workers = sand.get("max_workers", 4)

        log_level = log.get("level", "INFO")
        logging.getLogger("MutaLambda").setLevel(log_level)

        seed = repro.get("seed")
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)

        return config


# ── Tipos relacionados (Phase 2A extrae EarlyStopMonitor + GenerationResult) ──
from models import Individual  # noqa: E402
from island_evolution import IslandSnapshot  # noqa: E402

__all__ = ["EvolveConfig", "EarlyStopMonitor", "GenerationResult"]


class EarlyStopMonitor:
    """Detector de convergencia por ventana de mejora relativa."""

    def __init__(self, patience: int = 15, delta: float = 0.001):
        self.patience = patience
        self.delta = delta
        self._best: float = float("-inf")
        self._no_improve: int = 0

    def update(self, score: float) -> bool:
        """Retorna True si se detecta convergencia."""
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


@dataclass
class GenerationResult:
    """Resultado de una generación (API incremental CLI/dashboard/core)."""

    generation: int
    best: Optional[Individual] = None
    snapshots: List[IslandSnapshot] = field(default_factory=list)
    should_stop: bool = False
    combined_best_score: float = float("-inf")

