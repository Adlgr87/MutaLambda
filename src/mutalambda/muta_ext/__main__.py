#!/usr/bin/env python3
"""Entry point for MutaLambda CLI."""
import argparse
import json
import os
import sys
from pathlib import Path

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table

from mutalambda.muta_ext import (
    MutaLambdaOptimizer,
    ProjectAnalyzer,
    ExplainableOptimizer,
    create_ci_pipeline,
    __version__
)

console = Console()


def _detect_code_type(source: str) -> str:
    """Quick heuristic to detect code type for recommendations."""
    indicators = {
        'numpy': 'np.' in source or 'numpy' in source,
        'pandas': 'pd.' in source or 'pandas' in source,
        'scipy': 'scipy' in source,
        'ml': 'sklearn' in source or 'torch' in source or 'tensorflow' in source,
    }
    matches = [name for name, present in indicators.items() if present]
    return ', '.join(matches) if matches else 'general'


def cmd_optimize(args):
    """Run optimization on a file."""
    optimizer = MutaLambdaOptimizer(config_path=args.config)
    
    if args.language:
        optimizer.config["language"] = args.language
    
    source = Path(args.input).read_text(encoding="utf-8")
    result = optimizer.optimize(source)
    
    print(json.dumps(result, indent=2, default=str))


def cmd_analyze(args):
    """Analyze a project."""
    analyzer = ProjectAnalyzer(args.project_root)
    report = analyzer.analyze(max_depth=args.max_depth)
    
    if args.output:
        analyzer.save_report(args.output)
        print(f"Report saved to {args.output}")
    else:
        print(json.dumps(report, indent=2, default=str))


def cmd_explain(args):
    """Generate explanation for optimization."""
    optimizer = ExplainableOptimizer()
    
    original = Path(args.original).read_text(encoding="utf-8")
    optimized = Path(args.optimized).read_text(encoding="utf-8")
    
    result = optimizer.optimize_and_explain(
        original_code=original,
        optimized_code=optimized,
        optimization_type=args.type,
        function_name=args.function,
        fitness_results=json.loads(args.fitness)
    )
    
    print(json.dumps(result, indent=2, default=str))


def cmd_ci(args):
    """Run CI analysis."""
    result = create_ci_pipeline(repo_path=args.repo_path)
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2, default=str)
        print(f"Report saved to {args.output}")
    else:
        print(json.dumps(result, indent=2, default=str))


def cmd_register_baseline(args):
    """Register a performance baseline."""
    from mutalambda.muta_ext.ci_integration import register_baseline_from_ci
    
    register_baseline_from_ci(
        file_path=args.file,
        function_name=args.function,
        language=args.language,
        fitness=json.loads(args.fitness),
        code=Path(args.code).read_text() if args.code else "",
        commit_hash=args.commit or "",
        branch=args.branch
    )
    print(f"Baseline registered for {args.function} in {args.file}")


# ── UX commands (Fase 1-2) ────────────────────────────────────────────────

