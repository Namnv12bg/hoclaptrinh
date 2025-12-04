from __future__ import annotations

from typing import Dict


class MidiTrack:
    def __init__(self, channel: int):
        self.channel = channel
        self.notes = []

    def add_note(self, pitch: int, velocity: int, start_tick: int, duration: int) -> None:
        self.notes.append(
            {
                "pitch": pitch,
                "velocity": velocity,
                "start_tick": start_tick,
                "duration": duration,
            }
        )


class MidiWriter:
    def __init__(self, ppq: int = 480):
        self.ppq = ppq
        self._tracks: Dict[int, MidiTrack] = {}

    def get_track(self, channel: int) -> MidiTrack:
        if channel not in self._tracks:
            self._tracks[channel] = MidiTrack(channel)
        return self._tracks[channel]
