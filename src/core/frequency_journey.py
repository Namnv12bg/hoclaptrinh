from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class FrequencyStage:
    """Represents a transposition stage.

    Attributes:
        start_tick: The starting tick for this stage.
        end_tick: The tick where this stage stops being active. If None, it remains active indefinitely.
        shift_semitones: The semitone offset applied during this stage.
    """

    start_tick: int
    end_tick: Optional[int] = None
    shift_semitones: int = 0


class FrequencyJourney:
    """Timeline of transposition stages used by DynamicTransposingTrack."""

    def __init__(self, stages: Optional[List[FrequencyStage]] = None, enabled: bool = True):
        self.stages: List[FrequencyStage] = stages or []
        self.enabled = enabled

    def add_stage(self, stage: FrequencyStage):
        self.stages.append(stage)
        self.stages.sort(key=lambda st: st.start_tick)

    def get_stage_at_tick(self, tick: int) -> Optional[FrequencyStage]:
        for stage in self.stages:
            in_lower_bound = tick >= stage.start_tick
            in_upper_bound = stage.end_tick is None or tick < stage.end_tick
            if in_lower_bound and in_upper_bound:
                return stage
        return None
