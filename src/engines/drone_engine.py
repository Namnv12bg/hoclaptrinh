# Tệp: src/engines/drone_engine.py
# (FINAL V11.0.2) - DRONE ENGINE V2
# ROOT DRONE GIỮ NGUYÊN + OPTIONAL SUB/FIFTH + BREATH XFADE + BREAKDOWN-THIN + ZEN CORE AWARE
#
# Interface V11:
#
#     eng = DroneEngine(writer, profile, channel=2, ...)
#
#     eng.render(
#         segments=segments,
#         tempo_map=tempo_map,
#         tuning_plan=plan,          # Optional[TuningPlan] – ƯU TIÊN
#         base_freq=base_freq_hz,    # Optional[float] – Fallback nếu plan không có Solf
#         transition_cfg=transition_cfg,
#         channel_override=None,
#     )
#
# Nguyên tắc:
# - Source of Truth tần số:
#       1) tuning_plan.primary_solf_hz (nếu > 0)
#       2) tuning_plan.secondary_solf_hz (nếu > 0, dùng như overlay nếu primary trống)
#       3) base_freq (tham số cũ, dùng cho pure_key hoặc khi plan không mang Solf)
#
# - KHÔNG pitch-shift toàn bài, chỉ:
#       + convert Hz -> (midi_note, pitch_bend) cho track Drone.
# - Root note KHÔNG clamp bằng RegisterManager (giữ chuẩn Solf/key root).
# - Sub/Fifth (nếu bật flag) CÓ THỂ clamp nhẹ qua RegisterManager (nếu tồn tại),
#   để tránh đi quá thấp/quá cao.
#
# - Breath / Breakdown / Arc:
#       + Chỉ can thiệp CC11 (expression), không đổi pitch.
# - SafetyFilter:
#       + Root/Sub/Fifth đều đi qua SafetyFilter (nếu có) TRƯỚC khi add_note.
#       + Nếu velocity <= 0 sau filter → bỏ nốt.

import math
import random
from typing import List, Dict, Any, Optional

from src.utils.midi_writer import MidiWriter
from src.utils.config_loader import InstrumentProfile
from src.core.structure_builder import Segment
from src.core.tempo_breath import TempoMap
from src.utils.math_utils import freq_to_midi_pitch_bend
from src.core.tuning_core import TuningPlan


