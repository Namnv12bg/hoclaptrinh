# Tệp: src/engines/vocal_engine.py
# (FINAL V10.11.2) - VOCAL ENGINE V1 (ZEN CORE READY + SAFETY META)
# OM / DRONE / CALL-RESPONSE / CHANT + BREATH-SAFE + ACTIVITY-WRITE ONLY
#
# Mục tiêu:
# - Thêm lớp Vocal tối giản (OM / chant) dùng MIDI note của sample.
# - Không sinh giai điệu phức tạp, chỉ trigger root / note cố định.
# - Bám Zen Arc + Breath:
#     + Grounding / Outro: OM dài, thưa.
#     + Immersion / Peak: có thể dày hơn chút nếu muốn.
# - Tôn trọng:
#     + vocal_mode: "om_pulse" | "long_drone" | "call_response" | "chant_pattern"
#     + vocal_density: 0..1 (mặc định rất thấp).
#     + vocal_breakdown_mode: "mute" | "soft" | "normal"
#     + vocal_sections: list section_type được phép có vocal.
#
# Giao diện:
#   from src.engines.vocal_engine import VocalEngineV1
#
#   engine = VocalEngineV1(
#       writer,
#       profile,
#       channel,
#       user_options,
#       safety_filter=safety_filter,
#       register_manager=register_manager,
#       breath_sync=breath_sync,
#       zen_arc_matrix=zen_arc,
#       layer_name="vocal",
#       activity_map=activity_map,  # Option A: CHỈ ghi activity, không né
#   )
#   engine.render(segments, tempo_map, activity_map=None)
#
# Lưu ý:
# - Không dùng TuningCore / pitch-bend cho vocal.
# - Vocal luôn đánh 1 nốt (vocal_register_note) hoặc root key (fallback).
# - Option A: Vocal chỉ GHI activity vào ActivityMap, KHÔNG dùng ActivityMap để né.
# - safety_filter / register_manager nếu cung cấp sẽ được dùng để giữ pitch/velocity an toàn.

from __future__ import annotations

import math
import random
from typing import List, Optional, Dict, Any

