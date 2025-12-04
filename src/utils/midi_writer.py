from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class MidiEvent:
    """Simple representation of a MIDI event for testing and composition."""

    type: str
    tick: int
    data: Dict[str, int] = field(default_factory=dict)


class MidiTrack:
    """Minimal MidiTrack storing events for later inspection."""

    def __init__(self, channel: Optional[int] = None):
        self.channel = channel
        self.events: List[MidiEvent] = []
        self.name: Optional[str] = None
        self.program: Optional[int] = None

    def add_note(self, pitch: int, velocity: int, start_tick: int, duration_ticks: int):
        self.events.append(
            MidiEvent(
                "note",
                start_tick,
                {"pitch": int(pitch), "velocity": int(velocity), "duration": int(duration_ticks)},
            )
        )

    def add_cc(self, controller: int, value: int, tick: int):
        self.events.append(
            MidiEvent("cc", tick, {"controller": int(controller), "value": int(value)})
        )

    def add_pitch_bend(self, value: int, tick: int):
        self.events.append(MidiEvent("pitch_bend", tick, {"value": int(value)}))

    def add_pitch_bend_cents(self, cents: float, tick: int):
        self.events.append(MidiEvent("pitch_bend_cents", tick, {"cents": float(cents)}))

    def set_name(self, name: str):
        self.name = name

    def set_program(self, program: int):
        self.program = int(program)


class MidiWriter:
    """Minimal MidiWriter that hands out MidiTrack instances by channel."""

    def __init__(self, ppq: int = 480):
        self._ppq = int(ppq)
        self._tracks: Dict[int, MidiTrack] = {}

    def get_track(self, channel: int) -> MidiTrack:
        if channel not in self._tracks:
            self._tracks[channel] = MidiTrack(channel=channel)
        return self._tracks[channel]

    @property
    def ppq(self) -> int:
        return self._ppq