def cmd_init(args):
    """Interactive wizard to create optimized config.yaml."""
    from mutalambda.cli.config_manager import ConfigManager
    config_mgr = ConfigManager()
    
    console.print(Panel(
        "[bold cyan]MutaLambda Configuration Wizard[/bold cyan]\n"
        "Voy a ayudarte a crear una configuración optimizada para tu código.",
        title="✨ Bienvenido"
    ))
    
    # Step 1: code type
    console.print("\n[bold]1. ¿Qué tipo de código vas a optimizar?[/bold]")
    code_type = Prompt.ask(
        "Selecciona",
        choices=["1", "2", "3", "4"],
        default="3",
        show_choices=True
    )
    type_labels = {
        "1": "NumPy/Data Science",
        "2": "Código Científico",
        "3": "Aplicación General",
        "4": "Código Legacy",
    }
    console.print(f"  → {type_labels[code_type]} seleccionado")
    
    # Step 2: optimization aggressiveness
    console.print("\n[bold]2. ¿Qué tan agresiva debe ser la optimización?[/bold]")
    aggressiveness = Prompt.ask(
        "Selecciona",
        choices=["1", "2", "3"],
        default="2",
        show_choices=True
    )
    agg_labels = {
        "1": "Conservador (cambios seguros)",
        "2": "Balanceado",
        "3": "Agresivo (más riesgo, más ganancia)",
    }
    console.print(f"  → {agg_labels[aggressiveness]} seleccionado")
    
    # Map selections to presets
    preset_map = {
        ("1", "1"): "numpy",    # NumPy + conservador
        ("1", "2"): "numpy",    # NumPy + balanceado
        ("1", "3"): "numpy",    # NumPy + agresivo
        ("2", "1"): "scientific",
        ("2", "2"): "scientific",
        ("2", "3"): "research",
        ("3", "1"): "quick",
        ("3", "2"): "production",
        ("3", "3"): "advanced",
        ("4", "1"): "quick",
        ("4", "2"): "production",
        ("4", "3"): "production",
    }
    preset = preset_map.get((code_type, aggressiveness), "basic")
    
    # Show what we picked
    console.print(f"\n[bold green]✓ Configuración recomendada: preset '{preset}'[/bold green]")
    
    # Allow override
    if Confirm.ask("¿Crear config.yaml con este preset?", default=True):
        output = args.output or "config.yaml"
        success = config_mgr.create_from_template(preset, output)
        if success:
            console.print(f"\n[green]✓ Configuración guardada en {output}[/green]")
            console.print("  Ejecuta: [cyan]mutalambda evolve --config {output}[/cyan]")
        else:
            console.print(f"[red]✗ Error creando configuración[/red]")
            return False
    
    return True


def cmd_doctor(args):
    """Diagnose and fix config issues."""
    from mutalambda.cli.config_manager import ConfigManager
    config_mgr = ConfigManager()
    
    config_path = args.config or "config.yaml"
    config = config_mgr.load(config_path)
    
    if not config:
        console.print(f"[red]✗ No se pudo cargar {config_path}[/red]")
        return False
    
    issues = config_mgr.diagnostic(config)
    
    if not issues:
        console.print(Panel("[green]✓ ¡Todo correcto! No se encontraron problemas.[/green]",
                            title="Diagnóstico"))
        return True
    
    console.print(Panel(
        f"[yellow]Se encontraron {len(issues)} problema(s)[/yellow]",
        title="Diagnóstico MutaLambda"
    ))
    
    for i, issue in enumerate(issues, 1):
        severity_color = {
            "warning": "yellow", "info": "blue", "error": "red"
        }.get(issue["severity"], "yellow")
        console.print(f"\n  [{severity_color}]{i}. {issue['message']}[/{severity_color}]")
        if issue.get("fix_suggestion"):
            console.print(f"     🔧 {issue['fix_suggestion']}")
    
    if args.fix:
        console.print(f"\n[bold]Aplicando fixes...[/bold]")
        fixes_applied = 0
        for issue in issues:
            if "fix_key" in issue and config_mgr.apply_fix(config, issue):
                fixes_applied += 1
                console.print(f"  ✓ Corregido: {issue['code']}")
        
        config_mgr.save(config, config_path)
        console.print(f"\n[green]✓ Se aplicaron {fixes_applied} fix(es) en {config_path}[/green]")
    else:
        console.print(f"\n[dim]Ejecuta con --fix para aplicar correcciones automáticas[/dim]")
    
    return True


