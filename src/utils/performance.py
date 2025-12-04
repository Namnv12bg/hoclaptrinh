"""Performance utilities for pulse rendering.

The real codebase likely performs sophisticated interaction with a melodic
activity map.  Here we provide a lightweight approximation that can reduce
velocities when the surrounding music is busy.
"""
from __future__ import annotations

from typing import Iterable, List

from src.core.pulse_generator import PulseNote
from src.utils.activity_map import ActivityMap


def apply_pulse_activity_trim(
    notes: Iterable[PulseNote],
    activity_map: ActivityMap,
    pulse_activity_threshold: float,
    pulse_reduction_ratio: float,
    melody_track_name: str | None = None,
) -> List[PulseNote]:
    """Reduce pulse velocities based on activity levels.

    Notes with activity at or above ``pulse_activity_threshold`` are scaled by
    ``pulse_reduction_ratio``.  If a note's velocity would be reduced below 1
    it is dropped entirely.
    """

    trimmed: List[PulseNote] = []
    for note in notes:
        try:
            activity = float(activity_map.get_activity_at_tick(int(note.start_tick)))
        except Exception:
            activity = 0.0

        if activity >= pulse_activity_threshold:
            scaled_velocity = int(note.velocity * pulse_reduction_ratio)
            if scaled_velocity < 1:
                continue
            note = PulseNote(
                pitch=note.pitch,
                velocity=scaled_velocity,
                start_tick=note.start_tick,
                duration_ticks=note.duration_ticks,
                channel=getattr(note, "channel", 0),
                section_type=getattr(note, "section_type", None),
                energy_bias=getattr(note, "energy_bias", None),
                t_norm=getattr(note, "t_norm", None),
            )
        trimmed.append(note)

    return trimmed
