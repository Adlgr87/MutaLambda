"""
Configuration manager for MutaLambda CLI

Handles loading, saving, validating, and creating configuration files.
"""

import yaml
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from rich.console import Console
from rich.table import Table

from cli.animator import RetroAnimator


class ConfigManager:
    """Manages configuration files for MutaLambda"""

    def __init__(self, animator: Optional[RetroAnimator] = None):
        self.animator = animator or RetroAnimator()
        self.console = Console()

        # Default templates
        self.templates = {
            'basic': {
                'evolution': {
                    'generations': 50,
                    'num_islands': 4,
                    'population_size': 8,
                    'top_k': 3,
                },
                'migration': {
                    'interval': 10,
                    'migrants_per_island': 2,
                    'topology': 'ring',
                },
                'mutation': {
                    'rate': 0.1,
                    'crossover_rate': 0.7,
                },
                'checkpoint': {
                    'enabled': True,
                    'interval': 10,
                    'directory': 'checkpoints',
                },
                'early_stop': {
                    'enabled': True,
                    'patience': 15,
                    'delta': 0.001,
                }
            },

            'advanced': {
                'evolution': {
                    'generations': 100,
                    'num_islands': 8,
                    'population_size': 16,
                    'top_k': 5,
                },
                'migration': {
                    'interval': 5,
                    'migrants_per_island': 3,
                    'topology': 'fully_connected',
                },
                'mutation': {
                    'rate': 0.15,
                    'crossover_rate': 0.8,
                    'strategies': ['random', 'guided', 'crossover'],
                },
                'fitness': {
                    'weights': {
                        'correctness': 0.6,
                        'performance': 0.3,
                        'complexity': 0.1,
                    },
                },
                'checkpoint': {
                    'enabled': True,
                    'interval': 5,
                    'directory': 'checkpoints',
                    'compress': True,
                },
                'early_stop': {
                    'enabled': True,
                    'patience': 20,
                    'delta': 0.0005,
                },
                'logging': {
                    'level': 'INFO',
                    'file': 'mutalambda.log',
                }
            },

            'research': {
                'evolution': {
                    'generations': 200,
                    'num_islands': 12,
                    'population_size': 24,
                    'top_k': 8,
                },
                'migration': {
                    'interval': 3,
                    'migrants_per_island': 4,
                    'topology': 'fully_connected',
                },
                'mutation': {
                    'rate': 0.2,
                    'crossover_rate': 0.85,
                    'strategies': ['random', 'guided', 'crossover', 'elite'],
                    'adaptive': True,
                },
                'fitness': {
                    'weights': {
                        'correctness': 0.5,
                        'performance': 0.35,
                        'complexity': 0.15,
                    },
                    'novelty_bonus': 0.1,
                },
                'checkpoint': {
                    'enabled': True,
                    'interval': 2,
                    'directory': 'checkpoints',
                    'compress': True,
                    'keep_best': True,
                },
                'early_stop': {
                    'enabled': False,
                },
                'logging': {
                    'level': 'DEBUG',
                    'file': 'mutalambda.log',
                    'detailed_stats': True,
                },
                'analytics': {
                    'track_lineage': True,
                    'track_diversity': True,
                    'export_interval': 10,
                }
            },

            # ── New user-friendly presets (ML-C02) ──────────────────────────
            'quick': {
                'evolution': {
                    'generations': 10,
                    'num_islands': 2,
                    'population_size': 6,
                    'top_k': 2,
                },
                'migration': {
                    'interval': 10,
                    'migrants_per_island': 1,
                    'topology': 'ring',
                },
                'mutation': {
                    'rate': 0.1,
                    'crossover_rate': 0.7,
                },
                'fitness': {
                    'weights': {
                        'correctness': 0.5,
                        'performance': 0.3,
                        'complexity': 0.2,
                    },
                },
                'sandbox': {
                    'timeout_sec': 5.0,
                },
                'checkpoint': {
                    'enabled': True,
                    'interval': 5,
                    'directory': 'checkpoints',
                },
                'early_stop': {
                    'enabled': True,
                    'patience': 5,
                    'delta': 0.01,
                },
                'logging': {
                    'level': 'WARNING',
                },
            },

            'production': {
                'evolution': {
                    'generations': 100,
                    'num_islands': 6,
                    'population_size': 12,
                    'top_k': 4,
                },
                'migration': {
                    'interval': 8,
                    'migrants_per_island': 2,
                    'topology': 'ring',
                },
                'mutation': {
                    'rate': 0.12,
                    'crossover_rate': 0.75,
                    'strategies': ['random', 'guided', 'crossover'],
                },
                'fitness': {
                    'weights': {
                        'correctness': 0.6,
                        'performance': 0.3,
                        'complexity': 0.1,
                    },
                },
                'sandbox': {
                    'timeout_sec': 30.0,
                },
                'checkpoint': {
                    'enabled': True,
                    'interval': 5,
                    'directory': 'checkpoints',
                    'compress': True,
                },
                'early_stop': {
                    'enabled': True,
                    'patience': 20,
                    'delta': 0.001,
                },
                'logging': {
                    'level': 'INFO',
                    'file': 'mutalambda.log',
                },
                'hfc': {
                    'enabled': True,
                    'tier1_size': 50,
                    'tier2_size': 100,
                    'tier3_size': 50,
                },
            },

            'scientific': {
                'evolution': {
                    'generations': 200,
                    'num_islands': 8,
                    'population_size': 16,
                    'top_k': 6,
                },
                'migration': {
                    'interval': 5,
                    'migrants_per_island': 3,
                    'topology': 'fully_connected',
                },
                'mutation': {
                    'rate': 0.15,
                    'crossover_rate': 0.8,
                    'strategies': ['random', 'guided', 'crossover', 'elite'],
                    'adaptive': True,
                },
                'fitness': {
                    'weights': {
                        'correctness': 0.5,
                        'performance': 0.35,
                        'complexity': 0.15,
                    },
                    'novelty_bonus': 0.1,
                },
                'sandbox': {
                    'timeout_sec': 60.0,
                },
                'checkpoint': {
                    'enabled': True,
                    'interval': 2,
                    'directory': 'checkpoints',
                    'compress': True,
                    'keep_best': True,
                },
                'early_stop': {
                    'enabled': False,  # Scientific mode runs full course
                },
                'logging': {
                    'level': 'DEBUG',
                    'file': 'mutalambda.log',
                    'detailed_stats': True,
                },
                'analytics': {
                    'track_lineage': True,
                    'track_diversity': True,
                    'export_interval': 10,
                },
                'invariant_validation': {
                    'enabled': True,
                },
            },

            'numpy': {
                'evolution': {
                    'generations': 150,
                    'num_islands': 6,
                    'population_size': 12,
                    'top_k': 4,
                },
                'mutation': {
                    'rate': 0.1,
                    'crossover_rate': 0.75,
                    'strategies': ['numpy_optimized', 'guided', 'crossover'],
                },
                'fitness': {
                    'weights': {
                        'correctness': 0.6,
                        'performance': 0.35,
                        'complexity': 0.05,
                    },
                },
                'sandbox': {
                    'timeout_sec': 30.0,
                },
                'numpy_optimizer': {
                    'enabled': True,
                    'target_functions': ['np.dot', 'np.sum', 'np.mean'],
                },
                'checkpoint': {
                    'enabled': True,
                    'interval': 5,
                    'directory': 'checkpoints',
                },
                'logging': {
                    'level': 'INFO',
                },
            },
        }

    def load(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from file"""
        path = Path(config_path)

        if not path.exists():
            self.animator.error_message(f"Config file not found: {config_path}")
            return {}

        try:
            with open(path, 'r') as f:
                if path.suffix in ['.yaml', '.yml']:
                    config = yaml.safe_load(f)
                elif path.suffix == '.json':
                    config = json.load(f)
                else:
                    # Try YAML first, then JSON
                    content = f.read()
                    try:
                        config = yaml.safe_load(content)
                    except Exception:
                        # Not valid YAML — try JSON (config may be dual-format).
                        try:
                            config = json.loads(content)
                        except json.JSONDecodeError as je:
                            raise ValueError(
                                f"Config is neither valid YAML nor JSON: {je}"
                            ) from je

            self.animator.success_message(f"Loaded config from {config_path}")
            return config

        except Exception as e:
            self.animator.error_message(f"Failed to load config: {e}")
            return {}

    def save(self, config: Dict[str, Any], output_path: str,
             format: str = 'yaml'):
        """Save configuration to file"""
        path = Path(output_path)

        # Ensure directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(path, 'w') as f:
                if format == 'yaml' or path.suffix in ['.yaml', '.yml']:
                    yaml.dump(config, f, default_flow_style=False, sort_keys=False)
                else:
                    json.dump(config, f, indent=2)

            self.animator.success_message(f"Saved config to {output_path}")

        except Exception as e:
            self.animator.error_message(f"Failed to save config: {e}")

    def validate(self, config: Dict[str, Any]) -> tuple[bool, list[str]]:
        """Validate configuration and return (is_valid, errors)"""
        errors = []

        # Check required sections
        required_sections = ['evolution']
        for section in required_sections:
            if section not in config:
                errors.append(f"Missing required section: {section}")

        # Validate evolution settings
        if 'evolution' in config:
            evo = config['evolution']

            if 'generations' in evo and evo['generations'] < 1:
                errors.append("generations must be >= 1")

            if 'num_islands' in evo and evo['num_islands'] < 1:
                errors.append("num_islands must be >= 1")

            if 'population_size' in evo and evo['population_size'] < 2:
                errors.append("population_size must be >= 2")

        # Validate migration settings
        if 'migration' in config:
            mig = config['migration']

            valid_topologies = ['ring', 'fully_connected', 'random']
            if 'topology' in mig and mig['topology'] not in valid_topologies:
                errors.append(f"topology must be one of: {valid_topologies}")

        # Validate mutation settings
        if 'mutation' in config:
            mut = config['mutation']

            if 'rate' in mut and not (0 <= mut['rate'] <= 1):
                errors.append("mutation rate must be between 0 and 1")

            if 'crossover_rate' in mut and not (0 <= mut['crossover_rate'] <= 1):
                errors.append("crossover_rate must be between 0 and 1")

        return len(errors) == 0, errors

    def diagnostic(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return a list of diagnostic issues with human-readable explanations.

        Each issue is a dict: {severity, code, message, fix_suggestion}
        """
        issues = []

        # Sandbox timeout
        sandbox = config.get('sandbox', {}) or {}
        timeout = sandbox.get('timeout_sec', 10.0)
        if timeout < 15:
            issues.append({
                "severity": "warning",
                "code": "sandbox.timeout",
                "message": (
                    f"Tu sandbox timeout es muy bajo ({timeout}s). "
                    f"Para código general, recomendamos al menos 30s; "
                    f"para código científico/NumPy, 60s o más."
                ),
                "fix_suggestion": f"Set sandbox.timeout_sec a 30.0 (production) o 60.0 (scientific)",
                "fix_key": ("sandbox", "timeout_sec"),
                "fix_value": 30.0 if timeout >= 10 else 60.0,
            })

        # Population size warning
        evo = config.get('evolution', {}) or {}
        pop_size = evo.get('population_size', 8)
        if pop_size < 4:
            issues.append({
                "severity": "warning",
                "code": "evolution.population",
                "message": (
                    f"Tu population_size es bajo ({pop_size}). "
                    f"Valores menores a 4 pueden converger muy rápido "
                    f"y perder diversidad evolutiva."
                ),
                "fix_suggestion": "Incrementa a al menos 6-8 individuos por isla.",
                "fix_key": ("evolution", "population_size"),
                "fix_value": 8,
            })

        # Generations
        gens = evo.get('generations', 50)
        if gens < 20:
            issues.append({
                "severity": "info",
                "code": "evolution.generations",
                "message": (
                    f"Tu número de generaciones ({gens}) es bajo. "
                    f"Para resultados significativos, considera 50-100+."
                ),
            })

        # Migration topology
        mig = config.get('migration', {}) or {}
        topology = mig.get('topology', 'ring')
        if topology == 'ring' and evo.get('num_islands', 4) > 8:
            issues.append({
                "severity": "info",
                "code": "migration.topology",
                "message": (
                    f"Topology 'ring' con {evo.get('num_islands', 4)} islas puede "
                    f"ser lento. Considera 'fully_connected' para mejor convergencia."
                ),
                "fix_suggestion": "Set migration.topology to 'fully_connected'",
                "fix_key": ("migration", "topology"),
                "fix_value": "fully_connected",
            })

        # Checkpoint
        chk = config.get('checkpoint', {}) or {}
        if chk.get('interval', 10) > 50:
            issues.append({
                "severity": "warning",
                "code": "checkpoint.interval",
                "message": (
                    f"Tu checkpoint interval ({chk.get('interval', 10)}) es muy alto. "
                    f"Puedes perder trabajo valioso si la evolución falla."
                ),
                "fix_suggestion": "Reduce a 10-20 generaciones.",
                "fix_key": ("checkpoint", "interval"),
                "fix_value": 10,
            })

        return issues

    def apply_fix(self, config: Dict[str, Any], issue: Dict[str, Any]) -> bool:
        """Apply a fix to the config based on an issue dict."""
        if "fix_key" not in issue or "fix_value" not in issue:
            return False
        key_path = issue["fix_key"]
        value = issue["fix_value"]

        # Navigate/create nested dict
        d = config
        for k in key_path[:-1]:
            if k not in d or not isinstance(d[k], dict):
                d[k] = {}
            d = d[k]
        d[key_path[-1]] = value
        return True

    def create_from_template(self, template_name: str,
                            output_path: str) -> bool:
        """Create config from template"""
        if template_name not in self.templates:
            self.animator.error_message(
                f"Unknown template: {template_name}. "
                f"Available: {list(self.templates.keys())}"
            )
            return False

        template = self.templates[template_name]
        self.save(template, output_path)

        self.console.print(f"\n  Template: {template_name}")
        self.console.print(f"  Output: {output_path}\n")

        # Show summary
        self.display_summary(template)

        return True

    def display_summary(self, config: Dict[str, Any]):
        """Display config summary"""
        table = Table(title="Configuration Summary",
                     show_header=True,
                     header_style="bold cyan")

        table.add_column("Section", style="magenta")
        table.add_column("Key", style="cyan")
        table.add_column("Value", justify="right")

        for section, values in config.items():
            if isinstance(values, dict):
                for key, value in values.items():
                    table.add_row(section, key, str(value))
            else:
                table.add_row(section, "", str(values))

        self.console.print(table)

    def display_summary_from_file(self, config_path: str) -> None:
        """Load configuration from file and display summary"""
        config = self.load(config_path)
        if config:
            self.display_summary(config)

    def display_full(self, config: Dict[str, Any], format: str = 'yaml'):
        """Display full configuration"""
        if format == 'yaml':
            self.console.print(yaml.dump(config, default_flow_style=False))
        elif format == 'json':
            self.console.print(json.dumps(config, indent=2))
        else:
            self.display_summary(config)

    def merge_configs(self, base: Dict[str, Any],
                     override: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge two configurations"""
        result = base.copy()

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self.merge_configs(result[key], value)
            else:
                result[key] = value

        return result

    def get_default(self) -> Dict[str, Any]:
        """Get default configuration"""
        return self.templates['basic'].copy()
