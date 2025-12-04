from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class MelodyNote:
    pitch: int
    start_tick: int
    duration_ticks: int
    velocity: int
    kind: str = "main"


class MelodyGenerator:
    def __init__(self, ppq: int, user_options: Dict[str, Any]):
        self.ppq = ppq
        self.user_options = user_options

    def generate_full_melody(self, segments: List[Any], key: str, scale: str) -> List[MelodyNote]:
        return []
