from __future__ import annotations

from typing import List, Tuple


class ActivityMap:
    def __init__(self):
        self.activities: List[Tuple[int, int, float]] = []

    def add_activity(self, start_tick: int, duration: int, weight: float = 1.0) -> None:
        self.activities.append((start_tick, duration, weight))
