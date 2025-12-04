from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


def _default_duration(start_tick: int, end_tick: Optional[int], duration_ticks: Optional[int]) -> int:
    if duration_ticks is not None:
        return duration_ticks
    if end_tick is None:
        return 0
    return max(0, end_tick - start_tick)


def _default_end_tick(start_tick: int, end_tick: Optional[int], duration_ticks: Optional[int]) -> int:
    if end_tick is not None:
        return end_tick
    if duration_ticks is None:
        return start_tick
    return start_tick + duration_ticks


@dataclass
class Segment:
    start_tick: int
    end_tick: Optional[int]
    chord_name: str
    section_type: str = ""
    energy_bias: float = 0.5
    duration_ticks: Optional[int] = None

    def __post_init__(self) -> None:
        self.start_tick = int(self.start_tick)
        self.end_tick = _default_end_tick(self.start_tick, self.end_tick, self.duration_ticks)
        self.duration_ticks = _default_duration(self.start_tick, self.end_tick, self.duration_ticks)

