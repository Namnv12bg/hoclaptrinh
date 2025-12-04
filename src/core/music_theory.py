from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

NOTE_MAP = {
    "C": 0,
    "C#": 1,
    "DB": 1,
    "D": 2,
    "D#": 3,
    "EB": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "GB": 6,
    "G": 7,
    "G#": 8,
    "AB": 8,
    "A": 9,
    "A#": 10,
    "BB": 10,
    "B": 11,
}


@dataclass
class Scale:
    key: str
    scale: str

    def __post_init__(self) -> None:
        self.root_pc = NOTE_MAP.get(self.key.upper(), 0)
        self.scale = self.scale.lower()

    def _intervals(self) -> List[int]:
        if "dorian" in self.scale:
            return [0, 2, 3, 5, 7, 9, 10]
        if "minor" in self.scale:
            return [0, 2, 3, 5, 7, 8, 10]
        return [0, 2, 4, 5, 7, 9, 11]

    def get_pitch_classes(self) -> Iterable[int]:
        intervals = self._intervals()
        for interval in intervals:
            yield (self.root_pc + interval) % 12


@dataclass
class Chord:
    chord_name: str
    key: str
    scale: str

    def __post_init__(self) -> None:
        self.chord_name = (self.chord_name or self.key or "C").strip()
        root_name = self.chord_name[:-1] if self.chord_name and self.chord_name[-1] in {"m", "M"} else self.chord_name
        if not root_name:
            root_name = self.key
        self.root_pc = NOTE_MAP.get(root_name.upper(), 0)

        minor = self.chord_name.lower().endswith("m")
        intervals = [0, 3, 7] if minor else [0, 4, 7]
        self.pcs = [(self.root_pc + i) % 12 for i in intervals]


def note_number(pc: int, octave: int) -> int:
    return int(pc + octave * 12)
