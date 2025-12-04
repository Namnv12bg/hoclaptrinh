"""Lightweight Zen arc definitions used for tests and demos."""
from dataclasses import dataclass
from typing import List


@dataclass
class ZenPhaseDefinition:
    name: str
    index: int
    base_energy: float
    movement_bias: float


class ZenArcMatrix:
    """Simple evenly split arc over five phases.

    The real system exposes a configurable energy curve; here we keep a compact
    deterministic implementation that still provides meaningful values for
    StructureBuilder.
    """

    def __init__(self, user_options=None):
        self.user_options = user_options or {}
        self.phases: List[ZenPhaseDefinition] = [
            ZenPhaseDefinition("grounding", 1, 0.2, 0.2),
            ZenPhaseDefinition("immersion", 2, 0.4, 0.4),
            ZenPhaseDefinition("breakdown", 3, 0.3, 0.2),
            ZenPhaseDefinition("awakening", 4, 0.8, 0.8),
            ZenPhaseDefinition("integration", 5, 0.25, 0.3),
        ]

    def get_phase_by_ratio(self, ratio: float) -> ZenPhaseDefinition:
        clamped = max(0.0, min(1.0, float(ratio)))
        if clamped >= 1.0:
            return self.phases[-1]
        segment = int(clamped * len(self.phases))
        if segment >= len(self.phases):
            segment = len(self.phases) - 1
        return self.phases[segment]
