# Tệp: src/utils/midi_writer.py
# (FINAL V10.10.0) - SAFE DURATION + PITCH BEND RANGE + CENTS HELPERS
#
# Mục tiêu:
# - Giữ nguyên hành vi V9: Note/CC/Program/Pitch Bend an toàn.
# - Chuẩn hoá mapping Pitch Bend 0..16383 -> -8192..8191 (Mido).
# - Bổ sung helper cho phase sau:
#   + Tính pitch bend theo cents với giả định pitch bend range (± semitone).
#   + Cho phép DynamicTransposingWriter dùng để retune toàn bài (global cents).

import mido
import mido.backends.rtmidi
from typing import Dict, Optional, List

# Fallback import an toàn
try:
    from src.core.tempo_breath import TempoMap
except ImportError:
    class TempoMap:
        pass


class MidiTrack:
    def __init__(self, mido_track: mido.MidiTrack, channel: int):
        self.mido_track = mido_track
        self.channel = channel
        self.events: List[Dict] = []
        self.mido_track.append(
            mido.MetaMessage("track_name", name=f"Channel {channel}", time=0)
        )

    def set_name(self, name: str):
        found = False
        for msg in self.mido_track:
            if msg.type == "track_name":
                msg.name = name
                found = True
                break
        if not found:
            self.mido_track.append(
                mido.MetaMessage("track_name", name=name, time=0)
            )

    def _add_event(self, tick: int, message: mido.Message):
        if hasattr(message, "channel") and message.channel is None:
            message.channel = self.channel
        self.events.append({"tick": int(tick), "message": message})

    def add_note(self, pitch: int, velocity: int, start_tick: int, duration_ticks: int):
        # --- FIX: đảm bảo duration_ticks luôn là số hợp lệ ---
        start_tick = int(start_tick)

        if duration_ticks is None:
            duration_ticks = 1
        try:
            duration_ticks = int(duration_ticks)
        except (TypeError, ValueError):
            duration_ticks = 1
        if duration_ticks <= 0:
            duration_ticks = 1
        # -----------------------------------------------------

        pitch = max(0, min(127, int(pitch)))
        velocity = max(1, min(127, int(velocity)))

        self._add_event(
            start_tick,
            mido.Message(
                "note_on",
                note=pitch,
                velocity=velocity,
                channel=self.channel,
            ),
        )
        self._add_event(
            start_tick + duration_ticks,
            mido.Message(
                "note_off",
                note=pitch,
                velocity=0,
                channel=self.channel,
            ),
        )

    def add_cc(self, tick: int, control: int, value: int):
        self._add_event(
            int(tick),
            mido.Message(
                "control_change",
                control=control,
                value=max(0, min(127, int(value))),
                channel=self.channel,
            ),
        )

    # [QUAN TRỌNG] Đã đổi tên hàm từ add_pitchbend -> add_pitch_bend để khớp với các Engine
    def add_pitch_bend(self, tick: int, bend_value: int):
        """
        Thêm Pitch Bend với đầu vào 0..16383 (unsigned 14-bit).

        - 0    -> -8192 (full down)
        - 8192 -> 0     (center)
        - 16383-> +8191 (full up)
        """
        # 1. Kẹp giá trị đầu vào (0-16383)
        safe_val = max(0, min(16383, int(bend_value)))

        # 2. Chuyển sang hệ có dấu (-8192..8191)
        mido_val = safe_val - 8192

        # 3. Kẹp lại lần cuối cho chắc chắn (Mido strict check)
        if mido_val < -8192:
            mido_val = -8192
        if mido_val > 8191:
            mido_val = 8191

        self._add_event(
            int(tick),
            mido.Message("pitchwheel", pitch=mido_val, channel=self.channel),
        )

    # Helper mới: pitch bend theo cents + pitch bend range (± semitone)
    def add_pitch_bend_cents(
        self,
        tick: int,
        cents: float,
        bend_range_semitones: float = 2.0,
    ):
        """
        Thêm Pitch Bend theo đơn vị cents.

        Giả định:
        - pitch bend range = ±bend_range_semitones (thường là ±2)
        - cents có thể âm/dương (vd: +25.0, -15.0)

        Công thức:
        - semitones = cents / 100
        - ratio     = semitones / bend_range_semitones  (clamp -1..1)
        - unsigned  = 8192 + ratio * 8192  (0..16383)
        """
        try:
            br = float(bend_range_semitones)
        except (TypeError, ValueError):
            br = 2.0
        if br <= 0:
            # Không xác định được range -> bỏ qua để tránh gửi bend lỗi
            return

        try:
            cents_val = float(cents)
        except (TypeError, ValueError):
            cents_val = 0.0

        semitones = cents_val / 100.0
        ratio = semitones / br

        # Clamp ratio trong [-1, 1]
        if ratio < -1.0:
            ratio = -1.0
        if ratio > 1.0:
            ratio = 1.0

        # 8192 là center, mỗi phía 8192 "step"
        unsigned_val = int(round(8192 + ratio * 8192.0))
        # Đảm bảo trong [0, 16383]
        if unsigned_val < 0:
            unsigned_val = 0
        if unsigned_val > 16383:
            unsigned_val = 16383

        self.add_pitch_bend(tick, unsigned_val)

    def set_program(self, program: int, tick: int = 0):
        self._add_event(
            int(tick),
            mido.Message(
                "program_change",
                program=max(0, min(127, int(program))),
                channel=self.channel,
            ),
        )

    def finalize(self):
        if not self.events:
            return
        self.events.sort(key=lambda e: e["tick"])

        last_tick = 0
        for event in self.events:
            delta_tick = event["tick"] - last_tick
            if delta_tick < 0:
                delta_tick = 0

            event["message"].time = delta_tick
            self.mido_track.append(event["message"])
            last_tick = event["tick"]


