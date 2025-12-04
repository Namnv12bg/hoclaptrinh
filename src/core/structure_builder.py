"""Structural building blocks used by the pulse engine stubs."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Segment:
    """Simple musical segment descriptor."""

    start_tick: int
    duration_ticks: int
    intensity: float = 1.0
