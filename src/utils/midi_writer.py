from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class MidiTrack:
    channel: int
    name: str = ""
    program: int = 0
    notes: List[Tuple[int, int, int, int]] = field(default_factory=list)
    ccs: List[Tuple[int, int, int]] = field(default_factory=list)

    def set_name(self, name: str) -> None:
        self.name = name

    def set_program(self, program: int) -> None:
        self.program = program

    def add_note(self, note: int, velocity: int, start_tick: int, duration: int) -> None:
        self.notes.append((note, velocity, start_tick, duration))

    def add_cc(self, tick: int, controller: int, value: int) -> None:
        self.ccs.append((tick, controller, value))


class MidiWriter:
    def __init__(self, ppq: int = 480):
        self.ppq = ppq
        self.tracks = {}

    def get_track(self, channel: int) -> MidiTrack:
        if channel not in self.tracks:
            self.tracks[channel] = MidiTrack(channel)
        return self.tracks[channel]
