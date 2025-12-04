"""Lightweight MIDI writer stubs used by the pulse engine examples.

The real project likely serializes events to MIDI files, but for the purposes
of tests and local experimentation we only need to keep track of what would
have been written.  These classes provide a minimal, in-memory representation
of tracks and notes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class MidiNote:
    """A single MIDI note event."""

    pitch: int
    velocity: int
    start_tick: int
    duration_ticks: int


class MidiTrack:
    """Represents a MIDI track and collects note events."""

    def __init__(self, track_number: int) -> None:
        self.track_number = track_number
        self.name: str = f"Track {track_number}"
        self.program: int | None = None
        self.notes: List[MidiNote] = []

    def set_name(self, name: str) -> None:
        self.name = name

    def set_program(self, program: int) -> None:
        self.program = program

    def add_note(self, pitch: int, velocity: int, start_tick: int, duration_ticks: int) -> None:
        """Store a note event for later inspection or serialization."""

        note = MidiNote(pitch=pitch, velocity=velocity, start_tick=start_tick, duration_ticks=duration_ticks)
        self.notes.append(note)


class MidiWriter:
    """Container for MIDI tracks.

    In a full implementation this would handle timing, tempo maps, and writing
    files.  Here it simply returns :class:`MidiTrack` instances keyed by track
    number.
    """

    def __init__(self) -> None:
        self.tracks: Dict[int, MidiTrack] = {}

    def get_track(self, track_number: int) -> MidiTrack:
        if track_number not in self.tracks:
            self.tracks[track_number] = MidiTrack(track_number)
        return self.tracks[track_number]
