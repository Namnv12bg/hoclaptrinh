from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class MidiEvent:
    tick: int
    event_type: str
    payload: Dict[str, Any]


@dataclass
class Track:
    channel: int
    events: List[MidiEvent] = field(default_factory=list)

    def add_pitch_bend(self, tick: int, value: int) -> None:
        self.events.append(MidiEvent(tick, "pitch_bend", {"value": value}))

    def add_note(self, note: int, velocity: int, start_tick: int, duration: int) -> None:
        self.events.append(
            MidiEvent(
                start_tick,
                "note_on",
                {"note": note, "velocity": velocity, "duration": duration},
            )
        )

    def add_cc(self, tick: int, controller: int, value: int) -> None:
        self.events.append(
            MidiEvent(tick, "cc", {"controller": controller, "value": value})
        )


class MidiWriter:
    """A lightweight MIDI-like writer used for testing.

    The writer stores Track objects that record events so tests can
    inspect how the engine schedules notes, pitch bends, and CC values.
    This is intentionally minimal and does not attempt to emit real MIDI
    data.
    """

    def __init__(self, ppq: int = 480) -> None:
        self.ppq = ppq
        self._tracks: Dict[int, Track] = {}

    def get_track(self, channel: int) -> Track:
        if channel not in self._tracks:
            self._tracks[channel] = Track(channel)
        return self._tracks[channel]
