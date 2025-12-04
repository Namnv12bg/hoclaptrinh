"""Lightweight music theory helpers for pitch-class calculations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


_NOTE_TO_PC = {
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

_SCALE_INTERVALS = {
    "MAJOR": [0, 2, 4, 5, 7, 9, 11],
    "MINOR": [0, 2, 3, 5, 7, 8, 10],
    "DORIAN": [0, 2, 3, 5, 7, 9, 10],
    "PHRYGIAN": [0, 1, 3, 5, 7, 8, 10],
    "LYDIAN": [0, 2, 4, 6, 7, 9, 11],
    "MIXOLYDIAN": [0, 2, 4, 5, 7, 9, 10],
    "LOCRIAN": [0, 1, 3, 5, 6, 8, 10],
}


@dataclass
class Scale:
    """Represents a musical scale for computing allowed pitch classes."""

    key: str
    scale: str

    def _root_pc(self) -> Optional[int]:
        normalized = self.key.strip().upper()
        return _NOTE_TO_PC.get(normalized)

    def _intervals(self) -> Optional[List[int]]:
        normalized = self.scale.strip().upper()
        return _SCALE_INTERVALS.get(normalized)

    def get_pitch_classes(self) -> List[int]:
        """Return pitch classes for the configured key/scale.

        Empty list is returned when either the key or scale is unknown.
        """

        root = self._root_pc()
        intervals = self._intervals()
        if root is None or intervals is None:
            return []

        return [int((root + interval) % 12) for interval in intervals]
