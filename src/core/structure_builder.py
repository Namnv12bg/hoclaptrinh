"""Data structures representing song timeline segments."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Segment:
    """Represents a time-bounded musical segment used for pulse creation."""

    start_tick: int
    end_tick: int
    energy_bias: float = 0.5
