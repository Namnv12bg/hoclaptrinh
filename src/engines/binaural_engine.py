# Tệp: src/engines/binaural_engine.py
# (FINAL V11.0.3) - ZEN BINAURAL ENGINE V11 (BRAINWAVE JOURNEY SAFE-ACTIVATED)
#
# Base:
#   - (FINAL V10.6.0) - ZEN BINAURAL ENGINE (BREATH + BREAKDOWN + JOURNEY READY)
#   - (FINAL V9.9.70) - CONTINUOUS BINAURAL PATCHED
#
# Mục tiêu V11:
# - Giữ nguyên interface lịch sử:
#       eng = BinauralEngineV9(writer, prof)
#       eng.render(segments, render_freq, beat_hz, tempo_map, fade_cfg)
#
# - Phase 1 (SAFE):
#       + Không pitch toàn bài, chỉ tự tính pitch lớp binaural.
#       + Brainwave Journey chưa can thiệp thực sự vào beat Hz.
#
# - Phase 2 (V11.0.3 – SAFE ACTIVATED):
#       + Nếu profile.brainwave_mode == "journey" và có BrainwaveJourney:
#           * beat Hz sẽ thay đổi dọc timeline theo t_norm (0..1).
#           * Thay đổi được hiện thực bằng pitch-bend L/R, không đụng tới nhạc cụ khác.
#       + Nếu brainwave_mode != "journey" hoặc không có Journey:
#           * Hành vi giữ nguyên như V11.0.2 (beat Hz cố định).
#
# - Nâng cấp chung:
#       + TuningCoreV3-ready:
#           * Nếu có TuningPlan -> ưu tiên anchor từ Solf Hz (primary/secondary).
#           * Nếu không -> fallback base_freq như V9/V10.
#       + Breath-linked envelope theo TempoMap (CC11 cho L/R).
#       + Breakdown-aware: mỏng / tắt ở đoạn Bridge/Breakdown.
#       + Master mix_level từ profile.v9_mix_level.
#
# Lưu ý:
# - Khi không có TuningPlan/BrainwaveJourney, engine chạy như engine V10.6/V11.0.2 (safe fallback).
# - Brainwave Journey chỉ tác động lớp binaural, không pitch toàn bài.

from __future__ import annotations

import math
from typing import List, Optional, Dict, Any

from src.utils.midi_writer import MidiWriter
from src.core.tempo_breath import TempoMap
from src.core.structure_builder import Segment
from src.utils.math_utils import freq_to_midi_pitch_bend

# Optional types cho TuningCore & Brainwave Journey (không bắt buộc phải có khi import)
try:  # pragma: no cover
    from src.core.tuning_core import TuningPlan
except Exception:  # pragma: no cover
    TuningPlan = None  # type: ignore[misc]

try:  # pragma: no cover
    from src.core.brainwave_journey import BrainwaveJourney
except Exception:  # pragma: no cover
    BrainwaveJourney = None  # type: ignore[misc]