class DroneEngine:
    """
    DroneEngine V2 – Zen Core aware, lấy tần số từ TuningPlan nếu có.

    writer:
        - Có thể là MidiWriter hoặc DynamicTransposingWriter.
    profile:
        - InstrumentProfile chứa thông tin program, mix_level, v.v.
    channel:
        - Kênh DRONE mặc định (DRONE A). DRONE B (bridge/ping-pong) sẽ dùng channel_override.
    """

    def __init__(
        self,
        writer: MidiWriter,
        profile: InstrumentProfile,
        channel: int = 2,
        tuning_mode: str = "equal",
        # “Não Zen” – Zen Core truyền xuống (optionally)
        safety_filter: Optional[Any] = None,
        register_manager: Optional[Any] = None,
        breath_sync: Optional[Any] = None,
        activity_map: Optional[Any] = None,
        zen_arc_matrix: Optional[Any] = None,
        layer_name: str = "drone",
    ) -> None:
        self.writer = writer
        self.default_channel = channel
        self.profile = profile
        self.tuning_mode = tuning_mode or "equal"

        self.safety_filter = safety_filter
        self.register_manager = register_manager
        self.breath_sync = breath_sync
        self.activity_map = activity_map
        self.zen_arc_matrix = zen_arc_matrix
        self.layer_name = layer_name or "drone"

        # Mix & tone
        self.mix_level: float = float(getattr(profile, "v9_mix_level", 0.6))
        self.lowpass_cc: Optional[int] = getattr(profile, "v9_lowpass_cc", 50)
        self.pan_width: float = float(getattr(profile, "v9_pan_width", 0.2))

        # Breath & expression
        self.enable_breath: bool = bool(getattr(profile, "enable_breath", True))
        self.breath_depth: float = float(getattr(profile, "breath_depth", 15))

        # OPTIONAL Sub/Fifth – đọc từ profile/preset
        self.enable_sub: bool = bool(getattr(profile, "enable_sub_drone", False))
        self.enable_fifth: bool = bool(getattr(profile, "enable_fifth_drone", False))
        self.sub_level: float = float(getattr(profile, "sub_level", 0.6))
        self.fifth_level: float = float(getattr(profile, "fifth_level", 0.7))

        # Breakdown-thin factor – Drone mỏng ở Bridge / energy thấp
        self.breakdown_thin_factor: float = float(
            getattr(profile, "breakdown_thin_factor", 0.45)
        )

    # ------------------------
    # Helpers: Breakdown Logic
    # ------------------------

    def _is_breakdown_segment(self, seg: Optional[Segment]) -> bool:
        """
        Xác định một segment có được coi là Breakdown / rất nhẹ không.

        - Bridge: thường là đoạn chuyển / breakdown Zen.
        - Hoặc energy_bias rất thấp (<= 0.35) theo Zen Arc.
        """
        if seg is None:
            return False

        if (getattr(seg, "section_type", "") or "").lower() == "bridge":
            return True

        energy = getattr(seg, "energy_bias", 0.5)
        return energy <= 0.35

    @staticmethod
    def _find_segment_for_tick(segments: List[Segment], tick: int) -> Optional[Segment]:
        """
        Tìm segment nào đang chứa tick này (start_tick <= tick < end_tick).
        Nếu không tìm thấy, trả về None.
        """
        for seg in segments:
            if seg.start_tick <= tick < seg.end_tick:
                return seg
        return None

    # ------------------------
    # Helper: chọn tần số từ TuningPlan / base_freq
    # ------------------------

    @staticmethod
    def _pick_freq_from_plan(
        tuning_plan: Optional[TuningPlan],
        base_freq: Optional[float],
    ) -> Optional[float]:
        """
        Luật:
            1) Nếu có tuning_plan và primary_solf_hz > 0 → dùng primary_solf_hz.
            2) Nếu primary không có nhưng secondary_solf_hz > 0 → dùng secondary.
            3) Nếu plan không có Solf hoặc không có plan → fallback sang base_freq.
        """
        if tuning_plan is not None:
            if getattr(tuning_plan, "primary_solf_hz", 0) and tuning_plan.primary_solf_hz > 0:
                return float(tuning_plan.primary_solf_hz)
            if getattr(tuning_plan, "secondary_solf_hz", 0) and tuning_plan.secondary_solf_hz > 0:
                return float(tuning_plan.secondary_solf_hz)

        if base_freq is not None and base_freq > 0:
            return float(base_freq)

        return None

    # ------------------------
    # SafetyFilter helper
    # ------------------------

    def _apply_safety_filter(
        self,
        pitch: int,
        velocity: int,
        tick: int,
        *,
        is_primary: bool,
        seg: Optional[Segment],
    ) -> int:
        """
        Cho phép SafetyFilter can thiệp nhẹ vào velocity (hoặc bỏ nốt).
        Nếu không có safety_filter → trả về velocity gốc.
        """
        if self.safety_filter is None:
            return velocity

        try:
            meta: Dict[str, Any] = {
                "layer": self.layer_name,
                "is_primary": bool(is_primary),
            }
            if seg is not None:
                meta["section_type"] = getattr(seg, "section_type", None)
                meta["energy_bias"] = getattr(seg, "energy_bias", None)
                meta["t_norm"] = getattr(seg, "t_norm", None)

            fn = getattr(self.safety_filter, "adjust", None)
            if not callable(fn):
                return velocity

            new_vel = fn(self.layer_name, int(pitch), int(velocity), int(tick), meta)
            if new_vel is None:
                return 0
            v = int(new_vel)
            if v <= 0:
                return 0
            return max(1, min(127, v))
        except Exception:
            # Nếu có lỗi → không để crash, giữ nguyên velocity gốc
            return velocity

    # ------------------------
    # Interface chính
    # ------------------------

    def render(
        self,
        segments: List[Segment],
        tempo_map: Optional[TempoMap],
        tuning_plan: Optional[TuningPlan] = None,
        base_freq: Optional[float] = None,
        transition_cfg: Optional[Dict[str, int]] = None,
        channel_override: Optional[int] = None,
    ) -> None:
        """
        Render một lớp Drone liên tục phủ lên danh sách segments.

        Ưu tiên tần số:
            1) tuning_plan.primary_solf_hz
            2) tuning_plan.secondary_solf_hz
            3) base_freq (tham số cũ)

        Lưu ý:
            - Các Solf mode / kế hoạch tần số đã được TuningCoreV3 quyết định.
            - DroneEngine KHÔNG đổi tần số gốc, chỉ thêm Sub/Fifth nếu preset yêu cầu.
        """
        if not segments:
            return

        freq_hz = self._pick_freq_from_plan(tuning_plan, base_freq)
        if freq_hz is None or freq_hz <= 0:
            return

        # Convert tần số Hz -> (midi_note, pitch_bend) theo A440
        try:
            root_note, bend_value = freq_to_midi_pitch_bend(freq_hz)
        except Exception:
            # Nếu có vấn đề với tần số, bỏ qua để tránh crash
            return

        # Root: KHÔNG clamp bằng RegisterManager để giữ nguyên logic Solf/key root.
        base_vel = int(getattr(self.profile, "velocity", 90))
        root_vel = int(base_vel * float(self.mix_level))
        root_vel = max(1, min(127, root_vel))

        # Tính vùng tick core theo segments
        core_start = min(s.start_tick for s in segments)
        core_end = max(s.end_tick for s in segments)

        extend_start = 0
        extend_end = 0
        if transition_cfg:
            extend_start = int(transition_cfg.get("extend_start", 0) or 0)
            extend_end = int(transition_cfg.get("extend_end", 0) or 0)

        actual_start = max(0, core_start - extend_start)
        actual_end = core_end + extend_end
        if actual_end <= actual_start:
            actual_end = core_end

        total_duration = max(1, actual_end - actual_start)

        # Chọn kênh đích (DRONE A hoặc B)
        target_channel = (
            channel_override if channel_override is not None else self.default_channel
        )
        track = self.writer.get_track(target_channel)

        # Segment đầu tiên (dùng để meta cho SafetyFilter)
        first_seg: Optional[Segment] = segments[0] if segments else None

        # Pitch bend về đúng tần số Solf / key root (per-note, KHÔNG global shift)
        track.add_pitch_bend(actual_start, bend_value)

        # Low-pass (nếu có) – làm Drone mềm, ít chói
        if self.lowpass_cc is not None:
            cc_val = max(0, min(127, int(self.lowpass_cc)))
            track.add_cc(actual_start, 74, cc_val)  # CC74: Brightness / Filter

        # Pan ngẫu nhiên nhẹ quanh center để hai Drone (A/B) khác nhau một chút
        center = 64
        span = int(20 * float(self.pan_width))
        pan_val = center + random.randint(-span, span)
        pan_val = max(0, min(127, pan_val))
        track.add_cc(actual_start, 10, pan_val)  # CC10: Pan

        # 4. Chuẩn bị danh sách nốt Drone (Root + optional Sub/Fifth)
        notes_to_play: List[tuple[int, int, bool]] = []
        # Root luôn có – không clamp để giữ chuẩn Solf/key
        notes_to_play.append((root_note, root_vel, True))  # (pitch, vel, is_primary)

        # Sub Drone (nếu preset bật) – có thể clamp nhẹ qua RegisterManager
        if self.enable_sub:
            sub_note = root_note - 12
            sub_vel = int(root_vel * _clamp(self.sub_level, 0.0, 1.0))
            sub_vel = max(1, min(127, sub_vel))
            if sub_note >= 0:
                sub_note = self._maybe_constrain_pitch(sub_note)
                notes_to_play.append((sub_note, sub_vel, False))

        # Fifth Drone (nếu preset bật) – có thể clamp nhẹ qua RegisterManager
        if self.enable_fifth:
            fifth_note = root_note + 7
            fifth_vel = int(root_vel * _clamp(self.fifth_level, 0.0, 1.0))
            fifth_vel = max(1, min(127, fifth_vel))
            if fifth_note <= 127:
                fifth_note = self._maybe_constrain_pitch(fifth_note)
                notes_to_play.append((fifth_note, fifth_vel, False))

        # 5. Ghi nốt – Root + các vệ tinh Sub/Fifth (nếu có), qua SafetyFilter nếu có
        for note, vel, is_primary in notes_to_play:
            final_vel = self._apply_safety_filter(
                note,
                vel,
                actual_start,
                is_primary=is_primary,
                seg=first_seg,
            )
            if final_vel <= 0:
                continue

            track.add_note(note, final_vel, actual_start, total_duration)

        # Commit activity nhẹ nhàng (để layer khác biết Drone đang chiếm chỗ)
        if self.activity_map is not None:
            try:
                fn = getattr(self.activity_map, "commit_event", None)
                if callable(fn):
                    fn(
                        layer=self.layer_name,
                        start_tick=actual_start,
                        duration_ticks=total_duration,
                        weight=0.3,
                    )
                else:
                    fn = getattr(self.activity_map, "add_activity", None)
                    if callable(fn):
                        # API cũ: add_activity(start_tick, duration, weight=...)
                        fn(actual_start, total_duration, weight=0.3)
            except Exception:
                pass

        # 6. Breath & Crossfade & Breakdown-thin (Trên kênh đích)
        if self.enable_breath and tempo_map is not None:
            self._apply_breath_with_fade_and_breakdown(
                track,
                segments,
                actual_start,
                actual_end,
                core_start,
                core_end,
                tempo_map,
            )

    # =========================
    # Helpers
    # =========================

    def _maybe_constrain_pitch(self, midi_note: int) -> int:
        """
        Sub/Fifth có thể được "kéo" về register an toàn nếu RegisterManager hỗ trợ.
        Root note KHÔNG đi qua hàm này để tránh lệch Solf.
        """
        if self.register_manager is None:
            return midi_note

        try:
            fn = getattr(self.register_manager, "constrain_pitch", None)
            if callable(fn):
                return int(fn(self.layer_name, midi_note))
        except Exception:
            return midi_note
        return midi_note

    def _apply_breath_with_fade_and_breakdown(
        self,
        track,
        segments: List[Segment],
        start_t: int,
        end_t: int,
        core_start: int,
        core_end: int,
        tempo_map: TempoMap,
    ) -> None:
        """
        Áp dụng:
        - Breath LFO theo BreathSyncManager (nếu có) hoặc TempoMap (chu kỳ thở).
        - Crossfade ở đoạn bridge (trước core_start và sau core_end).
        - Drone MỎNG ở Breakdown:
              + Các tick thuộc segment Bridge / energy thấp sẽ giảm mạnh gain.

        Bản này thêm:
        - arc_factor (ZenArcMatrix) & activity_factor (ActivityMap) → chỉ scale CC11.
        """
        step = max(1, self.writer.ppq // 2)
        base_expr = 90  # Biểu cảm cơ bản cho Drone

        for t in range(start_t, end_t, step):
            # 1. Breath LFO (ưu tiên BreathSync nếu có)
            phase: Optional[float] = None

            if self.breath_sync is not None:
                try:
                    fn = getattr(self.breath_sync, "get_phase_at_tick", None)
                    if callable(fn):
                        phase = float(fn(t))
                except Exception:
                    phase = None

            if phase is None:
                try:
                    bar_pos = tempo_map.get_bar_pos_at_tick(t)
                    phase = float(tempo_map.get_phase_at_bar(bar_pos))
                except Exception:
                    phase = 0.0

            lfo = math.sin(phase) * float(self.breath_depth)

            # 2. Crossfade Logic (bridge fade in/out)
            fade_factor = 1.0
            if t < core_start:
                ramp_len = core_start - start_t
                if ramp_len > 0:
                    fade_factor = (t - start_t) / float(ramp_len)
            elif t > core_end:
                ramp_len = end_t - core_end
                if ramp_len > 0:
                    fade_factor = 1.0 - ((t - core_end) / float(ramp_len))

            # 3. Breakdown-thin: segment Bridge / energy thấp
            seg = self._find_segment_for_tick(segments, t)
            breakdown_factor = 1.0
            if self._is_breakdown_segment(seg):
                breakdown_factor = float(self.breakdown_thin_factor)

            # 4. Activity & Arc factor (rất defensive, tránh crash)
            activity_factor = 1.0
            if self.activity_map is not None:
                try:
                    fn = getattr(self.activity_map, "get_energy_at_tick", None)
                    if callable(fn):
                        activity_factor = float(fn(self.layer_name, t))
                    else:
                        fn = getattr(self.activity_map, "get_track_energy", None)
                        if callable(fn):
                            activity_factor = float(fn(self.layer_name, t))
                        else:
                            fn = getattr(self.activity_map, "get_activity_at_tick", None)
                            if callable(fn):
                                activity_factor = float(fn(self.layer_name, t))
                except Exception:
                    activity_factor = 1.0
            # Drone không bao giờ bị “dìm” quá nhiều bởi ActivityMap
            activity_factor = _clamp(activity_factor, 0.7, 1.3)

            arc_factor = 1.0
            if self.zen_arc_matrix is not None and seg is not None:
                try:
                    fn = getattr(self.zen_arc_matrix, "get_factor_for_segment", None)
                    if callable(fn):
                        arc_factor = float(fn(seg))
                except Exception:
                    arc_factor = 1.0
            arc_factor = _clamp(arc_factor, 0.5, 1.5)

            # 5. Kết hợp tất cả thành CC11
            current_vol = (base_expr + lfo) * fade_factor * breakdown_factor
            current_vol *= activity_factor * arc_factor

            val = int(_clamp(current_vol, 0.0, 127.0))
            track.add_cc(t, 11, val)  # CC11: Expression – dùng cho "thở" + fade


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))
