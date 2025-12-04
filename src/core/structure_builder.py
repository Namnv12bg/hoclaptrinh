from __future__ import annotations


class Segment:
    def __init__(
        self,
        start_tick: int,
        duration_ticks: int,
        section_type: str = "",
        energy_bias: float = 0.0,
        t_norm: float | None = None,
    ):
        self.start_tick = start_tick
        self.duration_ticks = duration_ticks
        self.section_type = section_type
        self.energy_bias = energy_bias
        self.t_norm = t_norm

    @property
    def end_tick(self) -> int:
        return self.start_tick + self.duration_ticks
