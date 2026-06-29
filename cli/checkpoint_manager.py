"""
Checkpoint manager for MutaLambda CLI

Handles saving, loading, and managing evolution checkpoints.
"""

import pickle
import gzip
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from rich.console import Console
from rich.table import Table

from cli.animator import RetroAnimator


class CheckpointManager:
    """Manages evolution checkpoints"""
    
    def __init__(self, checkpoint_dir: str = 'checkpoints',
                 animator: Optional[RetroAnimator] = None):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.animator = animator or RetroAnimator()
        self.console = Console()
        
        # Ensure directory exists
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    
    def save(self, state: Dict[str, Any], 
             generation: int,
             metadata: Optional[Dict[str, Any]] = None,
             compress: bool = True) -> str:
        """Save evolution state to checkpoint"""
        
        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"gen_{generation:04d}_{timestamp}.ckpt"
        filepath = self.checkpoint_dir / filename
        
        # Prepare checkpoint data
        checkpoint = {
            'version': '3.1.0',
            'generation': generation,
            'timestamp': timestamp,
            'state': state,
            'metadata': metadata or {}
        }
        
        try:
            if compress:
                # Compress with gzip
                with gzip.open(filepath.with_suffix('.ckpt.gz'), 'wb') as f:
                    pickle.dump(checkpoint, f, protocol=pickle.HIGHEST_PROTOCOL)
                actual_path = filepath.with_suffix('.ckpt.gz')
            else:
                # Save uncompressed
                with open(filepath, 'wb') as f:
                    pickle.dump(checkpoint, f, protocol=pickle.HIGHEST_PROTOCOL)
                actual_path = filepath
            
            self.animator.success_message(f"Checkpoint saved: {actual_path.name}")
            return str(actual_path)
            
        except Exception as e:
            self.animator.error_message(f"Failed to save checkpoint: {e}")
            return ""
    
    def load(self, checkpoint_path: str) -> Optional[Dict[str, Any]]:
        """Load evolution state from checkpoint"""
        path = Path(checkpoint_path)
        
        if not path.exists():
            self.animator.error_message(f"Checkpoint not found: {checkpoint_path}")
            return None
        
        try:
            # Detect if compressed
            if path.suffix == '.gz':
                with gzip.open(path, 'rb') as f:
                    checkpoint = pickle.load(f)
            else:
                with open(path, 'rb') as f:
                    checkpoint = pickle.load(f)
            
            self.animator.success_message(
                f"Loaded checkpoint: {path.name} "
                f"(generation {checkpoint['generation']})"
            )
            
            return checkpoint
            
        except Exception as e:
            self.animator.error_message(f"Failed to load checkpoint: {e}")
            return None
    
    def list_checkpoints(self, sort_by: str = 'time') -> List[Dict[str, Any]]:
        """List all available checkpoints"""
        checkpoints = []
        
        # Find all checkpoint files
        patterns = ['*.ckpt', '*.ckpt.gz']
        files = []
        for pattern in patterns:
            files.extend(self.checkpoint_dir.glob(pattern))
        
        for filepath in files:
            try:
                # Get file info
                stat = filepath.stat()
                
                # Try to load metadata
                try:
                    if filepath.suffix == '.gz':
                        with gzip.open(filepath, 'rb') as f:
                            checkpoint = pickle.load(f)
                    else:
                        with open(filepath, 'rb') as f:
                            checkpoint = pickle.load(f)
                    
                    generation = checkpoint.get('generation', '?')
                    timestamp = checkpoint.get('timestamp', '?')
                    metadata = checkpoint.get('metadata', {})
                except:
                    generation = '?'
                    timestamp = '?'
                    metadata = {}
                
                checkpoints.append({
                    'path': str(filepath),
                    'filename': filepath.name,
                    'generation': generation,
                    'timestamp': timestamp,
                    'size': stat.st_size,
                    'modified': datetime.fromtimestamp(stat.st_mtime),
                    'metadata': metadata
                })
                
            except Exception as e:
                self.animator.warning_message(f"Failed to read {filepath.name}: {e}")
        
        # Sort
        if sort_by == 'time':
            checkpoints.sort(key=lambda x: x['modified'], reverse=True)
        elif sort_by == 'generation':
            checkpoints.sort(key=lambda x: x['generation'], reverse=True)
        elif sort_by == 'size':
            checkpoints.sort(key=lambda x: x['size'], reverse=True)
        
        return checkpoints
    
    def display_checkpoints(self, checkpoints: List[Dict[str, Any]]):
        """Display checkpoints in a table"""
        if not checkpoints:
            self.console.print("\n  No checkpoints found\n")
            return
        
        table = Table(title="Available Checkpoints",
                     show_header=True,
                     header_style="bold cyan")
        
        table.add_column("Filename", style="cyan", no_wrap=True)
        table.add_column("Generation", justify="right", style="magenta")
        table.add_column("Timestamp", style="green")
        table.add_column("Size", justify="right", style="yellow")
        table.add_column("Modified", style="blue")
        
        for cp in checkpoints:
            # Format size
            size = cp['size']
            if size > 1024 * 1024:
                size_str = f"{size / (1024*1024):.1f} MB"
            elif size > 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size} B"
            
            # Format modified time
            modified_str = cp['modified'].strftime("%Y-%m-%d %H:%M:%S")
            
            table.add_row(
                cp['filename'],
                str(cp['generation']),
                cp['timestamp'],
                size_str,
                modified_str
            )
        
        self.console.print(table)
    
    def clean_old_checkpoints(self, max_age_days: int = 7, 
                             keep_best: bool = True) -> int:
        """Remove old checkpoints"""
        checkpoints = self.list_checkpoints(sort_by='time')
        cutoff = datetime.now() - timedelta(days=max_age_days)
        
        removed = 0
        for cp in checkpoints:
            # Skip if newer than cutoff
            if cp['modified'] > cutoff:
                continue
            
            # Optionally keep best checkpoints
            if keep_best and cp['metadata'].get('is_best', False):
                continue
            
            # Remove
            try:
                Path(cp['path']).unlink()
                removed += 1
                self.console.print(f"  Removed: {cp['filename']}")
            except Exception as e:
                self.animator.warning_message(
                    f"Failed to remove {cp['filename']}: {e}"
                )
        
        if removed > 0:
            self.animator.success_message(f"Removed {removed} old checkpoint(s)")
        else:
            self.console.print("  No old checkpoints to remove")
        
        return removed
    
    def get_latest(self) -> Optional[str]:
        """Get path to most recent checkpoint"""
        checkpoints = self.list_checkpoints(sort_by='time')
        return checkpoints[0]['path'] if checkpoints else None
    
    def get_best(self) -> Optional[str]:
        """Get path to best checkpoint (highest fitness)"""
        checkpoints = self.list_checkpoints(sort_by='time')
        
        best_path = None
        best_fitness = -1
        
        for cp in checkpoints:
            fitness = cp['metadata'].get('best_fitness', 0)
            if fitness > best_fitness:
                best_fitness = fitness
                best_path = cp['path']
        
        return best_path
    
    def export_metadata(self, output_path: str):
        """Export checkpoint metadata to JSON"""
        checkpoints = self.list_checkpoints()
        
        metadata_list = []
        for cp in checkpoints:
            metadata_list.append({
                'filename': cp['filename'],
                'generation': cp['generation'],
                'timestamp': cp['timestamp'],
                'size': cp['size'],
                'modified': cp['modified'].isoformat(),
                'metadata': cp['metadata']
            })
        
        with open(output_path, 'w') as f:
            json.dump(metadata_list, f, indent=2)
        
        self.animator.success_message(f"Exported metadata to {output_path}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get checkpoint statistics"""
        checkpoints = self.list_checkpoints()
        
        if not checkpoints:
            return {
                'total': 0,
                'total_size': 0,
                'oldest': None,
                'newest': None,
                'generations': []
            }
        
        total_size = sum(cp['size'] for cp in checkpoints)
        generations = [cp['generation'] for cp in checkpoints if cp['generation'] != '?']
        
        return {
            'total': len(checkpoints),
            'total_size': total_size,
            'oldest': checkpoints[-1]['modified'] if checkpoints else None,
            'newest': checkpoints[0]['modified'] if checkpoints else None,
            'generations': sorted(set(generations))
        }
