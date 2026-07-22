"""Unified validated configuration (ML-C01 / ML-C02 / ML-C04).

Single entrypoint for CLI and core:

    config = MutaLambdaConfig.from_yaml(path)
    evolve = config.to_evolve_config()

Uses Pydantic v2 for bounds/validation before workers or LLM clients start.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EvolutionSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    num_islands: int = Field(4, ge=1)
    generations: int = Field(50, ge=1)
    topology: Literal["ring", "fully_connected", "random", "mesh", "spatial_grid"] = "ring"
    early_stop_patience: int = Field(15, ge=0)
    early_stop_delta: float = Field(0.001, ge=0.0)
    novelty_alpha: float = Field(0.15, ge=0.0, le=1.0)
    fitness_normalize: bool = True
    use_process_pool: bool = False
    operator_bandit_enabled: bool = False
    operator_bandit_strategy: Literal["ucb1", "epsilon_greedy"] = "ucb1"

    @model_validator(mode="before")
    @classmethod
    def _lift_bandit(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        bandit = data.get("operator_bandit")
        if isinstance(bandit, dict):
            data = dict(data)
            data["operator_bandit_enabled"] = bandit.get("enabled", False)
            data["operator_bandit_strategy"] = bandit.get("strategy", "ucb1")
        return data


class PopulationSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    size: int = Field(8, ge=2)
    top_k: int = Field(3, ge=1)
    migration_interval: int = Field(10, gt=0)
    migrants_per_island: int = Field(2, ge=0)

    @model_validator(mode="after")
    def _top_k_bound(self) -> "PopulationSection":
        if self.top_k > self.size:
            raise ValueError("population.top_k must be <= population.size")
        return self


class SandboxSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    timeout_sec: float = Field(10.0, gt=0)
    max_workers: int = Field(4, gt=0)
    # Recommended secure mode is container; subprocess remains local-dev default.
    runner: Literal["subprocess", "container", "microvm", "docker", "podman", "local", "dev"] = (
        "subprocess"
    )
    allow_expression_eval: bool = False
    enforce_ast_scan: bool = False
    memory_mb: int = Field(256, ge=0)


class TargetSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_file: str = ""
    entrypoint: str = ""
    task: str = ""
    tests_file: str = ""
    benchmark_file: str = ""
    api_policy: Literal["strict", "relaxed"] = "strict"
    enforce_api_fingerprint: bool = False
    enforce_differential: bool = False


class PrivacySection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    allow_external_llm: bool = False
    redact_secrets: bool = True
    allowed_backends: List[str] = Field(default_factory=lambda: ["ollama"])


class LLMSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    provider: Literal["openai"] = "openai"
    mutator_model: str = "gpt-4o-mini"
    mutator_temperature: float = Field(0.1, ge=0.0, le=2.0)
    mutator_max_tokens: int = Field(1400, ge=1)
    mutator_timeout_sec: float = Field(60.0, gt=0)
    backend: Literal["ollama", "openai", "anthropic", "openrouter", "mistral"] = "ollama"
    model: str = "llama3.2:3b"
    timeout_sec: float = Field(60.0, gt=0)
    temperature: float = Field(0.2, ge=0.0, le=2.0)
    max_retries: int = Field(3, ge=0)
    max_calls_per_generation: int = Field(0, ge=0)
    max_total_calls: int = Field(0, ge=0)
    replay_log: str = ""


class CheckpointSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    interval: int = Field(10, ge=0)
    dir: str = "checkpoints"
    directory: Optional[str] = None  # CLI legacy alias
    save_archive: bool = True
    save_prompts: bool = True

    @property
    def checkpoint_dir(self) -> str:
        return self.directory or self.dir


class ArchiveSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    max_size: int = Field(10_000, ge=1)
    prune_threshold: int = Field(50, ge=1)
    embedder_model: str = "all-MiniLM-L6-v2"
    dedupe_similarity: float = Field(0.98, ge=0.0, le=1.0)


class BenchmarkSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    warmups: int = Field(0, ge=0)
    samples: int = Field(1, ge=1)
    operations_per_case: int = Field(1, ge=1)
    repetitions: int = Field(1, ge=1)


class WorkflowSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    max_retries: int = Field(1, ge=0)
    correctness_threshold: float = Field(1.0, ge=0.0, le=1.0)
    require_score_improvement: bool = False
    enforce_security: bool = True
    enforce_api_fingerprint: bool = False
    enforce_differential: bool = False
    trace_limit: int = Field(200, ge=1)


class ReproducibilitySection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    seed: Optional[int] = None
    track_git_commit: bool = True


class PromptEvolutionSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    pop_size: int = Field(6, ge=1)
    elite_frac: float = Field(0.5, ge=0.0, le=1.0)


class MutaLambdaConfig(BaseModel):
    """Root validated config — shared by CLI and core."""

    model_config = ConfigDict(extra="ignore")

    evolution: EvolutionSection = Field(default_factory=EvolutionSection)
    population: PopulationSection = Field(default_factory=PopulationSection)
    sandbox: SandboxSection = Field(default_factory=SandboxSection)
    target: TargetSection = Field(default_factory=TargetSection)
    privacy: PrivacySection = Field(default_factory=PrivacySection)
    llm: LLMSection = Field(default_factory=LLMSection)
    checkpoint: CheckpointSection = Field(default_factory=CheckpointSection)
    archive: ArchiveSection = Field(default_factory=ArchiveSection)
    benchmark: BenchmarkSection = Field(default_factory=BenchmarkSection)
    workflow: WorkflowSection = Field(default_factory=WorkflowSection)
    reproducibility: ReproducibilitySection = Field(default_factory=ReproducibilitySection)
    prompt_evolution: PromptEvolutionSection = Field(default_factory=PromptEvolutionSection)
    # Optional nested blocks kept as loose dicts for experimental flags
    hfc: Dict[str, Any] = Field(default_factory=dict)
    thc: Dict[str, Any] = Field(default_factory=dict)
    advanced_selection: Dict[str, Any] = Field(default_factory=dict)
    dialectic: Dict[str, Any] = Field(default_factory=dict)
    spatial: Dict[str, Any] = Field(default_factory=dict)
    pattern_memory: Dict[str, Any] = Field(default_factory=dict)
    logging: Dict[str, Any] = Field(default_factory=dict)
    allow_untested: bool = True

    @classmethod
    def from_yaml(cls, path: str | Path) -> "MutaLambdaConfig":
        """Load YAML via config_loader defaults+validate, then Pydantic model."""
        from config_loader import load_yaml

        raw = load_yaml(path)
        return cls.model_validate(raw)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MutaLambdaConfig":
        from config_loader import apply_defaults, validate_config

        cfg = apply_defaults(dict(data or {}))
        errors = validate_config(cfg)
        if errors:
            raise ValueError("Config validation failed:\n  - " + "\n  - ".join(errors))
        return cls.model_validate(cfg)

    def to_evolve_config(self, *, generations: Optional[int] = None):
        """Convert to EvolveConfig used by MutaLambdaAgent."""
        from muta_lambda import EvolveConfig

        evo = self.evolution
        pop = self.population
        sand = self.sandbox
        arch = self.archive
        prompt = self.prompt_evolution
        chk = self.checkpoint
        llm = self.llm
        wf = self.workflow
        tgt = self.target
        priv = self.privacy
        bench = self.benchmark
        hfc = self.hfc or {}
        thc = self.thc or {}
        advanced = self.advanced_selection or {}
        dialectic = self.dialectic or {}
        spatial = self.spatial or {}
        patterns = self.pattern_memory or {}

        config = EvolveConfig(
            num_islands=evo.num_islands,
            generations=generations if generations is not None else evo.generations,
            topology=evo.topology,
            population_size=pop.size,
            top_k=pop.top_k,
            migration_interval=pop.migration_interval,
            migrants_per_island=pop.migrants_per_island,
            archive_solutions=arch.enabled,
            prompt_evolution=prompt.enabled,
            checkpoint_enabled=chk.enabled,
            checkpoint_interval=chk.interval,
            checkpoint_dir=chk.checkpoint_dir,
            early_stop_patience=evo.early_stop_patience,
            early_stop_delta=evo.early_stop_delta,
            novelty_alpha=evo.novelty_alpha,
            workflow_enabled=wf.enabled,
            workflow_max_retries=wf.max_retries,
            workflow_correctness_threshold=wf.correctness_threshold,
            workflow_require_score_improvement=wf.require_score_improvement,
            workflow_enforce_security=wf.enforce_security,
            workflow_trace_limit=wf.trace_limit,
            use_process_pool=evo.use_process_pool,
            llm_backend=llm.backend,
            llm_model=llm.model,
            llm_timeout_sec=llm.timeout_sec,
            llm_temperature=llm.temperature,
            prompt_pop_size=prompt.pop_size,
            prompt_elite_frac=prompt.elite_frac,
            hfc_enabled=bool(hfc.get("enabled", False)),
            hfc_tier1_size=int(hfc.get("tier1_size", 100)),
            hfc_tier2_size=int(hfc.get("tier2_size", 50)),
            hfc_tier3_size=int(hfc.get("tier3_size", 10)),
            hfc_lambda_clones=int(hfc.get("lambda_clones", 8)),
            hfc_top_down_distillation=bool(hfc.get("top_down_distillation", True)),
            hfc_top_down_interval=int(hfc.get("top_down_interval", 5)),
            hfc_promotion_correctness=float(hfc.get("promotion_correctness", 1.0)),
            thc_enabled=bool(thc.get("enabled", False)),
            thc_max_transfers_per_generation=int(thc.get("max_transfers_per_generation", 1)),
            thc_min_donor_score=float(thc.get("min_donor_score", 0.0)),
            thc_validate_in_sandbox=bool(thc.get("validate_in_sandbox", True)),
            advanced_selection_enabled=bool(advanced.get("enabled", False)),
            advanced_fitness_weight=float(advanced.get("fitness_weight", 1.0)),
            advanced_novelty_weight=float(advanced.get("novelty_weight", 0.15)),
            advanced_entropy_weight=float(advanced.get("entropy_weight", 0.20)),
            advanced_discovery_weight=float(advanced.get("discovery_weight", 0.35)),
            dialectic_enabled=bool(dialectic.get("enabled", False)),
            dialectic_critique_intensity=str(dialectic.get("critique_intensity", "medium")),
            spatial_enabled=bool(spatial.get("enabled", False)),
            spatial_neighborhood=str(spatial.get("neighborhood", "moore")),
            pattern_memory_enabled=bool(patterns.get("enabled", False)),
            allow_untested=self.allow_untested,
            runner_mode=sand.runner,
            allow_expression_eval=sand.allow_expression_eval,
            enforce_ast_scan=sand.enforce_ast_scan,
            enforce_api_fingerprint=wf.enforce_api_fingerprint or tgt.enforce_api_fingerprint,
            enforce_differential=wf.enforce_differential or tgt.enforce_differential,
            benchmark_warmups=bench.warmups,
            benchmark_samples=bench.samples,
            benchmark_operations_per_case=bench.operations_per_case,
            privacy_allow_external_llm=priv.allow_external_llm,
            privacy_redact_secrets=priv.redact_secrets,
            target_source_file=tgt.source_file,
            target_entrypoint=tgt.entrypoint,
            target_task=tgt.task,
            target_tests_file=tgt.tests_file,
            target_benchmark_file=tgt.benchmark_file,
            target_api_policy=tgt.api_policy,
            master_seed=self.reproducibility.seed,
            operator_bandit_enabled=evo.operator_bandit_enabled,
            operator_bandit_strategy=evo.operator_bandit_strategy,
            fitness_normalize=evo.fitness_normalize,
            archive_dedupe_similarity=arch.dedupe_similarity,
            llm_max_retries=llm.max_retries,
            llm_max_calls_per_generation=llm.max_calls_per_generation,
            llm_max_total_calls=llm.max_total_calls,
            llm_replay_log=llm.replay_log,
        )
        config.sandbox_timeout = sand.timeout_sec
        config.sandbox_workers = sand.max_workers
        return config

    def recommended_runner_message(self) -> str:
        if self.sandbox.runner in {"subprocess", "local", "dev"}:
            return (
                "sandbox.runner=subprocess is for local development only. "
                "For untrusted candidates use sandbox.runner=container "
                "(Docker/Podman: network=none, cap-drop, read-only)."
            )
        return f"sandbox.runner={self.sandbox.runner} (hardened isolation path)"