def cmd_recommend(args):
    """Analyze code and recommend optimal configuration."""
    from mutalambda.cli.config_manager import ConfigManager
    config_mgr = ConfigManager()
    
    source_path = args.file
    if not Path(source_path).exists():
        console.print(f"[red]✗ Archivo no encontrado: {source_path}[/red]")
        return False
    
    source = Path(source_path).read_text(encoding="utf-8")
    code_type = _detect_code_type(source)
    
    console.print(Panel(
        f"[bold cyan]Análisis de código: {source_path}[/bold cyan]\n"
        f"Tipo detectado: [green]{code_type}[/green]",
        title="📋 Recomendación MutaLambda"
    ))
    
    # File size heuristic
    file_size = len(source)
    lines = source.count('\n')
    
    if code_type == 'numpy' or 'ml' in code_type:
        preset = "numpy"
        reason = "Código numérico/ML — numpy preset activa mutadores específicos"
    elif lines > 200:
        preset = "scientific"
        reason = "Código extenso — preset científico con full feature set"
    elif lines < 50:
        preset = "quick"
        reason = "Código conciso — quick preset para iteración rápida"
    else:
        preset = "production"
        reason = "Código general — preset balanceado para producción"
    
    console.print(f"\n[bold]Recomendación:[/bold] preset '{preset}'")
    console.print(f"  Razón: {reason}")
    
    # Show key differences
    presets = config_mgr.templates.get(preset, {})
    console.print(f"\n[bold]Configuración clave:[/bold]")
    console.print(f"  Generations: {presets.get('evolution', {}).get('generations', 50)}")
    console.print(f"  Islands: {presets.get('evolution', {}).get('num_islands', 4)}")
    console.print(f"  Population: {presets.get('evolution', {}).get('population_size', 8)}")
    if 'sandbox' in presets:
        console.print(f"  Timeout: {presets['sandbox'].get('timeout_sec', 10)}s")
    
    if args.apply:
        output = args.output or f"config.{preset}.yaml"
        config_mgr.create_from_template(preset, output)
        console.print(f"\n[green]✓ Configuración guardada en {output}[/green]")
    
    return True


def cmd_dashboard(args):
    """Launch visual dashboard to inspect existing runs."""
    if args.text:
        _print_text_dashboard(args.run_id)
        return True
    
    # Try Streamlit dashboard
    try:
        import streamlit  # noqa
    except ImportError:
        console.print("[yellow]⚠ Streamlit no está instalado.[/yellow]")
        console.print("  Instálalo con: [cyan]pip install streamlit[/cyan]")
        return True
    
    dashboard_file = Path(__file__).parent.parent / "dashboard_run.py"
    if not dashboard_file.exists():
        console.print(f"[red]✗ Dashboard script not found: {dashboard_file}[/red]")
        return False
    
    console.print("[cyan]🚀 Iniciando dashboard...[/cyan]")
    console.print(f"[dim]Abre http://localhost:8501 en tu navegador[/dim]\n")
    import subprocess
    subprocess.run(["streamlit", "run", str(dashboard_file)])
    return True


