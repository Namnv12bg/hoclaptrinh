from __future__ import annotations

import math
from typing import Optional


class TempoMap:
    """Minimal tempo map for breath/phase calculations.

    Attributes
    ----------
    ticks_per_bar: int
        How many ticks make up a single bar. Defaults to 4 quarter-notes
        at 480 ppq (1920 ticks).
    """

    def __init__(self, ticks_per_bar: int = 1920) -> None:
        self.ticks_per_bar = max(1, ticks_per_bar)

    def get_bar_pos_at_tick(self, tick: int) -> float:
        """Return the bar position for the provided tick."""
        return tick / float(self.ticks_per_bar)

    def get_phase_at_bar(self, bar_position: float, *, phase_wrap: float = 2 * math.pi) -> float:
        """Convert a bar position to a phase value.

        The default behavior maps 1 bar to a full 2π rotation so a breath
        envelope can use ``sin(phase)`` to oscillate once per bar.
        """
        return (bar_position % 1.0) * phase_wrap
