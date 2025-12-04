from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List


@dataclass
class InstrumentProfile:
    name: str = ""
    channel: int = 0
    program: int = 0
    scale_family: str = "diatonic"
    rhythm_mode: str = "rubato"
    articulation: str = "sustained"
    melody_master_intensity: float = 0.6
    register: List[int] = field(default_factory=lambda: [60, 84])
    legato: float = 0.95
    phrase_rest_prob: float = 0.4
    humanize_ms: int = 15
    enable_ghosts: bool = False
    ghost_prob: float = 0.3
    scale_mode: str = "diatonic"
    breath_phrasing: bool = False
    melody_breath_amount: float = 1.0
    melody_arc_rest_bias: float = 1.0
    melody_breakdown_mode: str = "soft"
    flute_ornament_mode: bool = False
    ornament_grace_prob: float = 0.35
    ornament_octave_jump_prob: float = 0.18
    velocity: int = 70
    user_data: Any = None
