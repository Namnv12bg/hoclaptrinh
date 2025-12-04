from __future__ import annotations

from typing import Optional


class ActivityMap:
    def __init__(self):
        self.events = []

    def get_activity_for_layer(self, layer: str, start_tick: int, end_tick: int) -> float:
        return 0.0

    def get_activity(self, start_tick: int, end_tick: int, layer: Optional[str] = None) -> float:
        return 0.0

    def commit_event(self, layer: str, start_tick: int, duration_ticks: int, weight: float = 1.0) -> None:
        self.events.append((layer, start_tick, duration_ticks, weight))

    def add_activity(self, start_tick: int, duration_ticks: int) -> None:
        self.events.append((start_tick, duration_ticks))
