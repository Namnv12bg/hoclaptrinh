"""Minimal activity map placeholder.

The activity map normally exposes time-varying energy levels.  For our purposes
it stores a mapping from ticks to normalized activity values between 0 and 1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


@dataclass
class ActivityMap:
    """Look up energy levels at specific ticks."""

    activity_by_tick: Dict[int, float] = field(default_factory=dict)

    def get_activity_at_tick(self, tick: int) -> float:
        return _clamp(float(self.activity_by_tick.get(int(tick), 0.0)), 0.0, 1.0)

    def set_activity(self, tick: int, value: float) -> None:
        self.activity_by_tick[int(tick)] = _clamp(value, 0.0, 1.0)