class MidiWriter:
    def __init__(self, ppq: int = 480, tempo_map: Optional[TempoMap] = None):
        self.ppq = ppq
        self.mido_file = mido.MidiFile(ticks_per_beat=ppq)
        self.tempo_map = tempo_map

        # Giả định mặc định pitch bend range là ±2 semitone (có thể override nếu cần)
        self.pitch_bend_range_semitones: float = 2.0

        self.meta_track = self.mido_file.add_track()
        self.meta_track.append(
            mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0)
        )

        self.tracks_by_channel: Dict[int, MidiTrack] = {}

    def get_track(self, channel: int) -> MidiTrack:
        if channel not in self.tracks_by_channel:
            new_mido_track = self.mido_file.add_track()
            wrapper_track = MidiTrack(new_mido_track, channel)
            self.tracks_by_channel[channel] = wrapper_track

        return self.tracks_by_channel[channel]

    def set_pitch_bend_range(self, semitones: float):
        """
        Đặt pitch bend range mặc định (±semitones) để các helper sử dụng.
        Ví dụ: writer.set_pitch_bend_range(2.0)
        """
        try:
            br = float(semitones)
        except (TypeError, ValueError):
            br = 2.0
        if br <= 0:
            br = 2.0
        self.pitch_bend_range_semitones = br

    def _apply_tempo_map(self):
        if not self.tempo_map or not getattr(self.tempo_map, "events", None):
            # Default 60 BPM nếu không có tempo_map
            self.meta_track.append(
                mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(60), time=0)
            )
            return

        self.tempo_map.events.sort(key=lambda e: e.tick)
        last_tick = 0
        for event in self.tempo_map.events:
            delta_tick = event.tick - last_tick
            if delta_tick < 0:
                delta_tick = 0

            self.meta_track.append(
                mido.MetaMessage(
                    "set_tempo",
                    tempo=event.microseconds_per_beat,
                    time=delta_tick,
                )
            )
            last_tick = event.tick

    def finalize(self) -> mido.MidiFile:
        self._apply_tempo_map()
        for _channel, track in self.tracks_by_channel.items():
            track.finalize()
        return self.mido_file
