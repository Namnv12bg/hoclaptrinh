from __future__ import annotations


class TempoMap:
    def __init__(self, ppq: int = 480, breath_cycle_bars: float = 2.0):
        self.ppq = ppq
        self.breath_cycle_bars = breath_cycle_bars

    def get_bar_pos_at_tick(self, tick: int) -> float:
        if self.ppq <= 0:
            return 0.0
        # assume 4/4: bar_length = ppq * 4
        bar_len = self.ppq * 4
        return tick / bar_len
