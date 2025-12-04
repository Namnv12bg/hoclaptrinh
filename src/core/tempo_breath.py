"""Tempo and breath utilities.

Only the minimal attributes used by StructureBuilder are provided here.
"""

from typing import Optional


class TempoMap:
    def __init__(self, base_tempo: float = 60.0, breath_cycle_bars: float = 1.0):
        self.base_tempo = base_tempo
        self.breath_cycle_bars = breath_cycle_bars

    def get_ticks_for_duration(self, seconds: float, ppq: Optional[int] = None) -> float:
        """Return tick duration for a given length in seconds.

        If ``ppq`` is not supplied, a default of 480 is used so that callers can
        still obtain a deterministic value when no sequencer context is
        available.
        """

        if seconds <= 0:
            return 0
        bpm = float(self.base_tempo or 60.0)
        beats = (seconds * bpm) / 60.0
        effective_ppq = 480 if ppq is None else ppq
        return beats * effective_ppq