from src.utils.midi_writer import MidiWriter
from src.utils.config_loader import InstrumentProfile
from src.core.structure_builder import Segment
from src.core.tempo_breath import TempoMap
from src.utils.activity_map import ActivityMap


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class VocalEngineV1:
    def __init__(
        self,
        writer: MidiWriter,
        profile: InstrumentProfile,
        channel: int,
        user_options: Optional[Dict[str, Any]] = None,
        safety_filter: Optional[object] = None,
        register_manager: Optional[object] = None,
        breath_sync: Optional[object] = None,
        zen_arc_matrix: Optional[object] = None,
        layer_name: str = "vocal",
        activity_map: Optional[ActivityMap] = None,
    ):
        self.writer = writer
        self.profile = profile
        self.options = user_options or {}

        # Hooks từ Zen Core
        self.safety_filter = safety_filter
        self.register_manager = register_manager
        self.breath_sync = breath_sync
        self.zen_arc_matrix = zen_arc_matrix
        self.layer_name = layer_name or "vocal"

        self.activity_map: Optional[ActivityMap] = activity_map

        # Track & PPQ an toàn
        if self.writer is not None:
            ch = channel or getattr(profile, "channel", 9) or 9
            self.track = self.writer.get_track(ch)
            self.channel = ch
            self.ppq = int(getattr(self.writer, "ppq", 480))
        else:
            self.track = None
            self.channel = channel or 9
            self.ppq = 480

        # =========================
        # Profile / Options
        # =========================

        # Bật / tắt layer vocal (options override profile)
        self.enable_vocal_layer: bool = bool(
            self.options.get(
                "enable_vocal_layer",
                getattr(profile, "enable_vocal_layer", True),
            )
        )

        # Kiểu hành vi vocal
        self.vocal_mode: str = str(
            self.options.get(
                "vocal_mode",
                getattr(profile, "vocal_mode", "om_pulse"),
            )
        ).lower()
        if self.vocal_mode not in (
            "om_pulse",
            "long_drone",
            "call_response",
            "chant_pattern",
        ):
            self.vocal_mode = "om_pulse"

        # Mật độ tổng thể (0..1). 0: gần như im lặng, 1: dày nhất (nhưng vẫn khá thưa).
        self.vocal_density: float = float(
            self.options.get(
                "vocal_density",
                getattr(profile, "vocal_density", 0.2),
            )
        )
        self.vocal_density = _clamp(self.vocal_density, 0.0, 1.0)

        # Breakdown mode
        self.breakdown_mode: str = str(
            self.options.get(
                "vocal_breakdown_mode",
                getattr(profile, "vocal_breakdown_mode", "soft"),
            )
        ).lower()
        if self.breakdown_mode not in ("soft", "mute", "normal"):
            self.breakdown_mode = "soft"

        # Nốt register cho sample vocal (ví dụ D3, C3...)
        # Ưu tiên options > profile, default ~ D3 (50).
        base_reg = int(getattr(profile, "vocal_register_note", 50))
        try:
            self.vocal_register_note: int = int(
                self.options.get("vocal_register_note", base_reg)
            )
        except Exception:
            self.vocal_register_note = base_reg

        # Độ "thở" của vocal (0..1) – mod nhẹ vào velocity theo pha thở
        self.vocal_breath_amount: float = float(
            self.options.get(
                "vocal_breath_amount",
                getattr(profile, "vocal_breath_amount", 0.5),
            )
        )
        self.vocal_breath_amount = _clamp(self.vocal_breath_amount, 0.0, 1.0)

        # Danh sách section_type được phép có vocal
        default_sections = [
            "grounding",
            "intro",
            "immersion",
            "peak",
            "awakening",
            "outro",
            "integration",
        ]
        secs_opt = self.options.get("vocal_sections", None)
        if isinstance(secs_opt, list):
            self.vocal_sections = [str(s).lower() for s in secs_opt]
        else:
            sec_from_profile = getattr(profile, "vocal_sections", None)
            if isinstance(sec_from_profile, list):
                self.vocal_sections = [str(s).lower() for s in sec_from_profile]
            else:
                self.vocal_sections = default_sections

        # Base velocity & jitter
        self.base_velocity: int = int(
            self.options.get(
                "vocal_velocity",
                getattr(profile, "vocal_velocity", 70),
            )
        )
        self.vel_jitter: int = int(
            self.options.get(
                "vocal_vel_jitter",
                getattr(profile, "vocal_vel_jitter", 4),
            )
        )

        # Nội bộ: tránh lặp quá sát
        self.min_gap_ticks: int = int(
            self.options.get(
                "vocal_min_gap_ticks",
                getattr(profile, "vocal_min_gap_ticks", self.ppq * 4),
            )
        )  # tối thiểu 1 bar 4/4
        self.last_note_off_tick: int = -999_999

        # Activity weight cho vocal trong ActivityMap (để lớp khác thấy Handpan/Vocal đã "chiếm chỗ")
        self.vocal_activity_weight: float = float(
            self.options.get(
                "vocal_activity_weight",
                getattr(profile, "vocal_activity_weight", 1.0),
            )
        )

    # =========================
    # PUBLIC
    # =========================

    def render(
        self,
        segments: List[Segment],
        tempo_map: Optional[TempoMap] = None,
        activity_map: Optional[ActivityMap] = None,
    ):
        """
        segments: list Segment có section_type + energy_bias
        tempo_map: dùng để sync breath_phase (nếu có).
        activity_map: nếu truyền vào đây sẽ override self.activity_map (Option A: chỉ ghi).
        """
        if not self.enable_vocal_layer:
            return

        if not segments or self.track is None:
            return

        if activity_map is not None:
            self.activity_map = activity_map

        for seg in segments:
            if getattr(seg, "duration_ticks", 0) <= 0:
                continue

            sec_type = (getattr(seg, "section_type", "") or "").lower()
            if not self._is_section_allowed(sec_type):
                continue

            # Breakdown xử lý đặc biệt
            if sec_type in ("breakdown", "silence"):
                if self.breakdown_mode == "mute":
                    continue
                elif self.breakdown_mode == "soft":
                    density_scale = 0.25
                else:
                    density_scale = 1.0
            else:
                density_scale = 1.0

            energy = float(getattr(seg, "energy_bias", 0.4))
            energy = _clamp(energy, 0.0, 1.0)

            # Local density cho segment này (0..1)
            local_density = (
                self._compute_local_density(energy, sec_type) * density_scale
            )

            # ZenArcMatrix factor (bias nhẹ, không tắt hẳn)
            if self.zen_arc_matrix is not None:
                try:
                    if hasattr(self.zen_arc_matrix, "get_factor_for_segment"):
                        zen_factor = float(self.zen_arc_matrix.get_factor_for_segment(seg))
                        zen_factor = _clamp(zen_factor, 0.5, 1.5)
                        local_density *= zen_factor
                except Exception:
                    pass

            local_density = _clamp(local_density, 0.0, 1.0)
            if local_density <= 0.0:
                continue

            # Chọn strategy theo vocal_mode
            if self.vocal_mode == "long_drone":
                self._render_long_drone(seg, local_density, energy, tempo_map)
            elif self.vocal_mode == "call_response":
                self._render_call_response(seg, local_density, energy, tempo_map)
            elif self.vocal_mode == "chant_pattern":
                self._render_chant_pattern(seg, local_density, energy, tempo_map)
            else:
                # om_pulse
                self._render_om_pulse(seg, local_density, energy, tempo_map)

    # =========================
    # INTERNAL HELPERS
    # =========================

    def _is_section_allowed(self, sec_type: str) -> bool:
        if not sec_type:
            return True
        # Mapping một số tên section sang tên Zen Arc
        s = sec_type.lower()
        if s in ("intro", "grounding"):
            tag = "grounding"
        elif s in ("immersion", "verse"):
            tag = "immersion"
        elif s in ("chorus", "peak", "awakening"):
            tag = "peak"
        elif s in ("integration", "outro"):
            tag = "outro"
        elif s in ("breakdown", "silence"):
            tag = "breakdown"
        else:
            tag = s
        return tag in self.vocal_sections

    def _compute_local_density(self, energy: float, sec_type: str) -> float:
        """
        Density cho vocal:
        - Base: vocal_density (profile/options).
        - Nhân thêm theo energy & section_type:
            + Grounding/Outro: dù energy thấp vẫn cho vài OM.
            + Immersion: trung bình.
            + Peak: nếu muốn có call-response / chant, cho phép cao hơn.
        """
        base = self.vocal_density
        s = (sec_type or "").lower()

        if s in ("intro", "grounding"):
            arc = 0.9  # trọng tâm chính cho OM
        elif s in ("immersion", "verse"):
            arc = 0.6
        elif s in ("chorus", "peak", "awakening"):
            arc = 0.7
        elif s in ("integration", "outro"):
            arc = 0.8
        elif s in ("breakdown", "silence"):
            arc = 0.2
        else:
            arc = 0.6

        # energy_factor nhẹ – vocal không nên "hùng hục" theo energy
        energy_factor = 0.4 + 0.6 * energy

        density = base * arc * energy_factor
        return _clamp(density, 0.0, 1.0)

    def _get_breath_phase(self, tick: int, tempo_map: Optional[TempoMap]) -> float:
        """
        Lấy phase thở 0..1 (nếu có TempoMap).
        - 0.0–~0.4 ~ inhale (ít vocal hơn)
        - ~0.4–1.0 ~ exhale (ưu tiên vocal mạnh hơn)
        Implement theo chuẩn các engine khác:
        dùng breath_cycle_bars + get_bar_pos_at_tick + sin LFO.
        """
        if tempo_map is None:
            return 0.5

        cycle_bars = float(getattr(tempo_map, "breath_cycle_bars", 2.0) or 2.0)
        try:
            bar_pos = tempo_map.get_bar_pos_at_tick(tick)
            phase_bar = (bar_pos / cycle_bars) % 1.0  # 0..1
        except Exception:
            phase_bar = 0.5

        # Chuyển phase_bar (0..1) thành sin LFO 0..1, peak ở exhale mid
        lfo = (math.sin(phase_bar * 2.0 * math.pi - (math.pi / 2.0)) + 1.0) / 2.0
        return float(_clamp(lfo, 0.0, 1.0))

    def _compute_velocity(self, energy: float, breath_phase: float) -> int:
        """
        Velocity cho note vocal:
        - Base: vocal_velocity.
        - Scale nhẹ theo energy.
        - Mod nhẹ theo breath_phase nếu vocal_breath_amount > 0.
        """
        vel = int(self.base_velocity * (0.6 + 0.6 * energy))  # 0.6–1.2x

        # Breath modulation: exhale mạnh hơn (breath_phase gần 1)
        if self.vocal_breath_amount > 0.0:
            # map breath_phase 0..1 -> 0.8..1.3
            breath_gain = 0.8 + 0.5 * breath_phase
            vel = int(
                vel * (1.0 + (breath_gain - 1.0) * self.vocal_breath_amount)
            )

        # Jitter
        vel += random.randint(-self.vel_jitter, self.vel_jitter)

        return max(1, min(127, vel))

    def _can_trigger_at(self, tick: int) -> bool:
        """
        Đảm bảo giữa 2 note vocal có khoảng cách tối thiểu min_gap_ticks.
        """
        if tick - self.last_note_off_tick < self.min_gap_ticks:
            return False
        return True

    # =========================
    # MODES
    # =========================

    def _render_long_drone(
        self,
        seg: Segment,
        density: float,
        energy: float,
        tempo_map: Optional[TempoMap],
    ):
        """
        long_drone:
        - Tối đa 1 nốt OM kéo dài gần hết segment (trừ khi density rất cao).
        - Thích hợp cho Grounding/Outro.
        """
        # Density thấp → nhiều segment bỏ qua.
        if random.random() > density:
            return

        start = seg.start_tick
        dur = int(seg.duration_ticks * 0.85)
        if dur <= self.ppq:
            return

        if not self._can_trigger_at(start):
            return

        breath_phase = self._get_breath_phase(start, tempo_map)
        vel = self._compute_velocity(energy=energy, breath_phase=breath_phase)

        self._add_note(start, dur, self.vocal_register_note, vel, seg, energy, breath_phase)
        self.last_note_off_tick = start + dur

    def _render_om_pulse(
        self,
        seg: Segment,
        density: float,
        energy: float,
        tempo_map: Optional[TempoMap],
    ):
        """
        om_pulse:
        - 1–2 OM dài mỗi segment, cách nhau ít nhất min_gap_ticks.
        - Thời điểm dựa trên breath cycle nếu có TempoMap.
        """
        # Ước lượng số OM trong segment (0–2)
        base = density * 2.0
        num_om = 0
        if base > 0.3:
            num_om = 1
        if base > 1.0:
            num_om = 2

        if num_om <= 0:
            return

        for _ in range(num_om):
            # random offset trong 60% đầu segment
            offset = random.randint(0, int(seg.duration_ticks * 0.6))
            start = seg.start_tick + offset
            if start >= seg.end_tick:
                continue

            if not self._can_trigger_at(start):
                continue

            # breath-phase tại start
            breath_phase = self._get_breath_phase(start, tempo_map)
            vel = self._compute_velocity(energy=energy, breath_phase=breath_phase)

            # dur phụ thuộc mode: pulse nhưng vẫn dài (2–4 bar)
            # tạm lấy 40–70% segment
            dur = random.randint(
                int(seg.duration_ticks * 0.4), int(seg.duration_ticks * 0.7)
            )
            if dur <= self.ppq:
                continue

            if start + dur > seg.end_tick:
                dur = seg.end_tick - start
            if dur <= 0:
                continue

            self._add_note(start, dur, self.vocal_register_note, vel, seg, energy, breath_phase)
            self.last_note_off_tick = start + dur

    def _render_call_response(
        self,
        seg: Segment,
        density: float,
        energy: float,
        tempo_map: Optional[TempoMap],
    ):
        """
        call_response:
        - Dùng cho Peak/Awakening: 2–3 OM "hỏi – đáp" trong 1 segment.
        - Vẫn cực kỳ thưa (phụ thuộc density).
        """
        # Một chút bias: section Peak/Chorus mới nên có kiểu này.
        # Nếu energy thấp + density thấp → hầu như không gọi.
        if density < 0.1 or energy < 0.4:
            return

        # Số phrases nhỏ (1–3)
        base = density * 3.0
        num_phrases = max(1, min(3, int(round(base))))
        if num_phrases <= 0:
            return

        slice_len = seg.duration_ticks // (num_phrases + 1)
        if slice_len <= self.ppq:
            # Segment quá ngắn, fallback sang om_pulse
            self._render_om_pulse(seg, density, energy, tempo_map)
            return

        for i in range(num_phrases):
            center = seg.start_tick + slice_len * (i + 1)
            jitter = random.randint(-self.ppq, self.ppq)
            start = center + jitter

            if start < seg.start_tick:
                start = seg.start_tick
            if start >= seg.end_tick:
                continue

            if not self._can_trigger_at(start):
                continue

            breath_phase = self._get_breath_phase(start, tempo_map)
            vel = self._compute_velocity(energy=energy, breath_phase=breath_phase)

            # call-response: mỗi phrase ngắn hơn om_pulse
            dur = random.randint(int(slice_len * 0.4), int(slice_len * 0.8))
            if dur <= self.ppq:
                continue
            if start + dur > seg.end_tick:
                dur = seg.end_tick - start
            if dur <= 0:
                continue

            self._add_note(start, dur, self.vocal_register_note, vel, seg, energy, breath_phase)
            self.last_note_off_tick = start + dur

    def _render_chant_pattern(
        self,
        seg: Segment,
        density: float,
        energy: float,
        tempo_map: Optional[TempoMap],
    ):
        """
        chant_pattern:
        - Chuỗi 3–6 OM ngắn hơn, giống chant nhẹ trên một note.
        - Không sync chặt 100% vào beat, chỉ dựa trên breath-phase nhẹ.
        - Vẫn tôn trọng min_gap và density.
        """
        # Energy/density rất thấp → thôi bỏ
        if density < 0.05 or energy < 0.2:
            return

        # Số note trong pattern
        base = density * 6.0
        num_notes = max(3, min(6, int(round(base)) or 3))

        # Tổng chiều dài pattern ~ 40–70% segment
        total_len = int(seg.duration_ticks * random.uniform(0.4, 0.7))
        if total_len <= self.ppq:
            return

        # Vị trí bắt đầu pattern
        start = seg.start_tick + random.randint(
            0, max(1, int(seg.duration_ticks * 0.4))
        )
        if start >= seg.end_tick:
            return

        if not self._can_trigger_at(start):
            return

        step = max(self.ppq // 2, total_len // max(1, num_notes - 1))

        for i in range(num_notes):
            t_on = start + i * step
            if t_on >= seg.end_tick:
                break

            breath_phase = self._get_breath_phase(t_on, tempo_map)
            vel = self._compute_velocity(energy=energy, breath_phase=breath_phase)

            # mỗi câu chant tương đối ngắn
            dur = int(step * random.uniform(0.6, 0.9))
            if dur <= self.ppq // 4:
                dur = self.ppq // 4
            if t_on + dur > seg.end_tick:
                dur = seg.end_tick - t_on
                if dur <= 0:
                    break

            self._add_note(t_on, dur, self.vocal_register_note, vel, seg, energy, breath_phase)
            self.last_note_off_tick = t_on + dur

    # =========================
    # OUTPUT
    # =========================

    def _add_note(
        self,
        t_on: int,
        dur: int,
        note: int,
        vel: int,
        seg: Segment,
        energy: float,
        breath_phase: float,
    ) -> None:
        """
        Ghi note + activity_map (nếu có).
        Option A: CHỈ ghi activity, không dùng activity_map để né.
        Nếu có register_manager / safety_filter thì áp dụng nhẹ trước khi ghi.
        Đồng thời truyền meta chuẩn cho SafetyFilter.
        """
        if dur <= 0 or self.track is None:
            return

        pitch = int(note)
        velocity = int(vel)
        start_tick = int(t_on)

        # 1) RegisterManager: ép nốt vào register an toàn nếu có
        if self.register_manager is not None:
            try:
                if hasattr(self.register_manager, "apply_register"):
                    pitch = int(
                        self.register_manager.apply_register(
                            self.layer_name, pitch, start_tick
                        )
                    )
                elif hasattr(self.register_manager, "apply_for_layer"):
                    pitch = int(
                        self.register_manager.apply_for_layer(
                            layer=self.layer_name,
                            pitch=pitch,
                            tick=start_tick,
                        )
                    )
                elif hasattr(self.register_manager, "constrain_pitch"):
                    pitch = int(
                        self.register_manager.constrain_pitch(
                            self.layer_name, pitch
                        )
                    )
            except Exception:
                # lỗi thì giữ nguyên pitch
                pass

        pitch = max(0, min(127, pitch))
        velocity = max(1, min(127, velocity))

        # 2) SafetyFilter: có thể chặn / chỉnh pitch / velocity
        allowed = True
        if self.safety_filter is not None:
            sec_type = (getattr(seg, "section_type", "") or "").lower()
            meta = {
                "layer": self.layer_name,
                "section_type": sec_type,
                "energy_bias": float(_clamp(energy, 0.0, 1.0)),
                "t_norm": getattr(seg, "t_norm", None),
                "vocal_mode": self.vocal_mode,
                "vocal_density": self.vocal_density,
                "breath_phase": float(_clamp(breath_phase, 0.0, 1.0)),
            }
            try:
                if hasattr(self.safety_filter, "filter_note"):
                    # Ưu tiên signature có meta; nếu bị TypeError thì fallback
                    try:
                        res = self.safety_filter.filter_note(
                            layer=self.layer_name,
                            pitch=pitch,
                            velocity=velocity,
                            tick=start_tick,
                            meta=meta,
                        )
                    except TypeError:
                        res = self.safety_filter.filter_note(
                            layer=self.layer_name,
                            pitch=pitch,
                            velocity=velocity,
                            tick=start_tick,
                        )

                    if isinstance(res, (tuple, list)) and len(res) >= 3:
                        allowed, pitch, velocity = (
                            bool(res[0]),
                            int(res[1]),
                            int(res[2]),
                        )
                    else:
                        allowed = bool(res)
                elif hasattr(self.safety_filter, "allow_note"):
                    try:
                        allowed = bool(
                            self.safety_filter.allow_note(
                                layer=self.layer_name,
                                pitch=pitch,
                                velocity=velocity,
                                tick=start_tick,
                                meta=meta,
                            )
                        )
                    except TypeError:
                        allowed = bool(
                            self.safety_filter.allow_note(
                                layer=self.layer_name,
                                pitch=pitch,
                                velocity=velocity,
                                tick=start_tick,
                            )
                        )
            except Exception:
                allowed = True

        if not allowed:
            return

        pitch = max(0, min(127, pitch))
        velocity = max(1, min(127, velocity))

        self.track.add_note(int(pitch), int(velocity), start_tick, int(dur))

        # 3) Ghi activity (Option A)
        if self.activity_map is not None:
            try:
                self.activity_map.add_activity(
                    start_tick,
                    int(dur),
                    weight=self.vocal_activity_weight,
                )
            except Exception:
                pass
