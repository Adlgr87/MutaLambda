"""
Real-time Performance Monitor for MutaLambda.

Tracks resource utilization, bottleneck detection, and alerts
during evolution runs. Integrates with metrics_exporter for
Prometheus/OpenTelemetry output.
"""
from __future__ import annotations

import logging
import os
import time
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Deque, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False
    psutil = None  # type: ignore


@dataclass
class ResourceSnapshot:
    """Point-in-time resource utilization snapshot."""
    timestamp: float
    cpu_percent: float
    memory_used_mb: float
    memory_total_mb: float
    memory_percent: float
    disk_read_mb: float
    disk_write_mb: float
    gpu_utilization: float = 0.0
    gpu_memory_used_mb: float = 0.0


@dataclass
class BottleneckAlert:
    """Alert when a resource bottleneck is detected."""
    timestamp: float
    resource: str
    value: float
    threshold: float
    message: str
    severity: str = "warning"  # "info", "warning", "critical"


@dataclass
class MonitorConfig:
    """Configuration for the performance monitor."""
    sampling_interval_sec: float = 1.0
    history_size: int = 3600  # Keep 1 hour of samples
    cpu_threshold_pct: float = 90.0
    memory_threshold_pct: float = 85.0
    gpu_threshold_pct: float = 95.0
    alert_callbacks: List[Callable[[BottleneckAlert], None]] = field(default_factory=list)
    log_level: str = "WARNING"


class PerformanceMonitor:
    """
    Real-time performance monitor for MutaLambda optimization runs.

    Features:
    - Continuous resource sampling (CPU, RAM, Disk, GPU)
    - Bottleneck detection with configurable thresholds
    - Alert callbacks for threshold breaches
    - Integration with metrics_exporter (Prometheus/OTel)
    - Thread-safe history tracking
    """

    def __init__(self, config: Optional[MonitorConfig] = None) -> None:
        self.config = config or MonitorConfig()
        self._samples: Deque[ResourceSnapshot] = deque(maxlen=self.config.history_size)
        self._alerts: List[BottleneckAlert] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._start_time: float = 0.0
        self._lock = threading.Lock()

        # Set up alert logging
        self._alert_logger = logging.getLogger("mutalambda.alerts")
        self._alert_logger.setLevel(getattr(logging, self.config.log_level.upper(), logging.WARNING))

    def start(self) -> None:
        """Start the monitoring thread."""
        if self._running:
            return

        self._running = True
        self._start_time = time.perf_counter()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="perf-monitor")
        self._thread.start()
        logger.info("Performance monitor started (interval=%.1fs)", self.config.sampling_interval_sec)

    def stop(self) -> None:
        """Stop the monitoring thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("Performance monitor stopped")

    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                snapshot = self._take_snapshot()
                with self._lock:
                    self._samples.append(snapshot)
                self._check_thresholds(snapshot)
            except Exception as exc:
                logger.debug("Monitor sample error: %s", exc)

            time.sleep(self.config.sampling_interval_sec)

    def _take_snapshot(self) -> ResourceSnapshot:
        """Take a resource utilization snapshot."""
        ts = time.perf_counter()

        # CPU
        cpu_pct = psutil.cpu_percent(interval=0.1) if _HAS_PSUTIL else 0.0

        # Memory
        mem_used = 0.0
        mem_total = 0.0
        mem_pct = 0.0
        if _HAS_PSUTIL and psutil.virtual_memory():
            mem = psutil.virtual_memory()
            mem_used = mem.used / 1024**2
            mem_total = mem.total / 1024**2
            mem_pct = mem.percent

        # Disk I/O
        disk_read = 0.0
        disk_write = 0.0
        if _HAS_PSUTIL:
            try:
                disk = psutil.disk_io_counters()
                if disk:
                    disk_read = disk.read_bytes / 1024**2
                    disk_write = disk.write_bytes / 1024**2
            except Exception:
                pass

        # GPU (if available)
        gpu_util = 0.0
        gpu_mem = 0.0
        try:
            from gpu_optimizer import GPUOptimizer  # noqa: PLC0415
            mem = GPUOptimizer({}).get_memory_usage()
            gpu_mem = mem.get("gpu_memory_used_mb", 0.0)
            # GPU utilization requires nvidia-smi
            if _HAS_PSUTIL:
                try:
                    import subprocess  # noqa: PLC0415
                    result = subprocess.run(
                        ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                        capture_output=True, text=True, timeout=2,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        gpu_util = float(result.stdout.strip().split("\n")[0])
                except Exception:
                    pass
        except Exception:
            pass

        return ResourceSnapshot(
            timestamp=ts,
            cpu_percent=cpu_pct,
            memory_used_mb=mem_used,
            memory_total_mb=mem_total,
            memory_percent=mem_pct,
            disk_read_mb=disk_read,
            disk_write_mb=disk_write,
            gpu_utilization=gpu_util,
            gpu_memory_used_mb=gpu_mem,
        )

    def _check_thresholds(self, snapshot: ResourceSnapshot) -> None:
        """Check if any thresholds are breached and trigger alerts."""
        checks = [
            ("cpu", snapshot.cpu_percent, self.config.cpu_threshold_pct, "CPU usage"),
            ("memory", snapshot.memory_percent, self.config.memory_threshold_pct, "Memory usage"),
            ("gpu", snapshot.gpu_utilization, self.config.gpu_threshold_pct, "GPU utilization"),
        ]

        for resource, value, threshold, label in checks:
            if value >= threshold:
                alert = BottleneckAlert(
                    timestamp=snapshot.timestamp,
                    resource=resource,
                    value=value,
                    threshold=threshold,
                    message=f"{label}: {value:.1f}% exceeds threshold {threshold}%",
                    severity="critical" if value >= threshold * 1.1 else "warning",
                )
                with self._lock:
                    self._alerts.append(alert)
                self._alert_logger.warning("%s [%.1f%%]", alert.message, value)
                for cb in self.config.alert_callbacks:
                    try:
                        cb(alert)
                    except Exception as exc:
                        logger.debug("Alert callback error: %s", exc)

    def record_evolution_step(
        self,
        generation: int,
        best_score: float,
        duration_sec: float,
        population_size: int,
    ) -> None:
        """
        Record an evolution step for trend analysis.

        This supplements the resource snapshots with evolution-specific metrics.
        """
        snapshot = self._take_snapshot()
        snapshot.evolution_generation = generation  # type: ignore[attr-defined]
        snapshot.evolution_best_score = best_score  # type: ignore[attr-defined]
        snapshot.evolution_duration_sec = duration_sec  # type: ignore[attr-defined]
        snapshot.evolution_population_size = population_size  # type: ignore[attr-defined]

        with self._lock:
            self._samples.append(snapshot)

    def get_trends(self, window_sec: float = 300.0) -> Dict[str, Any]:
        """Get trend analysis over a time window."""
        with self._lock:
            cutoff = time.perf_counter() - window_sec
            recent = [s for s in self._samples if s.timestamp >= cutoff]

        if not recent:
            return {"error": "no samples in window"}

        cpu_vals = [s.cpu_percent for s in recent]
        mem_vals = [s.memory_percent for s in recent]
        durations = []
        for s in recent:
            dur = getattr(s, "evolution_duration_sec", None)
            if dur is not None:
                durations.append(dur)

        return {
            "window_sec": window_sec,
            "sample_count": len(recent),
            "cpu": {
                "mean": np.mean(cpu_vals),
                "max": np.max(cpu_vals),
                "min": np.min(cpu_vals),
                "trend": "increasing" if cpu_vals[-1] > cpu_vals[0] else "stable",
            },
            "memory": {
                "mean": np.mean(mem_vals),
                "max": np.max(mem_vals),
                "min": np.min(mem_vals),
            },
            "evolution_duration": {
                "mean": float(np.mean(durations)) if durations else None,
                "trend": "improving" if len(durations) > 1 and durations[-1] < durations[0] else "stable",
            },
            "alerts_triggered": len(self._alerts),
        }

    def get_alerts(self, last_n: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get recent alerts."""
        with self._lock:
            alerts = list(self._alerts)
        if last_n:
            alerts = alerts[-last_n:]
        return [
            {
                "timestamp": a.timestamp,
                "resource": a.resource,
                "value": a.value,
                "threshold": a.threshold,
                "message": a.message,
                "severity": a.severity,
            }
            for a in alerts
        ]

    def get_latest(self) -> Optional[ResourceSnapshot]:
        """Get the most recent snapshot."""
        with self._lock:
            if self._samples:
                return self._samples[-1]
        return None

    def export_prometheus(self) -> str:
        """Export current state in Prometheus format."""
        trends = self.get_trends()
        lines = ["# HELP mutalambda_cpu_percent Current CPU usage percentage",
                  "# TYPE mutalambda_cpu_percent gauge"]

        latest = self.get_latest()
        if latest:
            lines.append(f'mutalambda_cpu_percent {latest.cpu_percent}')
            lines.append(f'mutalambda_memory_percent {latest.memory_percent}')
            lines.append(f'mutalambda_gpu_utilization {latest.gpu_utilization}')
            lines.append(f'mutalambda_gpu_memory_used_mb {latest.gpu_memory_used_mb}')
            lines.append(f'mutalambda_alerts_total {len(self._alerts)}')

            # Evolution metrics if available
            gen = getattr(latest, "evolution_generation", None)
            if gen is not None:
                lines.append(f"mutalambda_evolution_generation {gen}")
                score = getattr(latest, "evolution_best_score", None)
                if score is not None:
                    lines.append(f"mutalambda_evolution_best_score {score}")

        return "\n".join(lines)


