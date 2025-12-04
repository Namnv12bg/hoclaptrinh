"""Minimal pulse generator used for testing the PulseEngineV10 wrapper."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from src.core.structure_builder import Segment


@dataclass
class PulseNote:
    pitch: int
    velocity: int
    start_tick: int
    duration_ticks: int
    channel: int = 0
    section_type: str | None = None
    energy_bias: float | None = None
    t_norm: float | None = None


class PulseGenerator:
    """Generate placeholder pulse patterns.

    The implementation is intentionally simple but deterministic: each segment
    yields a heartbeat note on channel 0 and a texture note on channel 1.
    """

    def __init__(self, ppq: int, user_options: dict | None = None) -> None:
        self.ppq = ppq
        self.user_options = user_options or {}

    def generate_full_pulse(self, segments: List[Segment], key: str, scale: str) -> List[PulseNote]:
        notes: List[PulseNote] = []
        for idx, segment in enumerate(segments):
            intensity = max(0.1, float(segment.intensity))
            base_tick = int(segment.start_tick)
            duration = max(int(segment.duration_ticks // 2), 1)

            # Heartbeat
            hb_pitch = int(self.user_options.get("heartbeat_pitch", 36))
            hb_velocity = int(80 * intensity)
            notes.append(
                PulseNote(
                    pitch=hb_pitch,
                    velocity=hb_velocity,
                    start_tick=base_tick,
                    duration_ticks=duration,
                    channel=0,
                    section_type="segment",
                    t_norm=idx / max(len(segments), 1),
                )
            )

            # Texture / Kalimba
            tex_pitch = int(self.user_options.get("texture_pitch", 72))
            tex_velocity = int(70 * intensity)
            notes.append(
                PulseNote(
                    pitch=tex_pitch,
                    velocity=tex_velocity,
                    start_tick=base_tick + max(self.ppq // 4, 1),
                    duration_ticks=duration,
                    channel=1,
                    section_type="segment",
                    t_norm=idx / max(len(segments), 1),
                )
            )

        return notes
