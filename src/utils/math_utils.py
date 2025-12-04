from __future__ import annotations

import math
from typing import Tuple


PITCH_BEND_CENTER = 8192
PITCH_BEND_RANGE = 2  # semitones
PITCH_BEND_MIN = 0
PITCH_BEND_MAX = 16383


def freq_to_midi_pitch_bend(freq: float) -> Tuple[int, int]:
    """Convert a frequency to a MIDI note and pitch-bend value.

    The calculation assumes a pitch-bend range of ±2 semitones. The
    returned note is the nearest MIDI note, while the bend value adjusts
    the note toward the exact frequency.
    """
    freq = max(freq, 1e-6)
    midi_note = 69 + 12 * math.log2(freq / 440.0)
    rounded_note = int(round(midi_note))

    # compute difference in semitones between desired and rounded note
    note_freq = 440.0 * (2 ** ((rounded_note - 69) / 12))
    semitone_delta = 12 * math.log2(freq / note_freq)

    bend_ratio = semitone_delta / float(PITCH_BEND_RANGE)
    bend_value = int(PITCH_BEND_CENTER + bend_ratio * PITCH_BEND_CENTER)
    bend_value = max(PITCH_BEND_MIN, min(PITCH_BEND_MAX, bend_value))

    return rounded_note, bend_value
