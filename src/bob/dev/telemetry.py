"""Plausible fake system numbers for Phase 1.

Real telemetry (``psutil``) arrives in Phase 6. Until then the system panel
needs *something* to render, and constant zeroes would hide layout problems.
The values drift smoothly rather than jumping, so the meters look like real
measurements instead of noise.
"""

from __future__ import annotations

import math
import random
import time

from bob.ui.viewmodel import SystemStats


class MockTelemetry:
    """Smoothly drifting fake metrics."""

    def __init__(self, *, ram_total_gb: float = 32.0) -> None:
        self._start = time.monotonic()
        self._ram_total = ram_total_gb
        self._cpu = 18.0
        self._net = 120.0

    def sample(self) -> SystemStats:
        elapsed = time.monotonic() - self._start

        # Drift toward a slow sine, with a little noise: looks like a real load.
        cpu_target = 22.0 + 16.0 * math.sin(elapsed / 11.0) + random.uniform(-4, 6)
        self._cpu += (cpu_target - self._cpu) * 0.35
        self._cpu = max(2.0, min(97.0, self._cpu))

        ram_percent = 54.0 + 6.0 * math.sin(elapsed / 23.0)
        net_target = max(0.0, 140.0 + 260.0 * math.sin(elapsed / 7.0) + random.uniform(-60, 90))
        self._net += (net_target - self._net) * 0.4

        return SystemStats(
            cpu_percent=round(self._cpu, 1),
            ram_percent=round(ram_percent, 1),
            ram_used_gb=round(self._ram_total * ram_percent / 100.0, 1),
            ram_total_gb=self._ram_total,
            disk_percent=68.0,
            network_kbps=round(max(0.0, self._net), 0),
            gpu_percent=round(max(0.0, self._cpu * 0.6), 1),
        )
