#!/usr/bin/env python3
"""Entry point for MutaLambda CLI."""
import argparse
import json
import sys
from pathlib import Path

from muta_ext import (
    MutaLambdaOptimizer,
    ProjectAnalyzer,
    ExplainableOptimizer,
    create_ci_pipeline,
    __version__
)


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
    from muta_ext.ci_integration import register_baseline_from_ci
    
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
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    
    args.func(args)


if __name__ == "__main__":
    main()
