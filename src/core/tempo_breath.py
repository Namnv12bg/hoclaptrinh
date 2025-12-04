from __future__ import annotations

import math


class TempoMap:
    def get_bar_pos_at_tick(self, tick: int) -> float:
        return tick / 480.0

    def get_phase_at_bar(self, bar_pos: float) -> float:
        return (bar_pos % 1.0) * 2 * math.pi
