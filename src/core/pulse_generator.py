# Tệp: src/core/pulse_generator.py
# (FINAL V10.2.2) - BIO-SYNC PULSE (STRUCTURED + PL-READY)
# Features:
#   - Heartbeat (Grounding, channel=9)
#   - Kalimba / Texture (channel=1)
#   - Energy-aware density, chuẩn bị cho Performance Layer (ActivityMap trim ở zen_core).
#
# Lưu ý:
# - Trường "channel" của PulseNote được dùng bởi zen_core:
#       channel == 1  -> route sang track Texture ("8. HEART (Texture)")
#       channel != 1  -> route sang track Heartbeat ("7. HEART (Pulse)")

import random
from dataclasses import dataclass
from typing import Any, Dict, List

# Import core systems
from src.core.music_theory import Scale
from src.core.structure_builder import Segment


@dataclass
class PulseNote:
    start_tick: int
    duration_ticks: int
    pitch: int
    velocity: int
    channel: int  # 1 = Texture, 9 = Heartbeat (xem logic route ở zen_core)


class PulseGenerator:
    """
    V10.2.2 - Zen Pulse & Rhythmic Texture (PL-Ready)
    Tạo nhịp điệu sinh học (Heartbeat) và lớp phủ âm thanh (Kalimba/Texture).
    Phản ứng nhạy với Energy Bias; việc "nhường nhịn" Melody sẽ được
    xử lý ở Performance Layer (zen_core + ActivityMap).
    """

    def __init__(self, ppq: int = 480, user_options: Dict[str, Any] | None = None):
        self.ppq = ppq
        self.user_options = user_options or {}

        # Cấu hình kênh (Internal Logic)
        self.channel_heartbeat = 9
        self.channel_kalimba = 1

        # Cấu hình Pitch
        self.kick_pitch = 36  # C1 (Deep Kick/Heartbeat)
        self.base_vel_kalimba = 50

        # Humanize Config
        self.humanize_ticks = 15
        self.humanize_vel = 8

    def generate_full_pulse(
        self,
        segments: List[Segment],
        key: str,
        scale: str,
    ) -> List[PulseNote]:
        """
        API chính gọi từ bên ngoài (Zen Core).
        """
        full_pulse: List[PulseNote] = []
        for seg in segments:
            seg_pulse = self._generate_pulse_for_segment(seg, key, scale)
            full_pulse.extend(seg_pulse)
        return full_pulse

    def _generate_pulse_for_segment(
        self,
        segment: Segment,
        key: str,
        scale: str,
    ) -> List[PulseNote]:
        """
        Kết hợp Heartbeat (Rhythm) và Kalimba (Texture) cho 1 segment.
        """
        energy = getattr(segment, "energy_bias", 0.5)

        # Layer 1: Heartbeat (Kênh Drum/Bass)
        heartbeat_notes = self._generate_heartbeat(segment, energy)

        # Layer 2: Kalimba (Kênh Texture) - Cần key/scale để hòa âm
        kalimba_notes: List[PulseNote] = []
        # Chỉ đánh texture khi năng lượng đủ (tránh rác nốt ở đoạn Intro tĩnh lặng)
        if energy > 0.15:
            kalimba_notes = self._generate_kalimba(segment, energy, key, scale)

        # Trộn và sort theo thời gian
        all_notes = heartbeat_notes + kalimba_notes
        all_notes.sort(key=lambda n: n.start_tick)

        return all_notes

    def _generate_heartbeat(self, segment: Segment, energy: float) -> List[PulseNote]:
        """
        Tạo lớp nền nhịp tim (Grounding).
        """
        notes: List[PulseNote] = []
        start = segment.start_tick
        end = segment.end_tick

        # Logic Zen: Nhịp tim
        if energy < 0.3:
            # Deep Sleep: Rất thưa (1 Bar - 4 beats)
            step = self.ppq * 4
            prob = 0.8
            base_vel = 45
        elif energy < 0.7:
            # Calm: Nhịp 1/2 Bar (2 beats)
            step = self.ppq * 2
            prob = 0.9
            base_vel = 65
        else:
            # Awake: Nhịp 1/4 Bar (1 beat)
            step = self.ppq
            prob = 0.95
            base_vel = 80

        curr = start
        while curr < end:
            # Tránh nốt quá sát mép cuối
            if curr + 100 > end:
                break

            if random.random() < prob:
                # Humanize timing
                offset = random.randint(-self.humanize_ticks, self.humanize_ticks)
                actual_start = max(start, curr + offset)

                # Humanize velocity
                vel = base_vel + random.randint(-self.humanize_vel, self.humanize_vel)
                vel = max(1, min(127, vel))

                notes.append(
                    PulseNote(
                        start_tick=actual_start,
                        duration_ticks=int(self.ppq * 0.2),  # Short thump
                        pitch=self.kick_pitch,
                        velocity=vel,
                        channel=self.channel_heartbeat,
                    )
                )

            curr += step

        return notes

    def _generate_kalimba(
        self,
        segment: Segment,
        energy: float,
        key: str,
        scale: str,
    ) -> List[PulseNote]:
        """
        Tạo lớp texture (Kalimba/Bells) mang tính 'Tonal'.
        """
        notes: List[PulseNote] = []
        start = segment.start_tick
        end = segment.end_tick

        # Lấy scale notes
        scale_obj = Scale(key, scale)
        scale_pcs = scale_obj.get_pitch_classes()
        if not scale_pcs:
            return []

        # Logic Zen: Texture Density
        if energy < 0.3:
            density = 0.1
            grid_div = 1.0  # Quarter note
            oct_base = 4
        elif energy < 0.7:
            density = 0.3
            grid_div = 0.5  # 8th note
            oct_base = 5
        else:
            density = 0.6
            grid_div = 0.25  # 16th note
            oct_base = 5

        step = int(self.ppq * grid_div)
        curr = start

        while curr < end:
            if curr + step > end:
                break

            if random.random() < density:
                pc = random.choice(scale_pcs)
                # Random octave variation
                oct_offset = random.choice([0, 1])
                pitch = (oct_base + oct_offset) * 12 + pc
                pitch = max(0, min(127, pitch))

                # Velocity theo năng lượng
                vel = (
                    self.base_vel_kalimba
                    + int(energy * 30)
                    + random.randint(-10, 10)
                )
                vel = max(1, min(127, vel))

                offset = random.randint(-self.humanize_ticks, self.humanize_ticks)
                actual_start = max(start, curr + offset)

                notes.append(
                    PulseNote(
                        start_tick=actual_start,
                        duration_ticks=int(step * 0.8),  # Staccato
                        pitch=pitch,
                        velocity=vel,
                        channel=self.channel_kalimba,
                    )
                )

            curr += step

        return notes
