"""Configuration helpers and instrument profile stubs."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class InstrumentProfile:
    """Options that influence the pulse engine layers."""

    enable_pulse_layer: bool = True
    enable_heartbeat_layer: bool = True
    enable_kalimba_layer: bool = True
    pulse_activity_mid_threshold: float = 0.6
    pulse_activity_high_threshold: float = 0.85
    pulse_activity_threshold: float = 0.6
    pulse_reduction_ratio: float = 0.6
    program: int = 108