class BinauralEngine:
    """
    Zen Binaural Engine V11

    - Tạo lớp BINAURAL (hai kênh L/R lệch tần số nhỏ → beat Hz).
    - Dùng 1 anchor frequency (Hz) + beat_hz để tính left/right tone.
    - Envelope theo nhịp thở (TempoMap) + Breakdown-aware.
    - TuningCoreV3-ready: anchor có thể đến từ TuningPlan (primary Solf).
    """

    def __init__(
        self,
        writer: MidiWriter,
        profile,
        user_options: Optional[Dict[str, Any]] = None,
        # Các tham số “não Zen” – để khớp với cách gọi từ Zen Core, hiện chưa dùng mạnh
        safety_filter: Optional[Any] = None,
        register_manager: Optional[Any] = None,
        breath_sync: Optional[Any] = None,
        activity_map: Optional[Any] = None,
        zen_arc_matrix: Optional[Any] = None,
        layer_name: str = "binaural",
    ) -> None:
        self.writer = writer
        self.ppq = writer.ppq
        self.profile = profile
        self.user_options = user_options or {}

        # Giữ tham chiếu để tương lai có thể dùng (Phase 2/3)
        self.safety_filter = safety_filter
        self.register_manager = register_manager
        self.breath_sync = breath_sync
        self.activity_map = activity_map
        self.zen_arc_matrix = zen_arc_matrix
        self.layer_name = layer_name or "binaural"

        # Channel L/R – cho phép cấu hình qua profile, fallback mặc định
        left_ch = int(getattr(profile, "binaural_left_channel", 14))
        right_ch = int(getattr(profile, "binaural_right_channel", 15))

        self.track_left = writer.get_track(left_ch)
        self.track_right = writer.get_track(right_ch)

        # Mix level tổng (0..1) – nhân vào velocity/CC
        self.mix_level = float(getattr(profile, "v9_mix_level", 0.8))
        self.mix_level = max(0.0, min(1.0, self.mix_level))

        # Velocity cơ bản
        base_vel = int(getattr(profile, "velocity", 60))
        self.base_velocity = max(1, min(127, base_vel))

        # Brainwave Journey mode
        self.brainwave_mode = str(
            getattr(profile, "brainwave_mode", "steady") or "steady"
        ).lower()

        self.brainwave_end_beat_hz = float(
            getattr(profile, "brainwave_end_beat_hz", 4.0)
        )

        # Breakdown-thin factor: giảm cường độ ở Bridge/Breakdown
        self.breakdown_thin_factor = float(
            getattr(profile, "breakdown_thin_factor", 0.45)
        )
        self.breakdown_thin_factor = max(0.0, min(1.0, self.breakdown_thin_factor))

        # Depth của NHỊP THỞ trên CC11 (envelope)
        self.breath_depth = int(getattr(profile, "breath_depth", 20))
        self.breath_depth = max(0, min(60, self.breath_depth))

        # Step khi vẽ CC (ticks)
        self.cc_step_ticks = max(1, self.ppq // 2)

    # ------------------------------------------------------------------
    # Helpers chọn anchor freq & beat Hz
    # ------------------------------------------------------------------

    def _pick_anchor_freq(
        self,
        tuning_plan: Optional["TuningPlan"],
        base_freq: float,
    ) -> float:
        """
        Chọn anchor frequency cho binaural:

        - Nếu có TuningPlan:
            + Ưu tiên primary_solf_hz (Mode 2/3/4).
            + Nếu không có, thử secondary_solf_hz.
        - Nếu không có gì -> fallback base_freq (behavior cũ).
        """
        try:
            if tuning_plan is not None and TuningPlan is not None:
                primary = float(getattr(tuning_plan, "primary_solf_hz", 0.0) or 0.0)
                secondary = float(
                    getattr(tuning_plan, "secondary_solf_hz", 0.0) or 0.0
                )
                if primary > 0.0:
                    return primary
                if secondary > 0.0:
                    return secondary
        except Exception:
            pass

        # Fallback an toàn
        return float(base_freq or 0.0) if base_freq and base_freq > 0 else 432.0

    def _pick_beat_hz_base(
        self,
        base_beat_hz: float,
    ) -> float:
        """
        Chọn beat Hz nền (static):

        - Nếu base_beat_hz <= 0 -> 4.0 Hz (delta nhẹ).
        - Đây là giá trị default dùng khi:
            + Không bật Brainwave Journey
            + Hoặc brainwave_mode != "journey"
        """
        beat = float(base_beat_hz or 0.0)
        return beat if beat > 0 else 4.0

    def _beat_hz_from_journey_tnorm(
        self,
        t_norm: float,
        base_beat_hz: float,
        brainwave_journey: Optional["BrainwaveJourney"],
    ) -> float:
        """
        Lấy beat Hz theo t_norm (0..1) từ BrainwaveJourney nếu có.
        """
        base = self._pick_beat_hz_base(base_beat_hz)

        if brainwave_journey is None:
            return base

        # Case 1: đúng class BrainwaveJourney
        if BrainwaveJourney is not None and isinstance(brainwave_journey, BrainwaveJourney):
            try:
                fn = getattr(brainwave_journey, "get_smooth_beat_hz_for_t_norm", None)
                if not callable(fn):
                    fn = getattr(brainwave_journey, "get_beat_hz_for_t_norm", None)
                if callable(fn):
                    val = fn(float(t_norm), float(base))
                    if val and val > 0:
                        return float(val)
            except Exception:
                return base

        # Case 2: dict-like
        try:
            if isinstance(brainwave_journey, dict):
                if not brainwave_journey.get("enabled", False):
                    return base

                stages = brainwave_journey.get("stages", [])
                if not stages:
                    return base

                t = max(0.0, min(1.0, float(t_norm)))

                cum = 0.0
                chosen = None
                for stg in stages:
                    dur = float(stg.get("duration_pct", 0.0) or 0.0)
                    if dur <= 0:
                        continue
                    cum_next = cum + dur
                    if t <= cum_next + 1e-6:
                        chosen = stg
                        break
                    cum = cum_next

                if chosen is None:
                    chosen = stages[-1]

                stage_beat = float(chosen.get("beat_hz", 0.0) or 0.0)
                return stage_beat if stage_beat > 0 else base

        except Exception:
            return base

        return base

    # ------------------------------------------------------------------
    # Public render
    # ------------------------------------------------------------------

    def render(
        self,
        segments: List[Segment],
        base_freq: float,
        base_beat_hz: float,
        tempo_map: Optional[TempoMap],
        fade_cfg: Optional[Dict[str, int]] = None,
        *,
        tuning_plan: Optional["TuningPlan"] = None,
        brainwave_journey: Optional["BrainwaveJourney"] = None,
        **kwargs: Any,
    ) -> None:

        if not segments or tempo_map is None:
            return

        total_ticks = segments[-1].end_tick
        if total_ticks <= 0:
            return

        start_tick = segments[0].start_tick

        # 1) Anchor freq
        anchor_hz = self._pick_anchor_freq(tuning_plan, base_freq)

        # 2) Beat Hz base
        base_beat = self._pick_beat_hz_base(base_beat_hz)
        base_beat = max(0.1, min(40.0, base_beat))

        # 3) Tính freq L/R ban đầu
        left_hz = max(1.0, anchor_hz - base_beat / 2)
        right_hz = anchor_hz + base_beat / 2

        left_note, left_bend = freq_to_midi_pitch_bend(left_hz)
        right_note, right_bend = freq_to_midi_pitch_bend(right_hz)

        base_vel = int(self.base_velocity * self.mix_level)
        base_vel = max(1, min(127, base_vel))

        sustain_dur = total_ticks - start_tick + int(self.ppq * 4)

        # Pitch-bend ban đầu
        self.track_left.add_pitch_bend(start_tick, left_bend)
        self.track_right.add_pitch_bend(start_tick, right_bend)

        # Note L/R
        self.track_left.add_note(left_note, base_vel, start_tick, sustain_dur)
        self.track_right.add_note(right_note, base_vel, start_tick, sustain_dur)

        # Envelope CC11
        self._apply_breath_envelope(
            segments=segments,
            tempo_map=tempo_map,
            fade_cfg=fade_cfg,
        )

        # Brainwave Journey (Phase 2 ACTIVE)
        if (
            self.brainwave_mode == "journey"
            and brainwave_journey is not None
            and total_ticks > 0
        ):
            self._apply_brainwave_pitch_mod(
                start_tick=start_tick,
                total_ticks=total_ticks,
                anchor_hz=anchor_hz,
                base_beat_hz=base_beat,
                brainwave_journey=brainwave_journey,
            )

    # ------------------------------------------------------------------
    # Brainwave-based pitch modulation
    # ------------------------------------------------------------------

    def _apply_brainwave_pitch_mod(
        self,
        start_tick: int,
        total_ticks: int,
        anchor_hz: float,
        base_beat_hz: float,
        brainwave_journey: Optional["BrainwaveJourney"],
    ) -> None:

        if total_ticks <= start_tick or brainwave_journey is None:
            return

        step = self.cc_step_ticks
        effective_total = max(1, total_ticks - start_tick)

        for current_tick in range(start_tick, total_ticks + 1, step):
            t_norm = (current_tick - start_tick) / float(effective_total)

            beat = self._beat_hz_from_journey_tnorm(
                t_norm=t_norm,
                base_beat_hz=base_beat_hz,
                brainwave_journey=brainwave_journey,
            )
            beat = max(0.1, min(40.0, beat))

            left_hz = max(1.0, anchor_hz - beat / 2)
            right_hz = anchor_hz + beat / 2

            _, left_bend = freq_to_midi_pitch_bend(left_hz)
            _, right_bend = freq_to_midi_pitch_bend(right_hz)

            self.track_left.add_pitch_bend(int(current_tick), left_bend)
            self.track_right.add_pitch_bend(int(current_tick), right_bend)

    # ------------------------------------------------------------------
    # Envelope theo Breath + Breakdown
    # ------------------------------------------------------------------

    def _is_breakdown_section(self, sec_type: str) -> bool:
        return sec_type.lower() in ("bridge", "breakdown", "silent_breakdown")

    def _apply_breath_envelope(
        self,
        segments: List[Segment],
        tempo_map: TempoMap,
        fade_cfg: Optional[Dict[str, int]] = None,
    ) -> None:

        if tempo_map is None or not segments:
            return

        fade_cfg = fade_cfg or {}
        fade_in_len = int(fade_cfg.get("in", 0) or 0)
        out_start = int(fade_cfg.get("out_start", 10**12))
        fade_out_len = int(fade_cfg.get("out", 0) or 0)
        total = int(fade_cfg.get("total", segments[-1].end_tick))

        step = self.cc_step_ticks

        base_cc = int(60 * self.mix_level)
        base_cc = max(1, min(110, base_cc))

        depth = self.breath_depth

        for seg in segments:
            sec_type = getattr(seg, "section_type", "") or ""
            is_breakdown = self._is_breakdown_section(sec_type)

            seg_factor = 1.0
            if is_breakdown:
                seg_factor *= self.breakdown_thin_factor

            for t in range(0, seg.duration_ticks, step):
                current_tick = seg.start_tick + t
                if current_tick > total:
                    continue

                fade = 1.0
                if fade_in_len > 0 and current_tick < fade_in_len:
                    fade = current_tick / float(max(1, fade_in_len))

                if current_tick > out_start and fade_out_len > 0:
                    fade = max(
                        0.0,
                        (total - current_tick) / float(max(1, fade_out_len)),
                    )

                try:
                    bar = tempo_map.get_bar_pos_at_tick(current_tick)
                    phase = tempo_map.get_phase_at_bar(bar)
                except Exception:
                    phase = 0.0

                breath_mod = math.sin(phase)  # -1..1
                cc_val = base_cc + int(depth * breath_mod * seg_factor)
                cc_val = int(cc_val * fade)
                cc_val = max(0, min(127, cc_val))

                self.track_left.add_cc(current_tick, 11, cc_val)
                self.track_right.add_cc(current_tick, 11, cc_val)


# Alias để code cũ còn dùng BinauralEngineV9 không bị gãy
BinauralEngineV9 = BinauralEngine
