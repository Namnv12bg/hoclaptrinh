from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Segment:
    start_tick: int
    end_tick: int
    section_type: str = ""
    energy_bias: float = 0.5
