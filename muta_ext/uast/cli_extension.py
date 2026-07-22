#!/usr/bin/env python3
"""CLI extension for multi-language UAST evolution."""
import click

from muta_ext.uast.handlers.rust_handler import RustHandler
from muta_ext.uast.handlers.cpp_handler import CppHandler
from muta_ext.uast.handlers.python_handler import PythonHandler


@click.group("uast")
def uast_group():
    """Multi-language UAST evolution commands."""
    pass


@uast_group.command("run")
@click.option("--config", required=True, help="Path to language config YAML")
@click.option("--code", required=True, help="Path to source code file")
@click.option("--tests", default=None, help="Path to test file")
@click.option("--generations", default=50, help="Number of generations")
@click.option("--output", default=None, help="Output path for best result")
def uast_run(config, code, tests, generations, output):
    """Run UAST evolution for a specific language."""
    # Load config (simplified - just read the file)
    try:
        with open(config) as f:
            content = f.read()
    except Exception as e:
        click.echo(f"Error loading config: {e}")
        return
    
    # Load source code
    try:
        with open(code) as f:
            source = f.read()
    except Exception as e:
        click.echo(f"Error loading code: {e}")
        return
    
    # Determine handler from config
    if "rust" in content:
        handler = RustHandler()
    elif "cpp" in content:
        handler = CppHandler()
    else:
        handler = PythonHandler()
    
    # Create adapter and run
    from muta_ext.uast.evolution_adapter import UASTEvolutionAdapter
    adapter = UASTEvolutionAdapter(handler=handler)
    
    results = adapter.run(source_code=source, test_code="", generations=generations, population_size=8)
    
    click.echo(f"Generations completed: {results['generations_completed']}")
    click.echo(f"Valid candidates: {results['valid_candidates']}")


@uast_group.command("roundtrip")
@click.option("--lang", required=True, type=click.Choice(["python", "rust", "cpp"]))
@click.option("--code", required=True, help="Path to source code file")
def uast_roundtrip(lang, code):
    """Parse → CoreUAST → Emit roundtrip test."""
    with open(code) as f:
        source = f.read()
    
    if lang == "python":
        handler = PythonHandler()
    elif lang == "rust":
        handler = RustHandler()
    else:
        handler = CppHandler()
    
    result = handler.roundtrip(source)
    click.echo(result)


@uast_group.command("validate")
@click.option("--lang", required=True, type=click.Choice(["python", "rust", "cpp"]))
@click.option("--code", required=True, help="Path to source code file")
def uast_validate(lang, code):
    """Validate syntax for a specific language."""
    with open(code) as f:
        source = f.read()
    
    if lang == "python":
        handler = PythonHandler()
    elif lang == "rust":
        handler = RustHandler()
    else:
        handler = CppHandler()
    
    ok, err = handler.validate_syntax(source)
    if ok:
        click.echo("Syntax valid")
    else:
        click.echo(f"Syntax error: {err}")