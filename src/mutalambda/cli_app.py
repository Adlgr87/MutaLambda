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
    python cli.py checkpoints
    python cli.py migrate-checkpoints checkpoints/run_xxx --format msgpack
    python cli.py interactive
"""

import sys
from pathlib import Path

# Prefer installed package (pip install -e .). Fallback for running from a raw clone.
try:
    import mutalambda.muta_lambda as muta_lambda  # noqa: F401
except ImportError:  # pragma: no cover - dev checkout without install
    _project_root = str(Path(__file__).resolve().parent)
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)

import click
from rich.console import Console

from mutalambda.cli.main import MutaLambdaCLI, InteractiveREPL

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
# GENERATE MUTATOR
# ============================================================================
@cli.command("generate-mutator")
@click.argument("instruction", type=str)
@click.option('--lang', type=str, default='python', help='Target language for mutator intent')
@click.option('--name', type=str, default=None, help='Output mutator file name (without .py)')
@click.option('--dry-run', is_flag=True, help='Print generated code instead of writing file')
@click.pass_context
def generate_mutator_cmd(ctx, instruction, lang, name, dry_run):
    """🤖 Generate CoreUAST mutator code from natural language."""
    cli_instance = ctx.obj['cli']
    success = cli_instance.generate_mutator(
        instruction=instruction,
        lang=lang,
        name=name,
        dry_run=dry_run,
    )
    sys.exit(0 if success else 1)


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
# MIGRATE-CHECKPOINTS
# ============================================================================
@cli.command("migrate-checkpoints")
@click.argument("paths", nargs=-1, type=click.Path(exists=True), required=True)
@click.option('--format', '-f', 'format_mode', type=click.Choice(['auto', 'json', 'msgpack'], case_sensitive=False), default='msgpack', help='Formato de destino')
@click.option('--overwrite', is_flag=True, help='Sobrescribir si ya existe el destino')
@click.pass_context
def migrate_checkpoints(ctx, paths, format_mode, overwrite):
    """🔄 Migrar checkpoints JSON a msgpack (o viceversa)."""
    from mutalambda.checkpoint_manager import load_checkpoint, _serialise_checkpoint
    import zlib
    import msgpack

    for path in paths:
        p = Path(path)
        if p.is_dir():
            # Directory: migrate each full checkpoint inside
            json_file = p / "checkpoint.json"
            msgpack_file = p / "checkpoint.msgpack"
            if msgpack_file.exists() and not overwrite:
                console.print(f"[dim]↷ {path}: ya es msgpack, salta[/dim]")
                continue
            src = json_file if json_file.exists() else None
            dst = msgpack_file if format_mode == "msgpack" else (p / "checkpoint.json")
        else:
            src = p
            if format_mode == "auto":
                suffix = ".msgpack" if p.suffix == ".json" else ".json"
            else:
                suffix = f".{format_mode}"
            dst = p.with_suffix(suffix)

        if src is None or not src.exists():
            console.print(f"[yellow]⚠ {path}: sin checkpoint.json[/yellow]")
            continue

        try:
            cp = load_checkpoint(src)
            serialised = _serialise_checkpoint(cp)

            if format_mode == "msgpack":
                packed = msgpack.packb(serialised, use_bin_type=True)
                compressed = zlib.compress(packed, level=6)
                dst.write_bytes(compressed)
                console.print(f"[green]✓ {src} → msgpack ({len(compressed)} bytes)[/green]")
            else:
                dst.write_text(json.dumps(serialised, indent=2, ensure_ascii=False), encoding="utf-8")
                console.print(f"[green]✓ {src} → json[/green]")
        except Exception as e:
            console.print(f"[red]✗ {path}: {e}[/red]")


# ============================================================================
# INIT (Wizard Interactivo)
# ============================================================================
@cli.command()
@click.option('--output', '-o', type=click.Path(), default=None, help='Archivo de salida (default: config.yaml)')
@click.pass_context
def init(ctx, output):
    """✨ Asistente interactivo para crear configuración optimizada."""
    from mutalambda.cli.config_manager import ConfigManager
    from rich.prompt import Prompt, Confirm
    from rich.panel import Panel

    cm = ConfigManager()
    console.print(Panel(
        "[bold cyan]MutaLambda Configuration Wizard[/bold cyan]\n"
        "Crearé una configuración optimizada para tu código.",
        title="✨ Bienvenido"
    ))

    console.print("\n[bold]1. ¿Qué tipo de código vas a optimizar?[/bold]")
    code_type = Prompt.ask(
        "Selecciona",
        choices=["1", "2", "3", "4"],
        default="3",
        show_choices=True,
    )
    type_labels = {
        "1": "NumPy/Data Science",
        "2": "Código Científico",
        "3": "Aplicación General",
        "4": "Código Legacy",
    }
    console.print(f"  → {type_labels[code_type]} seleccionado")

    console.print("\n[bold]2. ¿Qué tan agresiva debe ser la optimización?[/bold]")
    aggressiveness = Prompt.ask(
        "Selecciona",
        choices=["1", "2", "3"],
        default="2",
        show_choices=True,
    )
    console.print(f"  → {['Conservador', 'Balanceado', 'Agresivo'][int(aggressiveness)-1]} seleccionado")

    preset_map = {
        ("1", "1"): "numpy", ("1", "2"): "numpy", ("1", "3"): "numpy",
        ("2", "1"): "scientific", ("2", "2"): "scientific", ("2", "3"): "research",
        ("3", "1"): "quick", ("3", "2"): "production", ("3", "3"): "advanced",
        ("4", "1"): "quick", ("4", "2"): "production", ("4", "3"): "production",
    }
    preset = preset_map.get((code_type, aggressiveness), "basic")
    console.print(f"\n[bold green]✓ Configuración recomendada: preset '{preset}'[/bold green]")

    if Confirm.ask("¿Crear config.yaml con este preset?", default=True):
        out = output or "config.yaml"
        if cm.create_from_template(preset, out):
            console.print(f"\n[green]✓ Configuración guardada en {out}[/green]")
        else:
            console.print("[red]✗ Error creando configuración[/red]")
            sys.exit(1)


# ============================================================================
# DOCTOR --FIX  (enhanced)
# ============================================================================
@cli.command()
@click.option('--config', '-c', type=click.Path(exists=True), help='Opcional: configurar YAML para diagnosticar')
@click.option('--fix', is_flag=True, help='Aplicar correcciones automáticas')
@click.pass_context
def doctor(ctx, config, fix):
    """🩺 Validar entorno, backend LLM, runner y dependencias, con opción --fix."""
    import importlib
    import shutil
    from mutalambda.cli.config_manager import ConfigManager
    from rich.panel import Panel
    from rich.table import Table

    ok = True
    console.print("[bold]MutaLambda doctor[/bold]\n")

    # --- Environment checks (unchanged) ---
    console.print(f"Python: {sys.version.split()[0]}")
    try:
        import mutalambda.muta_lambda as muta_lambda  # noqa
        from mutalambda.sandbox import SandboxEvaluator  # noqa
        from mutalambda.runners import create_runner  # noqa
        console.print("[green]✓ core imports[/green]")
    except Exception as e:
        console.print(f"[red]✗ core imports: {e}[/red]")
        ok = False

    for name, mod in [("click","click"),("rich","rich"),("numpy","numpy"),
                      ("pydantic","pydantic"),("yaml","yaml"),
                      ("faiss","faiss"),("sentence-transformers","sentence_transformers")]:
        try:
            importlib.import_module(mod)
            console.print(f"[green]✓ {name}[/green]")
        except Exception:
            console.print(f"[dim]· {name} (opcional)[/dim]")

    has_container = False
    for eng in ("docker", "podman"):
        path = shutil.which(eng)
        if path:
            console.print(f"[green]✓ {eng} en {path}[/green]")
            has_container = True
        else:
            console.print(f"[dim]· {eng} no encontrado[/dim]")
    if has_container:
        console.print("[green]✓ runner de contenedor disponible[/green]")
    else:
        console.print("[yellow]! sin motor de contenedor — solo subprocess[/yellow]")

    # --- Config diagnostics ---
    if config:
        cm = ConfigManager()
        cfg = cm.load(config)
        if cfg is None:
            console.print(f"[red]✗ No se pudo cargar {config}[/red]")
            sys.exit(1)

        issues = cm.diagnostic(cfg)
        if not issues:
            console.print(Panel("[green]✓ Configuración válida — sin problemas.[/green]"))
        else:
            table = Table(title="Diagnóstico de configuración", show_lines=True)
            table.add_column("#", style="dim")
            table.add_column("Severidad", style="bold")
            table.add_column("Problema")
            table.add_column("Solución sugerida", style="cyan")
            for i, issue in enumerate(issues, 1):
                sev = issue.get("severity", "warning")
                color = {"error":"red","warning":"yellow","info":"blue"}.get(sev, "yellow")
                table.add_row(str(i), f"[{color}]{sev}[/{color}]", issue["message"], issue.get("fix_suggestion",""))
            console.print(table)

            if fix:
                applied = 0
                for issue in issues:
                    if "fix_key" in issue and cm.apply_fix(cfg, issue):
                        applied += 1
                cm.save(cfg, config)
                console.print(f"\n[green]✓ {applied} corrección(es) aplicadas en {config}[/green]")
                ok = ok and True

    sys.exit(0 if ok else 1)


# ============================================================================
# MODO PRESETS  (quick/production/scientific/numpy)
# ============================================================================
def _run_with_preset(ctx, preset_name, file_arg):
    from mutalambda.cli.config_manager import ConfigManager
    import yaml
    cm = ConfigManager()
    preset_path = Path("presets") / f"{preset_name}.yaml"
    if not preset_path.exists():
        console.print(f"[red]✗ Preset no encontrado: {preset_path}[/red]")
        sys.exit(1)
    cfg = yaml.safe_load(preset_path.read_text())
    out = Path(f"config.{preset_name}.yaml")
    out.write_text(yaml.dump(cfg, default_flow_style=False, sort_keys=False))
    console.print(f"[green]✓ Preset '{preset_name}' cargado → {out}[/green]")
    if file_arg:
        console.print(f"[cyan]Ejecutando evolve con {file_arg}...[/cyan]")
        cli_inst = ctx.obj['cli']
        success = cli_inst.run_evolution(config_path=str(out), verbose=False, animation='none', source=file_arg)
        sys.exit(0 if success else 1)
    else:
        console.print(f"  Ejecuta: [cyan]mutalambda evolve --config {out.name} my_script.py[/cyan]")


@cli.command(name="quick")
@click.argument("file", required=False)
@click.pass_context
def quick(ctx, file):
    """⚡ Ejecutar con preset 'quick' (feedback rápido)."""
    _run_with_preset(ctx, "quick", file)


@cli.command(name="production")
@click.argument("file", required=False)
@click.pass_context
def production(ctx, file):
    """🏭 Ejecutar con preset 'production' (balanceado)."""
    _run_with_preset(ctx, "production", file)


@cli.command(name="scientific")
@click.argument("file", required=False)
@click.pass_context
def scientific(ctx, file):
    """🧪 Ejecutar con preset 'scientific' (SVL + invariantes)."""
    _run_with_preset(ctx, "scientific", file)


@cli.command(name="numpy")
@click.argument("file", required=False)
@click.pass_context
def numpy_mode(ctx, file):
    """🔢 Ejecutar con preset 'numpy' (optimización NumPy)."""
    _run_with_preset(ctx, "numpy", file)


# ============================================================================
# RECOMMEND
# ============================================================================
@cli.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--apply/--no-apply", default=False, help="Generar config recomendado")
@click.option("--output", "-o", type=click.Path(), default=None)
@click.pass_context
def recommend(ctx, file, apply, output):
    """📋 Analizar código y recomendar preset + configuración óptima."""
    from mutalambda.cli.config_manager import ConfigManager
    import yaml
    cm = ConfigManager()
    src = Path(file).read_text(encoding="utf-8")
    code_type = _detect_code_type_cli(src)
    lines = src.count("\n")

    if "numpy" in code_type or "ml" in code_type:
        preset, reason = "numpy", "Código numérico/ML"
    elif lines > 200:
        preset, reason = "scientific", "Código extenso (>200 líneas)"
    elif lines < 50:
        preset, reason = "quick", "Código conciso (<50 líneas)"
    else:
        preset, reason = "production", "Código general"

    console.print(f"[bold]Recomendación:[/bold] [green]preset '{preset}'[/green]")
    console.print(f"  Razón: {reason}")

    # read actual preset file for accurate key values
    preset_path = Path("presets") / f"{preset}.yaml"
    if preset_path.exists():
        pdata = yaml.safe_load(preset_path.read_text())
    else:
        pdata = cm.templates.get(preset, {})
    ev = pdata.get("evolution", {})
    sb = pdata.get("sandbox", {})
    console.print(f"  Generations: {ev.get('generations', '?')}")
    console.print(f"  Islands: {ev.get('num_islands', '?')}")
    console.print(f"  Population: {ev.get('population_size', '?')}")
    console.print(f"  Timeout: {sb.get('timeout_sec', '?')}s")

    if apply:
        out = output or f"config.{preset}.yaml"
        if preset_path.exists():
            cfg = yaml.safe_load(preset_path.read_text())
            Path(out).write_text(yaml.dump(cfg, default_flow_style=False, sort_keys=False))
        else:
            cm.create_from_template(preset, out)
        console.print(f"\n[green]✓ Guardado en {out}[/green]")


def _detect_code_type_cli(source: str) -> str:
    ind = {
        'numpy': 'np.' in source or 'numpy' in source,
        'pandas': 'pd.' in source or 'pandas' in source,
        'scipy': 'scipy' in source,
        'ml': 'sklearn' in source or 'torch' in source or 'tensorflow' in source,
    }
    m = [n for n, p in ind.items() if p]
    return ', '.join(m) if m else 'general'


# ============================================================================
# DASHBOARD (text fallback)
# ============================================================================
@cli.command()
@click.option("--text/--no-text", default=False, help="Ver resumen en texto (sin Streamlit)")
@click.argument("run_id", required=False)
@click.pass_context
def dashboard(ctx, text, run_id):
    """📊 Monitorear ejecuciones (texto o Streamlit)."""
    if not text:
        try:
            import streamlit  # noqa
        except ImportError:
            console.print("[yellow]⚠ Streamlit no instalado.[/yellow]")
            console.print("  [cyan]pip install streamlit[/cyan] o usa [cyan]--text[/cyan]")
            sys.exit(0)
        from pathlib import Path as P
        dash_file = P(__file__).parent / "dashboard_run.py"
        if dash_file.exists():
            import subprocess
            console.print("[cyan]🚀 Abriendo http://localhost:8501 ...[/cyan]")
            subprocess.run(["streamlit", "run", str(dash_file)])
            sys.exit(0)
        else:
            console.print("[yellow]streamlit disponible pero dashboard_run.py no encontrado[/yellow]")
            sys.exit(0)

    # --- text mode ---
    from json import loads
    checkpoints_dir = Path("checkpoints")
    if not checkpoints_dir.exists():
        console.print("[dim]No hay directorio de checkpoints[/dim]")
        sys.exit(0)
    runs = sorted(
        [d for d in checkpoints_dir.iterdir() if d.is_dir() and d.name.startswith("run_")],
        key=lambda d: d.stat().st_mtime, reverse=True)[:10]
    if not runs:
        console.print("[dim]No hay runs[/dim]")
        sys.exit(0)
    from rich.table import Table
    t = Table(title="Resumen de Ejecuciones")
    t.add_column("#", style="dim")
    t.add_column("Run ID", style="cyan")
    t.add_column("Gen", justify="right")
    t.add_column("Best", justify="right")
    t.add_column("Time", justify="right")
    for i, d in enumerate(runs, 1):
        mp = d / "run_manifest.json"
        if mp.exists():
            m = loads(mp.read_text())
            t.add_row(str(i), d.name[4:12],
                      str(m.get("generation_completed", 0)),
                      f"{m.get('best_score',0):.4f}",
                      f"{m.get('total_time_sec',0):.1f}")
        else:
            t.add_row(str(i), d.name[:8], "?","?","?")
    from rich.console import Console
    Console().print(t)


# ============================================================================
# COMPARE
# ============================================================================
@cli.command()
@click.argument("original", type=click.Path(exists=True))
@click.argument("optimized", type=click.Path(exists=True))
@click.option("--baseline", type=click.Path(exists=True), default=None)
@click.pass_context
def compare(ctx, original, optimized, baseline):
    """⚖️ Comparar soluciones original vs optimizada."""
    import difflib
    from rich.panel import Panel
    from rich.table import Table
    o = Path(original).read_text(encoding="utf-8")
    p = Path(optimized).read_text(encoding="utf-8")
    console.print(Panel("[bold cyan]⚖️ Solution Comparison[/bold cyan]"))
    ft = Table(show_header=False, box=None)
    ft.add_column("File", style="cyan")
    ft.add_column("Líneas", justify="right")
    ft.add_row(str(original), str(o.count("\n")))
    ft.add_row(str(optimized), str(p.count("\n")))
    if baseline:
        b = Path(baseline).read_text(encoding="utf-8")
        ft.add_row(str(baseline), str(b.count("\n")))
    console.print(ft)
    diff = list(difflib.unified_diff(o.splitlines(keepends=True), p.splitlines(keepends=True),
                                     fromfile=str(original), tofile=str(optimized), n=3))
    additions = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removals = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    st = Table(title="Stats")
    st.add_column("Métrica", style="cyan")
    st.add_column("Valor", justify="right")
    st.add_row("Líneas agregadas", str(additions))
    st.add_row("Líneas eliminadas", str(removals))
    st.add_row("Neto", str(additions - removals))
    console.print(st)


# ============================================================================
# EXPLAIN-RUN
# ============================================================================
@cli.command()
@click.argument("run_dir", type=click.Path(exists=True))
@click.option("--full", is_flag=True)
@click.pass_context
def explain_run(ctx, run_dir, full):
    """📖 Explicar decisiones de una corrida completada."""
    from json import loads
    rd = Path(run_dir)
    manifest = loads((rd / "run_manifest.json").read_text()) if (rd/"run_manifest.json").exists() else {}
    if not manifest:
        console.print(f"[red]✗ run_manifest.json no encontrado en {run_dir}[/red]")
        sys.exit(1)
    from rich.panel import Panel
    from rich.table import Table
    console.print(Panel("[bold cyan]📖 Explicando corrida[/bold cyan]"))
    it = Table(box=None, show_header=False)
    it.add_column("Key", style="dim")
    it.add_column("Value")
    it.add_row("Run ID", manifest.get("run_id","—"))
    it.add_row("Task", manifest.get("task","—"))
    it.add_row("Generaciones", str(manifest.get("generation_completed",0)))
    console.print(it)
    bs = manifest.get("best_score", 0)
    console.print(f"\n[cyan]🎯 Best Score:[/cyan] [bold]{bs:.4f}[/bold]")
    fh = rd / "fitness_history.json"
    if fh.exists():
        h = loads(fh.read_text()).get("global_best_history", [])
        if h:
            console.print(f"\n[bold]📈 Fitness Evolution:[/bold]")
            console.print(f"  Generaciones: {len(h)}")
            console.print(f"  Inicio: {h[0]:.4f}")
            console.print(f"  Final:  {h[-1]:.4f}")
            pct = ((h[-1]-h[0])/abs(h[0])*100) if h[0] else 0
            console.print(f"  Mejora: {pct:.1f}%")
    if full:
        bp = rd/"best_solution.py"
        if bp.exists():
            from rich.console import Console
            console.print("\n[bold]Mejor solución:[/bold]")
            console.print(bp.read_text(encoding="utf-8"))


# ============================================================================
# EXAMPLES + TUTORIAL
# ============================================================================
@cli.command(name="examples")
@click.pass_context
def examples(ctx):
    """📁 Listar ejemplos listos para usar."""
    from rich.table import Table
    t = Table(title="Ejemplos MutaLambda")
    t.add_column("Archivo", style="cyan")
    t.add_column("Tipo")
    t.add_column("Tests")
    ex_dir = Path("examples")
    if not ex_dir.exists():
        console.print("[dim]No hay directorio examples/[/dim]")
        sys.exit(0)
    for py in sorted(ex_dir.glob("*.py")):
        tests = py.with_name(py.stem + "_tests.json")
        t.add_row(str(py), _guess_type(py.read_text(encoding="utf-8")[:200]),
                  "✓" if tests.exists() else "—")
    console.print(t)


def _guess_type(src: str) -> str:
    if "np." in src or "numpy" in src: return "NumPy"
    if "scipy" in src: return "Científico"
    return "General"


@cli.command()
@click.pass_context
def tutorial(ctx):
    """🐣 Tutorial interactivo paso a paso."""
    from rich.panel import Panel
    console.print(Panel("""
[bold cyan]🐣 Tutorial MutaLambda[/bold cyan]

Pasos esenciales:
""", title="Tutorial"))
    steps = [
        ("1. Configuración", "Crea config.yaml con wizard:", "  mutalambda init"),
        ("2. Analizar", "Recomiendo preset para tu código:", "  mutalambda recommend my_script.py"),
        ("3. Optimizar", "Ejecuta con preset production:", "  mutalambda production my_script.py"),
        ("4. Monitorear", "Ver resumen en texto:", "  mutalambda dashboard --text"),
        ("5. Diagnosticar", "Verifica y corrige configuración:", "  mutalambda doctor --fix"),
        ("6. Explicar", "Entiende resultados de una corrida:", "  mutalambda explain-run checkpoints/run_xxx"),
    ]
    for name, desc, cmd in steps:
        console.print(f"\n[bold]{name}[/bold]")
        console.print(f"  [dim]{desc}[/dim]")
        console.print(f"  [cyan]{cmd}[/cyan]")
    console.print(f"\n[bold yellow]✨ Quick Start:[/bold yellow]")
    console.print("  [cyan]mutalambda init && mutalambda production examples/target.py[/cyan]")


if __name__ == '__main__':
    cli()
