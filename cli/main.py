"""
Main CLI logic for MutaLambda.

Provides the MutaLambdaCLI class that orchestrates all CLI operations
and the InteractiveREPL for real-time control.
"""

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cli.animator import RetroAnimator
from cli.checkpoint_manager import CheckpointManager
from cli.config_manager import ConfigManager
from muta_lambda import MutaLambdaAgent, EvolveConfig


console = Console()


class MutaLambdaCLI:
    """Main CLI orchestrator for MutaLambda operations"""

    def __init__(self):
        self.config_manager = ConfigManager()
        self.checkpoint_manager = CheckpointManager()
        self.animator = RetroAnimator()
        self.current_config = None
        self.agent: Optional[MutaLambdaAgent] = None
        self.generation = 0
        self._test_cases: List[Dict[str, Any]] = []
        self._seed_codes: List[str] = []
        self._task: str = "Optimize Python code for correctness and performance"
        self._allow_untested: bool = False

    def run_evolution(
        self,
        config_path: Optional[str] = None,
        generations: int = 50,
        animation: str = 'retro',
        verbose: bool = False,
        source: Optional[str] = None,
        tests: Optional[str] = None,
        task: Optional[str] = None,
        allow_untested: bool = False,
    ) -> bool:
        """Run a complete evolution process"""

        self._allow_untested = allow_untested

        # Load or create config
        if config_path:
            self.current_config = self.config_manager.load(config_path)
            if not self.current_config:
                return False
        else:
            self.current_config = self.config_manager.get_default()

        if not self._prepare_target(source=source, tests=tests, task=task):
            return False

        # Create MutaLambda agent
        evolve_config = self._create_evolve_config(self.current_config, generations)

        if not evolve_config:
            console.print("[red]Failed to create evolution config[/red]")
            return False

        # Initialize agent
        self.agent = self._create_agent(evolve_config)

        if not self.agent:
            console.print("[red]Failed to initialize agent[/red]")
            return False

        # Run with selected animation style
        if animation == 'retro':
            return self._run_with_retro_animation(generations, verbose)
        elif animation == 'minimal':
            return self._run_minimal_animation(generations, verbose)
        else:
            return self._run_no_animation(generations, verbose)

    def _prepare_target(
        self,
        source: Optional[str],
        tests: Optional[str],
        task: Optional[str],
    ) -> bool:
        """Resolve source code + tests from CLI args or YAML target section."""
        cfg = self.current_config or {}
        target = cfg.get("target") or {}

        source_path = source or target.get("source_file") or ""
        tests_path = tests or target.get("tests_file") or ""
        self._task = task or target.get("task") or self._task

        if source_path:
            p = Path(source_path)
            if not p.exists():
                console.print(f"[red]Source file not found: {source_path}[/red]")
                return False
            self._seed_codes = [p.read_text(encoding="utf-8")]
        else:
            self._seed_codes = []

        if tests_path:
            p = Path(tests_path)
            if not p.exists():
                console.print(f"[red]Tests file not found: {tests_path}[/red]")
                return False
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                console.print("[red]Tests file must be a JSON list of cases[/red]")
                return False
            self._test_cases = data
        else:
            self._test_cases = []

        if not self._test_cases and not self._allow_untested:
            console.print(
                "[red]No test cases configured. Use --tests or target.tests_file, "
                "or pass --allow-untested only for development.[/red]"
            )
            return False

        return True

    def _create_evolve_config(self, config: dict, generations: int) -> Optional[EvolveConfig]:
        """Create EvolveConfig from CLI config via unified MutaLambdaConfig (ML-C02)."""
        try:
            from muta_config import MutaLambdaConfig

            # Legacy CLI templates may use migration.* instead of population.*
            raw = dict(config or {})
            if "migration" in raw and "population" not in raw:
                mig = raw.get("migration") or {}
                evo = raw.setdefault("evolution", {})
                raw["population"] = {
                    "size": evo.get("population_size", 8),
                    "top_k": evo.get("top_k", 3),
                    "migration_interval": mig.get("interval", 10),
                    "migrants_per_island": mig.get("migrants_per_island", 2),
                }
                if "topology" not in evo and "topology" in mig:
                    evo["topology"] = mig["topology"]
            if "checkpoint" in raw:
                chk = raw["checkpoint"]
                if "dir" not in chk and "directory" in chk:
                    chk = dict(chk)
                    chk["dir"] = chk["directory"]
                    raw["checkpoint"] = chk

            ml = MutaLambdaConfig.from_dict(raw)
            evolve = ml.to_evolve_config(generations=generations)
            evolve.seed_codes = list(self._seed_codes)
            evolve.allow_untested = self._allow_untested
            evolve.require_tests = not self._allow_untested
            if self._task:
                evolve.target_task = self._task
            # Surface isolation guidance once
            msg = ml.recommended_runner_message()
            if "subprocess" in msg:
                console.print(f"[dim]{msg}[/dim]")
            return evolve
        except Exception as e:
            console.print(f"[red]Error creating evolve config: {e}[/red]")
            return None

    def _create_agent(self, config: EvolveConfig) -> Optional[MutaLambdaAgent]:
        """Create and initialize MutaLambda agent"""
        try:
            timeout = float(
                (self.current_config or {}).get('sandbox', {}).get('timeout_sec', 10.0)
            )
            agent = MutaLambdaAgent(
                config,
                test_cases=self._test_cases,
                timeout_sec=timeout,
                task=self._task,
            )

            console.print(f"[green]✓ Initialized {config.num_islands} islands[/green]")
            console.print(f"[green]✓ Population: {config.population_size} per island[/green]")
            console.print(f"[green]✓ Topology: {config.topology}[/green]")
            console.print(f"[green]✓ Tests: {len(self._test_cases)} cases[/green]")
            console.print()

            return agent

        except Exception as e:
            console.print(f"[red]Failed to create agent: {e}[/red]")
            return None

    def _run_with_retro_animation(self, generations: int, verbose: bool) -> bool:
        """Run evolution with retro animations"""

        self.animator.print_banner()
        console.print()

        start_time = time.time()
        best_score = 0.0
        history = []

        try:
            with Live(console=console, refresh_per_second=10) as live:
                for gen in range(generations):
                    self.generation = gen + 1

                    # Execute one evolution step (shared core API)
                    result = self.agent.step_generation(generation=gen, task=self._task)
                    best = result.best or self.agent.migration_bus.get_global_best()
                    if best:
                        best_score = max(best_score, best.score if best.score > float("-inf") else best_score)
                        history.append(best_score)

                    # Build and update display
                    state = self._get_agent_state()
                    layout = self._create_evolution_layout(state, generations)
                    live.update(layout)

                    # Save checkpoint if needed
                    if (gen + 1) % self.agent.config.checkpoint_interval == 0:
                        if self.agent.config.checkpoint_enabled:
                            self._save_checkpoint(gen + 1, best_score)

                    if result.should_stop:
                        break

                    # Small delay for smooth animation
                    time.sleep(0.05)

            # Final summary
            elapsed = time.time() - start_time
            self._display_final_results(history, elapsed)

            return True

        except KeyboardInterrupt:
            console.print("\n[yellow]Evolution interrupted by user[/yellow]")
            return False
        except Exception as e:
            console.print(f"\n[red]Evolution error: {e}[/red]")
            if verbose:
                import traceback
                traceback.print_exc()
            return False

    def _run_minimal_animation(self, generations: int, verbose: bool) -> bool:
        """Run evolution with minimal output"""

        console.print(f"[bold cyan]MutaLambda Evolution[/bold cyan] ({generations} generations)\n")

        start_time = time.time()
        best_score = 0.0
        history = []

        try:
            for gen in range(generations):
                self.generation = gen + 1

                result = self.agent.step_generation(generation=gen, task=self._task)
                best = result.best or self.agent.migration_bus.get_global_best()
                if best and best.score > float("-inf"):
                    best_score = max(best_score, best.score)
                    history.append(best_score)

                if result.should_stop:
                    break

                # Progress update every 10 generations
                if (gen + 1) % 10 == 0:
                    elapsed = time.time() - start_time
                    console.print(
                        f"Gen {gen + 1}/{generations} | "
                        f"Best: {best_score:.3f} | "
                        f"Time: {elapsed:.1f}s"
                    )

                # Checkpoint
                if (gen + 1) % self.agent.config.checkpoint_interval == 0:
                    if self.agent.config.checkpoint_enabled:
                        self._save_checkpoint(gen + 1, best_score)

            # Final
            elapsed = time.time() - start_time
            console.print(f"\n[green]✓ Evolution complete[/green]")
            console.print(f"  Generations: {generations}")
            console.print(f"  Best Score: {best_score:.4f}")
            console.print(f"  Time: {elapsed:.1f}s")

            return True

        except KeyboardInterrupt:
            console.print("\n[yellow]Evolution interrupted[/yellow]")
            return False
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]")
            return False

    def _run_no_animation(self, generations: int, verbose: bool) -> bool:
        """Run evolution with no animation (silent)"""

        best_score = 0.0
        history = []

        try:
            for gen in range(generations):
                self.generation = gen + 1

                result = self.agent.step_generation(generation=gen, task=self._task)
                best = result.best or self.agent.migration_bus.get_global_best()
                if best and best.score > float("-inf"):
                    best_score = max(best_score, best.score)
                    history.append(best_score)

                # Checkpoint
                if (gen + 1) % self.agent.config.checkpoint_interval == 0:
                    if self.agent.config.checkpoint_enabled:
                        self._save_checkpoint(gen + 1, best_score)

                if result.should_stop:
                    break

            if verbose:
                console.print(f"Complete: {generations} generations, best={best_score:.4f}")

            return True

        except Exception as e:
            if verbose:
                console.print(f"[red]Error: {e}[/red]")
            return False

    def _get_agent_state(self) -> dict:
        """Get current state from agent"""
        islands_data = []

        for island in self.agent.islands:
            best = island.local_best
            best_score = best.score if best else 0.0
            pop_size = len(island.population)

            islands_data.append({
                'id': island.id,
                'best_score': best_score,
                'population': pop_size,
            })

        global_best = self.agent.migration_bus.get_global_best()
        global_best_score = global_best.score if global_best else 0.0

        return {
            'generation': self.generation,
            'islands': islands_data,
            'global_best_score': global_best_score,
        }

    def _create_evolution_layout(self, state: dict, total_gens: int) -> Layout:
        """Create live evolution layout with real data"""

        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="islands", size=8),
            Layout(name="footer", size=3),
        )

        layout["body"].split_row(
            Layout(name="progress", size=40),
            Layout(name="stats"),
        )

        gen = state['generation']
        best = state['global_best_score']

        # Header
        layout["header"].update(Panel(
            Text.assemble(
                (" MutaΛ ", "bold magenta"),
                (f"Gen {gen}/{total_gens}", "bold cyan"),
                ("  Best: ", "bold"),
                (f"{best:.4f}", "bold green"),
            ),
            border_style="cyan"
        ))

        # Progress bar
        layout["progress"].update(Panel(
            self.animator.progress_bar(gen, total_gens, best),
            title="[bold]Progress[/bold]",
            border_style="green"
        ))

        # Stats table
        stats_table = Table.grid(padding=(0, 1))
        stats_table.add_column(style="cyan", justify="right")
        stats_table.add_column(style="green")

        stats_table.add_row("Generation:", str(gen))
        stats_table.add_row("Best Score:", f"{best:.4f}")
        stats_table.add_row("Islands:", str(len(state['islands'])))
        stats_table.add_row("Total Pop:", str(sum(i['population'] for i in state['islands'])))

        layout["stats"].update(Panel(
            stats_table,
            title="[bold]Stats[/bold]",
            border_style="blue"
        ))

        # Island grid
        island_panels = []
        for island_data in state['islands']:
            panel = self.animator.island_display(
                island_data['id'],
                island_data['best_score'],
                island_data['population']
            )
            island_panels.append(Panel(panel))

        if island_panels:
            if len(island_panels) <= 2:
                layout["islands"].split_row(*[Layout(p) for p in island_panels])
            else:
                mid = len(island_panels) // 2
                layout["islands"].split_column(
                    Layout(name="top_islands"),
                    Layout(name="bot_islands"),
                )
                layout["top_islands"].split_row(*[Layout(p) for p in island_panels[:mid]])
                layout["bot_islands"].split_row(*[Layout(p) for p in island_panels[mid:]])

        # Footer with fitness graph (last 50 generations)
        history = [i['best_score'] for i in state['islands']][-50:]
        if history:
            layout["footer"].update(Panel(
                self.animator.fitness_graph(history, width=60, height=1),
                title="[bold]Fitness Trend[/bold]"
            ))

        return layout

    def _save_checkpoint(self, generation: int, score: float):
        """Save JSON checkpoint (no pickle)."""
        try:
            state = {
                'generation': generation,
                'best_score': score,
                'islands': [
                    {
                        'id': island.id,
                        'best_score': island.local_best.score if island.local_best else 0.0,
                        'population': len(island.population)
                    }
                    for island in self.agent.islands
                ]
            }

            self.checkpoint_manager.save(
                state=state,
                generation=generation,
                score=score,
                compress=True,
            )
        except Exception as e:
            console.print(f"[yellow]Warning: checkpoint failed: {e}[/yellow]")

    def _display_final_results(self, history: list, elapsed: float):
        """Display final results"""

        if not history:
            console.print("[yellow]No evolution data collected[/yellow]")
            return

        best = max(history)
        final = history[-1]

        # Results table
        results = Table.grid(padding=(0, 2))
        results.add_column(style="cyan")
        results.add_column(style="green")

        results.add_row("Best Score:", f"{best:.4f}")
        results.add_row("Final Score:", f"{final:.4f}")
        results.add_row("Generations:", str(len(history)))
        results.add_row("Time:", f"{elapsed:.1f}s")

        if len(history) > 1:
            improvement = best - history[0]
            results.add_row("Improvement:", f"{improvement:+.4f}")

        console.print()
        console.print(Panel(
            results,
            title="[bold green]🏆 Final Results[/bold green]",
            border_style="green"
        ))
        console.print()

        # Fitness graph
        console.print(Panel(
            self.animator.fitness_graph(history, width=60, height=6),
            title="[bold]Evolution History[/bold]",
            border_style="cyan"
        ))

    def resume_evolution(
        self,
        checkpoint_path: str,
        additional_gens: int = 50,
        animation: str = 'retro'
    ) -> bool:
        """Resume evolution from a core or CLI checkpoint (JSON only)."""

        console.print(f"[cyan]Loading checkpoint: {checkpoint_path}[/cyan]")
        path = Path(checkpoint_path)

        # Prefer core checkpoint_manager when format matches.
        core_ckpt = None
        try:
            candidate = path
            if path.is_dir():
                candidate = path / "checkpoint.json"
            if candidate.exists() and candidate.suffix == ".json":
                raw = candidate.read_text(encoding="utf-8")
                data = json.loads(raw)
                if data.get("format") == "mutalambda-core-json" or "island_populations" in data:
                    core_ckpt = candidate
        except Exception:
            core_ckpt = None

        if core_ckpt is not None:
            return self._resume_from_core_checkpoint(core_ckpt, additional_gens, animation)

        # Fallback: CLI lightweight JSON checkpoints
        checkpoint_data = self.checkpoint_manager.load(checkpoint_path)
        if not checkpoint_data:
            console.print("[red]Failed to load checkpoint[/red]")
            return False

        gen = checkpoint_data.get("generation", 0)
        best = checkpoint_data.get("best_score", 0.0)
        console.print(f"[green]✓ Loaded CLI checkpoint from generation {gen}[/green]")
        console.print(f"[green]✓ Best score: {best}[/green]")
        console.print(
            "[yellow]Note: CLI lightweight checkpoints restore generation metadata only; "
            "use core checkpoints (checkpoints/chk_gen*/checkpoint.json) for full resume.[/yellow]"
        )
        console.print()

        config = checkpoint_data.get("config") or self.config_manager.get_default()
        self.current_config = config
        if not self._prepare_target(source=None, tests=None, task=None):
            # Allow resume of lightweight ckpt with allow_untested if no tests
            if not self._test_cases:
                self._allow_untested = True

        evolve_config = self._create_evolve_config(config, additional_gens)
        if not evolve_config:
            return False

        self.agent = self._create_agent(evolve_config)
        if not self.agent:
            return False

        self.agent._current_generation = int(gen)
        self.agent._generation_completed = int(gen)
        self.generation = int(gen)
        console.print(f"[cyan]Resuming for {additional_gens} additional generations...[/cyan]\n")

        if animation == "retro":
            return self._run_with_retro_animation(additional_gens, False)
        if animation == "minimal":
            return self._run_minimal_animation(additional_gens, False)
        return self._run_no_animation(additional_gens, False)

    def _resume_from_core_checkpoint(
        self,
        checkpoint_path: Path,
        additional_gens: int,
        animation: str,
    ) -> bool:
        """Full restore via checkpoint_manager.resume_agent."""
        try:
            from checkpoint_manager import load_checkpoint, resume_agent
            from muta_lambda import EvolveConfig
        except Exception as e:
            console.print(f"[red]Core resume unavailable: {e}[/red]")
            return False

        try:
            cp = load_checkpoint(checkpoint_path)
        except Exception as e:
            console.print(f"[red]Failed to load core checkpoint: {e}[/red]")
            return False

        console.print(
            f"[green]✓ Core checkpoint gen_completed={cp.generation_completed} "
            f"current={cp.current_generation}[/green]"
        )
        console.print(f"[green]✓ Best score: {cp.best_score}[/green]")
        console.print()

        # Build config: prefer YAML if available, else defaults sized for additional gens.
        if self.current_config is None:
            self.current_config = self.config_manager.get_default()
        evolve_config = self._create_evolve_config(self.current_config, additional_gens)
        if not evolve_config:
            evolve_config = EvolveConfig(
                generations=cp.current_generation + additional_gens,
                allow_untested=True,
                archive_solutions=False,
                prompt_evolution=False,
                checkpoint_enabled=True,
            )
        else:
            # Ensure total horizon covers completed + additional
            evolve_config.generations = max(
                evolve_config.generations,
                int(cp.current_generation) + int(additional_gens),
            )

        if not self._test_cases and not self._allow_untested:
            self._allow_untested = True
            evolve_config.allow_untested = True

        try:
            agent = resume_agent(
                checkpoint_path,
                evolve_config,
                test_cases=self._test_cases,
                llm_fn=None,
            )
        except Exception as e:
            console.print(f"[red]resume_agent failed: {e}[/red]")
            return False

        self.agent = agent
        self.generation = int(agent._current_generation)
        console.print(
            f"[cyan]Resuming from gen {agent._current_generation} "
            f"for {additional_gens} additional generations...[/cyan]\n"
        )

        # Drive via step_generation so we don't double-count from 0.
        try:
            history = []
            best_score = float(cp.best_score) if cp.best_score is not None else float("-inf")
            start = int(agent._current_generation)
            for i, gen in enumerate(range(start, start + additional_gens)):
                self.generation = gen + 1
                result = agent.step_generation(generation=gen, task=agent.task or self._task)
                if result.best and result.best.score > best_score:
                    best_score = result.best.score
                history.append(best_score if best_score > float("-inf") else 0.0)
                if animation == "minimal" and (i + 1) % 10 == 0:
                    console.print(f"Gen {gen + 1} | Best: {best_score:.4f}")
                if result.should_stop:
                    break
            agent.shutdown()
            console.print(f"[green]✓ Resume complete — best={best_score:.4f}[/green]")
            return True
        except Exception as e:
            console.print(f"[red]Resume run error: {e}[/red]")
            try:
                agent.shutdown()
            except Exception:
                pass
            return False

    def run_mutation(
        self,
        target: str,
        mutation_type: str = 'prompt',
        strategy: str = 'adaptive'
    ) -> bool:
        """Run mutation operations (ML-UI01: never report success if nothing changed)."""

        console.print(Panel(
            Text.assemble(
                ("Mutation ", "bold"),
                (mutation_type, "bold cyan"),
                (f" → {target}", "bold"),
            ),
            title="[bold]MutaΛ Mutation[/bold]",
            border_style="cyan"
        ))

        console.print(f"\n[cyan]Strategy: {strategy}[/cyan]")
        console.print(f"[cyan]Target: {target}[/cyan]\n")

        path = Path(target)
        if mutation_type in {"prompt", "operators", "hyperparams"} and not path.exists():
            # Non-file targets (prompt strings) are accepted only for 'prompt'
            if mutation_type != "prompt":
                console.print(
                    f"[red]✗ Target file not found: {target}. "
                    "No mutation applied.[/red]"
                )
                return False

        if mutation_type == "prompt":
            # Minimal real operation: apply AST mutation to a source file if present.
            if path.exists() and path.suffix == ".py":
                try:
                    from evolution_engine import ASTMutator

                    original = path.read_text(encoding="utf-8")
                    mutated = ASTMutator.apply_random_mutation(original)
                    if mutated.strip() == original.strip():
                        console.print(
                            "[red]✗ Mutation produced no change. "
                            "Refusing to report success.[/red]"
                        )
                        return False
                    out = path.with_suffix(path.suffix + f".mut.{strategy}.py")
                    out.write_text(mutated, encoding="utf-8")
                    console.print(f"[green]✓ Wrote mutated source: {out}[/green]")
                    return True
                except Exception as e:
                    console.print(f"[red]✗ Mutation failed: {e}[/red]")
                    return False
            console.print(
                "[red]✗ mutate prompt without a .py file is not implemented. "
                "No changes made.[/red]"
            )
            return False

        if mutation_type in {"operators", "hyperparams"}:
            console.print(
                f"[red]✗ mutate {mutation_type} is not implemented yet. "
                "No configuration was modified.[/red]"
            )
            return False

        console.print(f"[red]✗ Unknown mutation type: {mutation_type}[/red]")
        return False

    def evaluate_results(self, results_path: Optional[str] = None) -> bool:
        """Evaluate and summarize results"""

        console.print(Panel("[bold]Results Evaluation[/bold]", border_style="cyan"))
        console.print()

        if results_path:
            console.print(f"[cyan]Loading results from: {results_path}[/cyan]\n")

            # Load and parse results
            try:
                with open(results_path, 'r') as f:
                    results = json.load(f)

                # Display summary
                if isinstance(results, dict):
                    for key, value in results.items():
                        console.print(f"  {key}: {value}")
                else:
                    console.print(f"  Results: {results}")

            except Exception as e:
                console.print(f"[red]Error loading results: {e}[/red]")
                return False
        else:
            console.print("[dim]No results file specified[/dim]")

        # Show available checkpoints
        console.print("\n[cyan]Available checkpoints:[/cyan]")
        checkpoints = self.checkpoint_manager.list_checkpoints()
        if checkpoints:
            self.checkpoint_manager.display_checkpoints(checkpoints)
        else:
            console.print("[dim]No checkpoints found[/dim]")

        console.print()
        return True

    def create_config(
        self,
        output_path: str,
        template: str = 'basic'
    ) -> bool:
        """Create configuration from template"""

        success = self.config_manager.create_from_template(template, output_path)

        if success:
            console.print(f"\n[green]✓ Created '{template}' config: {output_path}[/green]")

        return success

    def validate_config(self, config_path: str) -> bool:
        """Validate configuration file"""

        console.print(Panel("[bold]Configuration Validation[/bold]", border_style="cyan"))
        console.print()

        config = self.config_manager.load(config_path)
        if not config:
            return False

        is_valid, errors = self.config_manager.validate(config)

        if is_valid:
            console.print("[green]✓ Configuration is valid[/green]")
            self.config_manager.display_summary(config)
        else:
            console.print("[red]✗ Validation errors:[/red]")
            for error in errors:
                console.print(f"  [red]• {error}[/red]")

        console.print()
        return is_valid

    def show_stats(self) -> bool:
        """Show statistics from previous runs"""

        console.print(Panel("[bold]📊 Statistics[/bold]", border_style="cyan"))
        console.print()

        checkpoints = self.checkpoint_manager.list_checkpoints()

        if not checkpoints:
            console.print("[dim]No checkpoints found[/dim]")
            console.print()
            return True

        self.checkpoint_manager.display_checkpoints(checkpoints)

        # Additional stats
        stats = self.checkpoint_manager.get_statistics()

        console.print("\n[bold]Summary:[/bold]")
        for key, value in stats.items():
            console.print(f"  {key}: {value}")

        console.print()
        return True


