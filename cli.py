#!/usr/bin/env python3
"""
MutaLambda CLI — Interfaz de línea de comandos para evolución de código.

Uso:
    python cli.py run --config config.yaml --generations 50 --animation retro
    python cli.py resume --checkpoint path/to/checkpoint.json
    python cli.py config create --output config.yaml --template basic
    python cli.py config validate --path config.yaml
    python cli.py stats
    python cli.py evaluate --results results.json
    python cli.py mutate --target function.py --type prompt --strategy adaptive
    python cli.py interactive
    python cli.py checkpoints
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path for core imports
_project_root = str(Path(__file__).resolve().parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import click
from rich.console import Console

from cli.main import MutaLambdaCLI, InteractiveREPL

console = Console()


@click.group()
@click.version_option(version="3.1.0", prog_name="MutaLambda")
@click.pass_context
def cli(ctx):
    """🧬 MutaLambda — Evolución genética de código Python."""
    ctx.ensure_object(dict)
    ctx.obj['cli'] = MutaLambdaCLI()


# ============================================================================
# RUN
# ============================================================================
@cli.command()
@click.option('--config', '-c', type=click.Path(exists=True), help='Archivo de configuración YAML')
@click.option('--generations', '-g', type=int, default=50, help='Número de generaciones')
@click.option('--animation', '-a', type=click.Choice(['retro', 'minimal', 'none']), default='retro', help='Estilo de animación')
@click.option('--verbose', '-v', is_flag=True, help='Output detallado')
@click.option('--source', type=click.Path(exists=True), help='Código semilla a evolucionar')
@click.option('--tests', type=click.Path(exists=True), help='Casos de prueba JSON declarativos')
@click.option('--task', type=str, default=None, help='Descripción de la tarea evolutiva')
@click.option('--allow-untested', is_flag=True, help='Permitir corridas sin tests (solo desarrollo)')
@click.pass_context
def run(ctx, config, generations, animation, verbose, source, tests, task, allow_untested):
    """🚀 Ejecutar corrida evolutiva completa."""
    cli_instance = ctx.obj['cli']
    success = cli_instance.run_evolution(
        config_path=config,
        generations=generations,
        animation=animation,
        verbose=verbose,
        source=source,
        tests=tests,
        task=task,
        allow_untested=allow_untested,
    )
    sys.exit(0 if success else 1)


# ============================================================================
# RESUME
# ============================================================================
@cli.command()
@click.option('--checkpoint', '-p', type=click.Path(exists=True), required=True, help='Archivo de checkpoint')
@click.option('--additional-gens', '-g', type=int, default=50, help='Generaciones adicionales')
@click.option('--animation', '-a', type=click.Choice(['retro', 'minimal', 'none']), default='retro', help='Estilo de animación')
@click.pass_context
def resume(ctx, checkpoint, additional_gens, animation):
    """🔄 Reanudar desde checkpoint."""
    cli_instance = ctx.obj['cli']
    success = cli_instance.resume_evolution(
        checkpoint_path=checkpoint,
        additional_gens=additional_gens,
        animation=animation,
    )
    sys.exit(0 if success else 1)


# ============================================================================
# CONFIG
# ============================================================================
@cli.group()
def config():
    """⚙️  Gestionar configuraciones."""
    pass


@config.command('create')
@click.option('--output', '-o', type=click.Path(), required=True, help='Archivo de salida')
@click.option('--template', '-t', type=click.Choice(['basic', 'advanced', 'research']), default='basic', help='Plantilla base')
@click.pass_context
def config_create(ctx, output, template):
    """Crear configuración desde plantilla."""
    cli_instance = ctx.obj['cli']
    success = cli_instance.create_config(output_path=output, template=template)
    sys.exit(0 if success else 1)


@config.command('validate')
@click.option('--path', '-p', type=click.Path(exists=True), required=True, help='Archivo a validar')
@click.pass_context
def config_validate(ctx, path):
    """Validar archivo de configuración."""
    cli_instance = ctx.obj['cli']
    success = cli_instance.validate_config(config_path=path)
    sys.exit(0 if success else 1)


@config.command('show')
@click.option('--path', '-p', type=click.Path(exists=True), required=True, help='Archivo a mostrar')
@click.pass_context
def config_show(ctx, path):
    """Mostrar resumen de configuración."""
    cli_instance = ctx.obj['cli']
    cli_instance.config_manager.display_summary_from_file(path)


# ============================================================================
# STATS
# ============================================================================
@cli.command()
@click.pass_context
def stats(ctx):
    """📊 Mostrar estadísticas de ejecuciones anteriores."""
    cli_instance = ctx.obj['cli']
    cli_instance.show_stats()


# ============================================================================
# EVALUATE
# ============================================================================
@cli.command()
@click.option('--results', '-r', type=click.Path(exists=True), help='Archivo de resultados')
@click.pass_context
def evaluate(ctx, results):
    """🔬 Evaluar y resumir resultados."""
    cli_instance = ctx.obj['cli']
    cli_instance.evaluate_results(results_path=results)


# ============================================================================
# MUTATE
# ============================================================================
@cli.group()
def mutate():
    """🧬 Operaciones de mutación."""
    pass


@mutate.command('prompt')
@click.option('--target', '-t', type=str, required=True, help='Prompt o función a mutar')
@click.option('--strategy', '-s', type=click.Choice(['adaptive', 'creative', 'conservative']), default='adaptive', help='Estrategia')
@click.pass_context
def mutate_prompt(ctx, target, strategy):
    """Mutar prompts de evolución."""
    cli_instance = ctx.obj['cli']
    cli_instance.run_mutation(target=target, mutation_type='prompt', strategy=strategy)


@mutate.command('operators')
@click.option('--target', '-t', type=str, required=True, help='Operador a mutar')
@click.option('--strategy', '-s', type=click.Choice(['weighted', 'uniform', 'adaptive']), default='adaptive', help='Distribución')
@click.pass_context
def mutate_operators(ctx, target, strategy):
    """Mutar operadores genéticos."""
    cli_instance = ctx.obj['cli']
    cli_instance.run_mutation(target=target, mutation_type='operators', strategy=strategy)


@mutate.command('hyperparams')
@click.option('--target', '-t', type=str, required=True, help='Hiperparámetro a mutar')
@click.option('--strategy', '-s', type=click.Choice(['grid', 'random', 'bayesian']), default='bayesian', help='Búsqueda')
@click.pass_context
def mutate_hyperparams(ctx, target, strategy):
    """Optimizar hiperparámetros."""
    cli_instance = ctx.obj['cli']
    cli_instance.run_mutation(target=target, mutation_type='hyperparams', strategy=strategy)


# ============================================================================
# INTERACTIVE
# ============================================================================
@cli.command()
@click.pass_context
def interactive(ctx):
    """🎮 Modo interactivo tipo REPL."""
    cli_instance = ctx.obj['cli']
    repl = InteractiveREPL(cli_instance)
    repl.start()


# ============================================================================
# CHECKPOINTS
# ============================================================================
@cli.command()
@click.option('--list', '-l', 'list_mode', is_flag=True, help='Listar checkpoints')
@click.option('--clean', '-c', is_flag=True, help='Limpiar checkpoints antiguos')
@click.option('--max-age', type=int, default=30, help='Edad máxima en días')
@click.pass_context
def checkpoints(ctx, list_mode, clean, max_age):
    """💾 Gestionar checkpoints."""
    cli_instance = ctx.obj['cli']

    if list_mode:
        chk_list = cli_instance.checkpoint_manager.list_checkpoints()
        if chk_list:
            cli_instance.checkpoint_manager.display_checkpoints(chk_list)
        else:
            console.print("[dim]No hay checkpoints.[/dim]")

    if clean:
        removed = cli_instance.checkpoint_manager.clean_old_checkpoints(max_age_days=max_age)
        console.print(f"[green]✓ {removed} checkpoints eliminados[/green]")

    if not list_mode and not clean:
        # Default: list
        chk_list = cli_instance.checkpoint_manager.list_checkpoints()
        if chk_list:
            cli_instance.checkpoint_manager.display_checkpoints(chk_list)
        else:
            console.print("[dim]No hay checkpoints. Ejecuta 'run' para crearlos.[/dim]")


# ============================================================================
# DOCTOR
# ============================================================================
@cli.command()
@click.option('--config', '-c', type=click.Path(exists=True), help='Config YAML opcional')
@click.pass_context
def doctor(ctx, config):
    """🩺 Validar entorno, backend LLM, runner y dependencias."""
    import importlib
    import shutil

    ok = True
    console.print("[bold]MutaLambda doctor[/bold]\n")

    # Python
    console.print(f"Python: {sys.version.split()[0]}")

    # Core imports
    try:
        import muta_lambda  # noqa: F401
        from sandbox import SandboxEvaluator  # noqa: F401
        from runners import create_runner  # noqa: F401
        console.print("[green]✓ core imports[/green]")
    except Exception as e:
        console.print(f"[red]✗ core imports: {e}[/red]")
        ok = False

    # Optional deps
    for name, mod in [
        ("click", "click"),
        ("rich", "rich"),
        ("numpy", "numpy"),
        ("pydantic", "pydantic"),
        ("yaml", "yaml"),
        ("faiss", "faiss"),
        ("sentence-transformers", "sentence_transformers"),
    ]:
        try:
            importlib.import_module(mod)
            console.print(f"[green]✓ {name}[/green]")
        except Exception:
            console.print(f"[yellow]· {name} missing (optional or install extras)[/yellow]")

    # Container engines
    for eng in ("docker", "podman"):
        path = shutil.which(eng)
        if path:
            console.print(f"[green]✓ {eng} at {path}[/green]")
        else:
            console.print(f"[dim]· {eng} not found (container runner unavailable)[/dim]")

    # LLM backend probe (Ollama default)
    backend = "ollama"
    model = "llama3.2:3b"
    if config:
        try:
            from config_loader import load_yaml

            cfg = load_yaml(config)
            backend = cfg.get("llm", {}).get("backend", backend)
            model = cfg.get("llm", {}).get("model", model)
            privacy = cfg.get("privacy", {})
            if privacy.get("allow_external_llm") is False and backend not in ("ollama", "local"):
                console.print(
                    f"[yellow]! privacy.allow_external_llm=false but llm.backend={backend}[/yellow]"
                )
        except Exception as e:
            console.print(f"[yellow]! config load warning: {e}[/yellow]")

    console.print(f"LLM backend: {backend} / model: {model}")
    if backend == "ollama":
        try:
            import requests

            url = "http://127.0.0.1:11434/api/tags"
            r = requests.get(url, timeout=2)
            if r.ok:
                console.print("[green]✓ ollama reachable[/green]")
            else:
                console.print(f"[yellow]! ollama HTTP {r.status_code}[/yellow]")
                ok = False
        except Exception as e:
            console.print(f"[yellow]! ollama not reachable: {e}[/yellow]")
            ok = False

    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    cli()