def _print_text_dashboard(run_id_or_dir: Optional[str] = None):
    """Fallback: print recent run stats as text (no Streamlit required)."""
    from mutalambda.cli.checkpoint_manager import CheckpointManager
    mgr = CheckpointManager()
    
    checkpoints_dir = Path("checkpoints")
    if not checkpoints_dir.exists():
        console.print(Panel("[dim]No checkpoints directory found[/dim]", title="📊 Dashboard"))
        return
    
    runs = sorted(
        [d for d in checkpoints_dir.iterdir() if d.is_dir() and d.name.startswith("run_")],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )[:10]
    
    if not runs:
        console.print(Panel("[dim]No runs found[/dim]", title="📊 Dashboard"))
        return
    
    console.print(Panel("[bold cyan]📊 Resumen de Ejecuciones[/bold cyan]"))
    table = Table(show_lines=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("Run ID", style="cyan")
    table.add_column("Gen", justify="right")
    table.add_column("Best Score", justify="right")
    table.add_column("Time (s)", justify="right")
    table.add_column("Islands", justify="right")
    
    for i, run_dir in enumerate(runs, 1):
        manifest_path = run_dir / "run_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            best_score = manifest.get("best_score", 0)
            gen_completed = manifest.get("generation_completed", 0)
            metrics = manifest.get("metrics", {}) or {}
            config = manifest.get("config", {}) or {}
            isl = config.get("evolution", {}).get("num_islands", "?") if isinstance(config, dict) else "?"
            if isl == "?" and metrics:
                isl = metrics.get("num_islands", "?")
            gen_val = gen_completed if gen_completed else metrics.get("total_generations", "?")
            time_val = metrics.get("total_time_sec", manifest.get("total_time_sec", 0))
            table.add_row(
                str(i),
                run_dir.name[4:12],
                str(gen_val),
                f"{best_score:.4f}" if isinstance(best_score, (int, float)) else str(best_score),
                f"{time_val:.1f}" if isinstance(time_val, (int, float)) else str(time_val),
                str(isl),
            )
        else:
            table.add_row(str(i), run_dir.name[:8], "?", "?", "?", "?")
    
    console.print(table)
    console.print(f"\n[dim]Usa 'muta_lambda dashboard' para abrir el dashboard web[/dim]")


# ── Phase 2 commands ─────────────────────────────────────────────────────────────────

def _load_run_manifest(run_dir: Path) -> dict:
    manifest_path = run_dir / "run_manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text())
    return {}


def cmd_explain_run(args):
    """Explain evolution decisions from a completed run."""
    run_dir = Path(args.run_dir)
    manifest = _load_run_manifest(run_dir)
    if not manifest:
        console.print(f"[red]✗ Run manifest not found in {run_dir}[/red]")
        return False

    console.print(Panel("[bold cyan]📖 Explaining Evolution Run[/bold cyan]"))

    # Basic run info
    info_table = Table(box=None, show_header=False)
    info_table.add_column("Key", style="dim")
    info_table.add_column("Value")
    info_table.add_row("Run ID", manifest.get("run_id", "—"))
    info_table.add_row("Task", manifest.get("task", "—"))
    info_table.add_row("Git Commit", manifest.get("git_commit", "—")[:8] if manifest.get("git_commit") else "—")
    info_table.add_row("Generations Completed", str(manifest.get("generation_completed", 0)))
    console.print(info_table)

    # Best solution explanation
    best_path = run_dir / "best_solution.py"
    original_path = run_dir / "original.py"

    best_score = manifest.get("best_score", 0)
    if best_score is None:
        best_score = manifest.get("final_metrics", {}).get("best_score", 0)

    console.print(f"\n[cyan]🎯 Best Score:[/cyan] [bold]{best_score:.4f}[/bold]")

    if best_path.exists() and original_path.exists():
        optimizer = ExplainableOptimizer()
        # Determine optimization type from manifest/task
        opt_type = manifest.get("task", "speed")
        # Try to extract fitness results from manifest
        fitness_results = {
            "final_score": float(best_score) if isinstance(best_score, (int, float)) else 0,
            "improvement": manifest.get("improvement_ratio", 0),
        }
        try:
            result = optimizer.optimize_and_explain(
                original_code=original_path.read_text(encoding="utf-8"),
                optimized_code=best_path.read_text(encoding="utf-8"),
                optimization_type=opt_type,
                function_name=manifest.get("target_function", "main"),
                fitness_results=fitness_results,
            )
            # Print nicely formatted explanation
            console.print()
            console.print(Panel(result.get("justification", "No justification available."),
                                title="[bold]Justification[/bold]", border_style="cyan"))
            console.print(f"[yellow]⚠ Risk Level:[/yellow] {result.get('risk_level', 'unknown')}")
            complexity = result.get("complexity", {})
            if complexity.get("time_before") and complexity.get("time_after"):
                console.print(f"[yellow]⚡ Complexity:[/yellow] "
                            f"{complexity['time_before']} → {complexity['time_after']} (time), "
                            f"{complexity.get('space_before', '?')} → {complexity.get('space_after', '?')} (space)")
            if args.full:
                console.print("\n[bold]Best Solution Code:[/bold]")
                console.print(code_format(best_path.read_text(encoding="utf-8"), "python"))
        except Exception as e:
            console.print(f"[yellow]⚠ Could not generate LLM explanation: {e}[/yellow]")

    # Fitness evolution
    fitness_path = run_dir / "fitness_history.json"
    if fitness_path.exists():
        history = json.loads(fitness_path.read_text())
        hist_data = history.get("global_best_history", [])
        if hist_data:
            console.print(f"\n[bold]📈 Fitness Evolution:[/bold]")
            console.print(f"  Generations: {len(hist_data)}")
            console.print(f"  Starting: {hist_data[0]:.4f}")
            console.print(f"  Ending:   {hist_data[-1]:.4f}")
            console.print(f"  Improvement: {((hist_data[-1] - hist_data[0]) / abs(hist_data[0]) * 100) if hist_data[0] else 0:.1f}%")

    console.print(f"\n[dim]Tip: Open full dashboard with 'mutalambda dashboard --text'[/dim]")
    return True


def cmd_compare(args):
    """Compare original, optimized, and baseline solutions."""
    original = Path(args.original)
    optimized = Path(args.optimized)
    baseline = Path(args.baseline) if args.baseline else None

    for f in (original, optimized) + ((baseline,) if baseline else ()):
        if not f.exists():
            console.print(f"[red]✗ File not found: {f}[/red]")
            return False

    console.print(Panel("[bold cyan]⚖️ Solution Comparison[/bold cyan]"))

    # Show unified diff
    import difflib
    original_code = original.read_text(encoding="utf-8").splitlines(keepends=True)
    optimized_code = optimized.read_text(encoding="utf-8").splitlines(keepends=True)

    diff = list(difflib.unified_diff(
        original_code, optimized_code,
        fromfile=str(original), tofile=str(optimized),
        n=3
    ))

    console.print(f"\n[bold]📄 Files:[/bold]")
    table = Table(show_header=False, box=None)
    table.add_column("File", style="cyan")
    table.add_column("Lines", justify="right", style="dim")
    table.add_row(str(original), str(len(original_code)))
    table.add_row(str(optimized), str(len(optimized_code)))
    if baseline:
        table.add_row(str(baseline), str(len(baseline.read_text(encoding="utf-8").splitlines())))
    console.print(table)

    console.print(f"\n[bold green]📝 Changes:[/bold green]")
    diff_text = "".join(diff)
    if diff_text:
        console.print(code_format(diff_text, "diff"))
    else:
        console.print("[dim]No differences found[/dim]")

    # Show stats
    additions = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removals = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

    stats_table = Table(title="Comparison Stats")
    stats_table.add_column("Metric", style="cyan")
    stats_table.add_column("Value", justify="right")
    stats_table.add_row("Lines Added", str(additions))
    stats_table.add_row("Lines Removed", str(removals))
    stats_table.add_row("Net Change", str(additions - removals))
    console.print(stats_table)
    return True


def cmd_tutorial(args):
    """Interactive tutorial for first-time users."""
    console.print(Panel("""
[bold cyan]🐣 MutaLambda Interactive Tutorial[/bold cyan]

Bienvenido al tutorial rápido. Aprenderás los comandos esenciales.
Selecciona qué quieres hacer:
""", title="Tutorial MutaLambda"))

    steps = [
        ("1. Configuración Inicial",
         "Crea tu config.yaml usando el wizard interactivo:",
         "  mutalambda init"),
        ("2. Analizar Código",
         "Obtén una recomendación de config basada en tu código:",
         "  mutalambda recommend my_script.py"),
        ("3. Ejecutar Optimización",
         "Optimiza tu código con un preset:",
         "  mutalambda production my_script.py"),
        ("4. Monitorear Progreso",
         "Ver resultados en texto o en dashboard web:",
         "  mutalambda dashboard --text"),
        ("5. Diagnosticar Problemas",
         "Verifica y corrige tu configuración:",
         "  mutalambda doctor --fix"),
        ("6. Explicar Resultados",
         "Entiende por qué una optimización funcionó:",
         "  mutalambda explain-run checkpoints/run_xxx"),
    ]

    for name, desc, command in steps:
        console.print(f"\n[bold]{name}[/bold]")
        console.print(f"  [dim]{desc}[/dim]")
        console.print(f"  [cyan]{command}[/cyan]")

    console.print(f"\n[bold yellow]✨ Quick Start:[/bold yellow]")
    console.print("  [cyan]mutalambda init && mutalambda optimize my_script.py --config config.yaml[/cyan]")
    console.print("\n[dim]Para más información: https://github.com/Adlgr87/MutaLambda[/dim]")
    return True


def cmd_quick(args):
    """Run evolution with 'quick' preset (fast feedback)."""
    return _run_with_preset(args, "quick")


def cmd_production(args):
    """Run evolution with 'production' preset (balanced settings)."""
    return _run_with_preset(args, "production")


def cmd_scientific(args):
    """Run evolution with 'scientific' preset (SVL + invariants)."""
    return _run_with_preset(args, "scientific")


def cmd_numpy(args):
    """Run evolution with 'numpy' preset (NumPy optimizer)."""
    return _run_with_preset(args, "numpy")


def _run_with_preset(args, preset_name: str):
    """Shared helper: load a preset config and run evolution."""
    from mutalambda.muta_ext.cli.config_manager import ConfigManager
    config_mgr = ConfigManager()
    preset_path = Path("presets") / f"{preset_name}.yaml"
    if not preset_path.exists():
        console.print(f"[red]✗ Preset not found: {preset_path}[/red]")
        return False

    # Copy preset to a temp or named config
    config = yaml.safe_load(preset_path.read_text())
    tmp_config = Path(f"config.{preset_name}.yaml")
    tmp_config.write_text(yaml.dump(config, default_flow_style=False))

    console.print(f"[green]✓ Loaded preset: {preset_name}[/green]")
    console.print(f"  Config: {tmp_config}")

    # If user passed a file argument, run optimize
    if hasattr(args, "file") and args.file:
        file_path = Path(args.file)
        console.print(f"  File: {file_path}")
        console.print(f"\n[bold cyan]🚀 Starting evolution ({preset_name})...[/bold cyan]\n")
        return cmd_optimize(args)
    else:
        console.print(f"[cyan]Config written to {tmp_config}. Run:[/cyan]")
        console.print(f"  [cyan]mutalambda optimize my_script.py --config {tmp_config}[/cyan]")
        return True


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="mutalambda",
        description=f"MutaLambda v{__version__} - Evolutionary Code Optimizer"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Optimize command
    optimize_parser = subparsers.add_parser("optimize", help="Optimize a source file")
    optimize_parser.add_argument("input", help="Input source file")
    optimize_parser.add_argument("--language", "-l", help="Language override")
    optimize_parser.add_argument("--config", "-c", help="Config file path")
    optimize_parser.set_defaults(func=cmd_optimize)
    
    # Analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze project")
    analyze_parser.add_argument("project_root", help="Project root directory")
    analyze_parser.add_argument("--output", "-o", help="Output report file")
    analyze_parser.add_argument("--max-depth", type=int, default=3, help="Max depth for analysis")
    analyze_parser.set_defaults(func=cmd_analyze)
    
    # Explain command
    explain_parser = subparsers.add_parser("explain", help="Explain optimization")
    explain_parser.add_argument("original", help="Original source file")
    explain_parser.add_argument("optimized", help="Optimized source file")
    explain_parser.add_argument("--type", "-t", required=True, help="Optimization type")
    explain_parser.add_argument("--function", "-f", required=True, help="Function name")
    explain_parser.add_argument("--fitness", required=True, help="Fitness results as JSON")
    explain_parser.set_defaults(func=cmd_explain)
    
    # CI command
    ci_parser = subparsers.add_parser("ci", help="Run CI analysis")
    ci_parser.add_argument("--repo-path", default=".", help="Repository path")
    ci_parser.add_argument("--output", "-o", help="Output file")
    ci_parser.set_defaults(func=cmd_ci)
    
    # Register baseline command
    baseline_parser = subparsers.add_parser("register-baseline", help="Register performance baseline")
    baseline_parser.add_argument("--file", "-f", required=True, help="Source file")
    baseline_parser.add_argument("--function", required=True, help="Function name")
    baseline_parser.add_argument("--language", "-l", required=True, help="Language")
    baseline_parser.add_argument("--fitness", required=True, help="Fitness metrics as JSON")
    baseline_parser.add_argument("--code", help="Source code file")
    baseline_parser.add_argument("--commit", help="Git commit hash")
    baseline_parser.add_argument("--branch", default="main", help="Branch name")
    baseline_parser.set_defaults(func=cmd_register_baseline)
    
    # ── UX commands (Fase 1-2) ────────────────────────────────────────────────
    
    # init command (wizard)
    init_parser = subparsers.add_parser(
        "init",
        help="Create optimized config.yaml with interactive wizard"
    )
    init_parser.add_argument("--output", "-o", default="config.yaml",
                             help="Output config path (default: config.yaml)")
    init_parser.set_defaults(func=cmd_init)
    
    # doctor command
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Diagnose config issues and offer fixes"
    )
    doctor_parser.add_argument("--config", "-c", default="config.yaml",
                               help="Config file to diagnose (default: config.yaml)")
    doctor_parser.add_argument("--fix", action="store_true",
                               help="Apply automatic fixes")
    doctor_parser.set_defaults(func=cmd_doctor)
    
    # recommend command
    recommend_parser = subparsers.add_parser(
        "recommend",
        help="Analyze code and recommend optimal configuration"
    )
    recommend_parser.add_argument("file", help="Python source file to analyze")
    recommend_parser.add_argument("--apply", action="store_true",
                                  help="Auto-generate recommended config")
    recommend_parser.add_argument("--output", "-o", default=None,
                                  help="Output config path (default: config.<preset>.yaml)")
    recommend_parser.set_defaults(func=cmd_recommend)
    
    # dashboard command
    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help="Launch web dashboard to inspect runs"
    )
    dashboard_parser.add_argument("--text", action="store_true",
                                  help="Show text-only dashboard (no browser)")
    dashboard_parser.add_argument("--run-id", help="Specific run to inspect")
    dashboard_parser.set_defaults(func=cmd_dashboard)

    # explain-run command (explain a completed evolution run)
    explain_run_parser = subparsers.add_parser(
        "explain-run",
        help="Explain the decisions made during an evolution run"
    )
    explain_run_parser.add_argument("run_dir", help="Run directory (e.g. checkpoints/run_xxx)")
    explain_run_parser.add_argument("--full", action="store_true",
                                    help="Include full best solution code")
    explain_run_parser.set_defaults(func=cmd_explain_run)

    # compare command
    compare_parser = subparsers.add_parser(
        "compare",
        help="Compare original, optimized, and baseline solutions"
    )
    compare_parser.add_argument("original", help="Original source file")
    compare_parser.add_argument("optimized", help="Optimized source file")
    compare_parser.add_argument("--baseline", help="Optional baseline file for diffing")
    compare_parser.set_defaults(func=cmd_compare)

    # tutorial command
    tutorial_parser = subparsers.add_parser(
        "tutorial",
        help="Interactive tutorial for first-time users"
    )
    tutorial_parser.set_defaults(func=cmd_tutorial)

    # Preset shortcut commands
    quick_parser = subparsers.add_parser("quick", help="Fast feedback run (quick preset)")
    quick_parser.add_argument("file", help="Python source file to optimize")
    quick_parser.set_defaults(func=cmd_quick)

    production_parser = subparsers.add_parser("production", help="Production-quality run (balanced preset)")
    production_parser.add_argument("file", help="Python source file to optimize")
    production_parser.set_defaults(func=cmd_production)

    scientific_parser = subparsers.add_parser("scientific", help="Scientific code run (SVL + invariants)")
    scientific_parser.add_argument("file", help="Python source file to optimize")
    scientific_parser.set_defaults(func=cmd_scientific)

    numpy_parser = subparsers.add_parser("numpy", help="NumPy-optimized run")
    numpy_parser.add_argument("file", help="Python source file to optimize")
    numpy_parser.set_defaults(func=cmd_numpy)
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    
    args.func(args)


if __name__ == "__main__":
    main()
