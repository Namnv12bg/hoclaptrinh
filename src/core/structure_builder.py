from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Segment:
    start_tick: int
    end_tick: int
    section_type: str = ""

    @property
    def duration_ticks(self) -> int:
        return max(0, self.end_tick - self.start_tick)
