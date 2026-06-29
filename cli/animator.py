"""
Retro-style animations for MutaLambda CLI

Provides ASCII art animations, progress bars, and visual effects
inspired by Atari/retro gaming aesthetics.
"""

import time
import sys
from typing import List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.text import Text
from rich.layout import Layout


class RetroAnimator:
    """Retro-style animator with Atari-inspired visuals"""
    
    def __init__(self, style: str = 'retro'):
        self.style = style
        self.console = Console()
        self.frames = 0
        
        # Retro color palette
        self.colors = {
            'primary': 'bright_cyan',
            'secondary': 'bright_magenta',
            'success': 'bright_green',
            'warning': 'bright_yellow',
            'error': 'bright_red',
            'dim': 'dim',
        }
    
    def clear_screen(self):
        """Clear terminal screen"""
        if self.style != 'none':
            print("\033[2J\033[H", end="")
    
    def print_banner(self, title: str, subtitle: str = ""):
        """Print retro-style banner"""
        if self.style == 'none':
            return
        
        # ASCII art banner
        banner = f"""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   ███╗   ███╗██╗   ██╗████████╗ █████╗ ██╗      █████╗       ║
║   ████╗ ████║██║   ██║╚══██╔══╝██╔══██╗██║     ██╔══██╗      ║
║   ██╔████╔██║██║   ██║   ██║   ███████║██║     ███████║      ║
║   ██║╚██╔╝██║██║   ██║   ██║   ██╔══██║██║     ██╔══██║      ║
║   ██║ ╚═╝ ██║╚██████╔╝   ██║   ██║  ██║███████╗██║  ██║      ║
║   ╚═╝     ╚═╝ ╚═════╝    ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝      ║
║                                                              ║
║          Lambda: Evolutionary Code Optimization              ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
"""
        
        self.console.print(banner, style=self.colors['primary'])
        
        if subtitle:
            self.console.print(f"  {subtitle}", style=self.colors['secondary'])
        
        self.console.print()
    
    def progress_bar(self, current: int, total: int, prefix: str = "", 
                     width: int = 40, show_percent: bool = True) -> str:
        """Generate retro-style progress bar"""
        percent = current / total if total > 0 else 0
        filled = int(width * percent)
        
        # Retro-style progress bar with blocks
        bar = "█" * filled + "░" * (width - filled)
        
        result = f"{prefix} [{bar}]"
        if show_percent:
            result += f" {percent*100:5.1f}%"
        
        return result
    
    def island_display(self, island_id: int, fitness: float, 
                       population_size: int, is_migrating: bool = False) -> str:
        """Display island status with retro graphics"""
        # Island ASCII art
        island_art = "🏝️" if not is_migrating else "🚀"
        
        # Fitness indicator (bars)
        fitness_bars = int(fitness * 10)
        fitness_indicator = "▓" * fitness_bars + "░" * (10 - fitness_bars)
        
        # Population indicator
        pop_indicator = "●" * min(population_size, 20)
        
        return f"{island_art} Island {island_id:2d} | Fitness: [{fitness_indicator}] {fitness:.3f} | Pop: {pop_indicator}"
    
    def migration_animation(self, from_island: int, to_island: int, 
                           num_migrants: int):
        """Animate migration between islands"""
        if self.style == 'none':
            return
        
        # Retro arrow animation
        arrows = ["→", "⇒", "⟹", "⟶"]
        
        for i, arrow in enumerate(arrows):
            self.console.print(
                f"  Island {from_island} {arrow * (i+1)} Island {to_island} "
                f"({num_migrants} migrants)",
                style=self.colors['secondary']
            )
            time.sleep(0.1)
    
    def fitness_graph(self, fitness_history: List[float], 
                      width: int = 60, height: int = 10) -> str:
        """Generate ASCII art fitness graph"""
        if not fitness_history or len(fitness_history) < 2:
            return "Insufficient data for graph"
        
        # Normalize to graph height
        max_fit = max(fitness_history)
        min_fit = min(fitness_history)
        fit_range = max_fit - min_fit if max_fit != min_fit else 1
        
        # Sample points to fit width
        step = max(1, len(fitness_history) // width)
        sampled = fitness_history[::step][:width]
        
        # Generate graph
        graph_lines = []
        for row in range(height, 0, -1):
            threshold = min_fit + (fit_range * row / height)
            line = ""
            for val in sampled:
                if val >= threshold:
                    line += "█"
                else:
                    line += " "
            graph_lines.append(f"  {line}")
        
        # Add axis labels
        graph_lines.append(f"  {'─' * len(sampled)}")
        graph_lines.append(f"  {min_fit:.3f}{' ' * (len(sampled)-12)}{max_fit:.3f}")
        
        return "\n".join(graph_lines)
    
    def evolution_stats_table(self, stats: dict) -> Table:
        """Create retro-styled statistics table"""
        table = Table(
            show_header=True,
            header_style=f"bold {self.colors['primary']}",
            border_style=self.colors['dim']
        )
        
        table.add_column("Metric", style=self.colors['secondary'])
        table.add_column("Value", justify="right")
        table.add_column("Status", justify="center")
        
        for key, value in stats.items():
            # Determine status indicator
            if isinstance(value, (int, float)):
                if key in ['best_fitness', 'avg_fitness']:
                    status = "✓" if value > 0.5 else "⚠"
                else:
                    status = "●"
            else:
                status = "●"
            
            # Format value
            if isinstance(value, float):
                formatted = f"{value:.4f}"
            elif isinstance(value, int):
                formatted = f"{value:,}"
            else:
                formatted = str(value)
            
            table.add_row(key.replace('_', ' ').title(), formatted, status)
        
        return table
    
    def loading_spinner(self, message: str = "Processing"):
        """Retro loading spinner"""
        if self.style == 'none':
            print(message)
            return
        
        spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        
        with Live(
            Text(f"{spinner_chars[0]} {message}", style=self.colors['primary']),
            refresh_per_second=10,
            console=self.console
        ) as live:
            for i in range(20):  # 2 seconds
                char = spinner_chars[i % len(spinner_chars)]
                live.update(Text(f"{char} {message}", style=self.colors['primary']))
                time.sleep(0.1)
    
    def success_message(self, message: str):
        """Display success message with retro styling"""
        self.console.print(f"✓ {message}", style=self.colors['success'])
    
    def warning_message(self, message: str):
        """Display warning message with retro styling"""
        self.console.print(f"⚠ {message}", style=self.colors['warning'])
    
    def error_message(self, message: str):
        """Display error message with retro styling"""
        self.console.print(f"✗ {message}", style=self.colors['error'])
    
    def info_panel(self, title: str, content: str):
        """Display information in a retro panel"""
        panel = Panel(
            content,
            title=title,
            border_style=self.colors['primary'],
            padding=(1, 2)
        )
        self.console.print(panel)
    
    def generation_header(self, gen: int, total: int):
        """Display generation header"""
        if self.style == 'none':
            return
        
        self.console.print(
            f"\n{'═'*60}\n"
            f"  GENERATION {gen}/{total}\n"
            f"{'═'*60}",
            style=f"bold {self.colors['primary']}"
        )
    
    def fitness_update(self, old_fitness: float, new_fitness: float):
        """Animate fitness update"""
        if self.style == 'none':
            return
        
        delta = new_fitness - old_fitness
        if delta > 0:
            symbol = "↑"
            color = self.colors['success']
        elif delta < 0:
            symbol = "↓"
            color = self.colors['error']
        else:
            symbol = "→"
            color = self.colors['dim']
        
        self.console.print(
            f"  Fitness: {old_fitness:.4f} {symbol} {new_fitness:.4f} ({delta:+.4f})",
            style=color
        )
    
    def island_grid(self, islands: List[dict]):
        """Display islands in a grid layout"""
        if self.style == 'none':
            return
        
        # Create 2x2 or larger grid
        cols = min(4, len(islands))
        rows = (len(islands) + cols - 1) // cols
        
        for row in range(rows):
            line_parts = []
            for col in range(cols):
                idx = row * cols + col
                if idx < len(islands):
                    island = islands[idx]
                    # Compact island display
                    fitness_bar = "█" * int(island['fitness'] * 5)
                    line_parts.append(
                        f"🏝️{island['id']:2d}[{fitness_bar:<5}]{island['fitness']:.2f}"
                    )
                else:
                    line_parts.append(" " * 20)
            
            self.console.print("  ".join(line_parts))
        self.console.print()