# Singleton instance
_default_monitor: Optional[PerformanceMonitor] = None


def get_monitor(config: Optional[MonitorConfig] = None) -> PerformanceMonitor:
    """Get or create the default performance monitor singleton."""
    global _default_monitor
    if _default_monitor is None:
        _default_monitor = PerformanceMonitor(config)
    return _default_monitor


def reset_monitor() -> None:
    """Reset the singleton (for testing)."""
    global _default_monitor
    if _default_monitor:
        _default_monitor.stop()
    _default_monitor = None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MutaLambda Performance Monitor")
    parser.add_argument("--interval", type=float, default=1.0, help="Sampling interval (seconds)")
    parser.add_argument("--duration", type=float, default=60.0, help="Monitor duration (seconds)")
    args = parser.parse_args()

    monitor = get_monitor(MonitorConfig(sampling_interval_sec=args.interval))
    monitor.start()

    print(f"Monitoring for {args.duration}s...")
    start = time.perf_counter()
    while time.perf_counter() - start < args.duration:
        trends = monitor.get_trends()
        print(f"\rCPU: {trends.get('cpu', {}).get('mean', 0):.1f}% | "
              f"Mem: {trends.get('memory', {}).get('mean', 0):.1f}% | "
              f"Alerts: {trends.get('alerts_triggered', 0)}   ", end="", flush=True)
        time.sleep(args.interval)

    monitor.stop()
    print("\nDone. Final trends:", json.dumps(monitor.get_trends(), indent=2))
