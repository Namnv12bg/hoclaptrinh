# Tệp: src/core/tempo_breath.py
# (FINAL V10.0) - UNLOCK VARIABLE BREATH CYCLES
# Features:
# - Cho phép chu kỳ thở biến thiên theo số bar (1 bar = Flow, 2 bar = Deep, v.v.).
# - TempoMap có breath_cycle_bars để các Engine khác (Binaural, Chime, Pulse...) dùng lại.

import math
import mido
from dataclasses import dataclass

@dataclass
class TempoEvent:
    tick: int
    bpm: float
    microseconds_per_beat: int

class TempoMap:
    def __init__(self, ppq: int):
        # PPQ (ticks per quarter note)
        self.ppq = ppq if ppq > 0 else 480
        self.events: list[TempoEvent] = []
        self.base_bpm: float = 60.0
        # [FIX] Dynamic breath cycle support (để get_phase_at_bar dùng đúng)
        self.breath_cycle_bars: float = 1.0

    def add_event(self, tick: int, bpm: float):
        if bpm <= 0:
            bpm = 60.0
        try:
            micros = mido.bpm2tempo(bpm)
        except Exception:
            micros = mido.bpm2tempo(60)

        self.events.append(TempoEvent(int(tick), bpm, int(micros)))
        if tick == 0:
            self.base_bpm = bpm

    def get_average_bpm(self) -> float:
        if not self.events:
            return self.base_bpm
        return sum(e.bpm for e in self.events) / len(self.events)

    def get_ticks_for_duration(self, duration_seconds: float) -> int:
        """
        Ước tính số tick tương ứng với duration_seconds dựa trên BPM trung bình.
        Dùng cho các Engine muốn convert giây -> tick.
        """
        avg_bpm = self.get_average_bpm()
        if avg_bpm <= 0:
            avg_bpm = 60.0
        ticks_per_sec = (avg_bpm / 60.0) * self.ppq
        return int(duration_seconds * ticks_per_sec)

    def get_bar_pos_at_tick(self, tick: int) -> float:
        """
        Trả về "vị trí bar" (đơn vị: số bar) tại tick cho trước.
        Giả định nhịp 4/4: 1 bar = 4 beat.
        """
        ticks_per_bar = self.ppq * 4.0
        if ticks_per_bar <= 0:
            return 0.0
        return tick / ticks_per_bar

    def get_phase_at_bar(self, bar_pos: float) -> float:
        """
        Trả về pha (rad) của LFO hơi thở tại một vị trí bar cụ thể.
        - Thay vì luôn dùng 1 bar/chu kỳ, dùng self.breath_cycle_bars để:
          + 1.0  -> 1 bar / chu kỳ thở (Flow)
          + 2.0  -> 2 bar / chu kỳ thở (Deep)
        """
        # [CRITICAL] Use actual cycle, not hardcoded 1.0
        cycle = self.breath_cycle_bars
        if cycle <= 0:
            cycle = 1.0
        local = (bar_pos / cycle) % 1.0
        return 2.0 * math.pi * local

class TempoBreath:
    """
    Generator tạo TempoMap có "nhịp thở" (breathing tempo LFO).

    base_tempo: BPM trung bình (60 là kinh điển cho thiền).
    cycle_bars: số bar cho 1 chu kỳ thở (1.0, 2.0, 3.0...).
    depth_bpm: biên độ dao động quanh base_tempo (±depth_bpm).
    """

    def __init__(
        self,
        base_tempo: float = 60.0,
        ppq: int = 480,
        cycle_bars: float = 1.0,
        depth_bpm: float = 2.0,
    ):
        self.base_tempo = base_tempo
        self.ppq = ppq
        # [CRITICAL] Respect input cycle
        self.cycle_bars = float(cycle_bars) if cycle_bars > 0 else 1.0
        self.depth = depth_bpm

        # Giới hạn BPM để tránh cực đoan
        self.min_bpm = max(20.0, base_tempo - depth_bpm)
        self.max_bpm = min(200.0, base_tempo + depth_bpm)

    def generate_map(self, total_seconds: int) -> TempoMap:
        """
        Sinh ra TempoMap dài total_seconds (giây), với LFO thở:
        - Dạng cos: chậm ở đỉnh hít/thở, nhanh ở giữa.
        - Chu kỳ tính theo số bar (cycle_bars).
        """
        tempo_map = TempoMap(self.ppq)
        # Store cycle bars cho các Engine khác sử dụng khi cần
        tempo_map.breath_cycle_bars = self.cycle_bars

        # Ước tính tổng tick theo base_tempo
        ticks_per_sec = (self.base_tempo / 60.0) * self.ppq
        total_ticks = int(total_seconds * ticks_per_sec)
        if total_ticks <= 0:
            total_ticks = 1000

        # Bước lấy mẫu tempo (1 beat)
        step_ticks = self.ppq
        ticks_per_bar = self.ppq * 4.0

        for tick in range(0, total_ticks, step_ticks):
            bar_pos = tick / ticks_per_bar

            # Phase theo chu kỳ thở
            phase = (bar_pos / self.cycle_bars) % 1.0
            lfo = (1.0 - math.cos(phase * 2 * math.pi)) / 2.0  # 0..1

            bpm = self.min_bpm + (lfo * (self.max_bpm - self.min_bpm))
            tempo_map.add_event(tick, bpm)

        if not tempo_map.events:
            tempo_map.add_event(0, self.base_tempo)

        return tempo_map