class InteractiveREPL:
    """Interactive REPL for real-time control"""

    def __init__(self, cli: MutaLambdaCLI):
        self.cli = cli
        self.running = True
        self.paused = False

    def start(self):
        """Start interactive mode"""

        self.cli.animator.print_banner()
        console.print("[bold cyan]Interactive Mode[/bold cyan]")
        console.print("Type [green]help[/green] for commands\n")

        while self.running:
            try:
                command = console.input("[bold green]mutalambda>[/bold green] ").strip()

                if not command:
                    continue

                parts = command.split()
                cmd = parts[0].lower()
                args = parts[1:]

                if cmd == 'help':
                    self.show_help()
                elif cmd == 'status':
                    self.show_status()
                elif cmd == 'run':
                    gens = int(args[0]) if args else 10
                    self.cli.run_evolution(generations=gens)
                elif cmd == 'pause':
                    self.paused = True
                    console.print("[yellow]⏸ Paused[/yellow]")
                elif cmd == 'resume':
                    self.paused = False
                    console.print("[green]▶ Resumed[/green]")
                elif cmd == 'save':
                    path = args[0] if args else None
                    if path:
                        console.print(f"[green]✓ Saved to {path}[/green]")
                    else:
                        console.print("[yellow]Usage: save <checkpoint_path>[/yellow]")
                elif cmd in ['quit', 'exit', 'q']:
                    self.running = False
                    console.print("[dim]Goodbye![/dim]")
                else:
                    console.print(f"[red]Unknown command: {cmd}[/red]")

            except KeyboardInterrupt:
                console.print("\n[yellow]Use 'quit' to exit[/yellow]")
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")

    def show_help(self):
        """Show available commands"""
        table = Table(title="Interactive Commands", border_style="cyan")
        table.add_column("Command", style="bold green")
        table.add_column("Description")

        table.add_row("run [gens]", "Run N generations")
        table.add_row("status", "Show current status")
        table.add_row("pause", "Pause evolution")
        table.add_row("resume", "Resume evolution")
        table.add_row("save <path>", "Save checkpoint")
        table.add_row("quit", "Exit interactive mode")

        console.print(table)

    def show_status(self):
        """Show current evolution status"""
        if not self.cli.agent:
            console.print("[dim]No active evolution[/dim]")
            return

        state = self.cli._get_agent_state()

        console.print(Panel(
            self.cli.animator.island_grid(state['islands']),
            title=f"[bold]Status - Generation {state['generation']}[/bold]",
            border_style="cyan"
        ))
