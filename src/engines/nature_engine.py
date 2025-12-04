# Tệp: src/engines/nature_engine.py
# (FINAL V10.11.2) - NATURE ENGINE V1
# (RAIN / FOREST / RIVER / OCEAN / FIREPLACE + ZEN ARC + BREATH + ACTIVITY SAFE + SAFETY HOOKS)
#
# Mục tiêu:
# - Tạo lớp NATURE (tiếng mưa, suối, rừng, lửa...) theo Zen Arc + Energy + Breath.
# - Có master switch + breakdown mode giống Drone/Harm/Melody/Chime.
# - Tích hợp:
#     + SafetyFilter  : chặn/chỉnh pitch/velocity nếu cần.
#     + RegisterManager: giữ pitch trong vùng an toàn (nếu dùng).
#     + ZenArcMatrix  : bias nhẹ density theo hành trình Zen (0.5–1.5).
#     + ActivityMap   : vừa tránh vùng quá dày, vừa ghi activity cho lớp sau.
#
# Thiết kế:
#   engine = NatureEngineV1(
#       writer, profile, channel,
#       user_options=user_options,
#       safety_filter=safety_filter,
#       register_manager=register_manager,
#       breath_sync=breath_sync,
#       zen_arc_matrix=zen_arc,
#       layer_name="nature",
#       activity_map=activity_map,
#   )
#   engine.render(segments, tempo_map=None, activity_map=None)

from __future__ import annotations

import random
import math
from typing import List, Optional, Tuple, Dict, Any

from src.utils.midi_writer import MidiWriter
from src.utils.config_loader import InstrumentProfile  # đồng bộ với profile loader mới
from src.core.structure_builder import Segment
from src.core.tempo_breath import TempoMap
from src.utils.activity_map import ActivityMap


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class NatureEngineV1:
    def __init__(
        self,
        writer: MidiWriter,
        profile: InstrumentProfile,
        channel: int,
        user_options: Optional[dict] = None,
        *,
        safety_filter: Optional[object] = None,
        register_manager: Optional[object] = None,
        breath_sync: Optional[object] = None,
        zen_arc_matrix: Optional[object] = None,
        layer_name: str = "nature",
        activity_map: Optional[ActivityMap] = None,
    ):
        self.writer = writer
        self.track = writer.get_track(channel) if writer is not None else None
        self.profile = profile
        self.channel = channel
        self.ppq = int(getattr(writer, "ppq", 480))

        self.user_options = user_options or {}

        # Hooks Neo Zen
        self.safety_filter = safety_filter
        self.register_manager = register_manager
        self.breath_sync = breath_sync
        self.zen_arc_matrix = zen_arc_matrix
        self.layer_name = layer_name or "nature"
        self.activity_map: Optional[ActivityMap] = activity_map

        # ===== CONFIG TỪ OPTIONS + PROFILE =====

        # Master switch: bật/tắt hẳn lớp NATURE
        self.enable_nature_layer: bool = bool(
            self.user_options.get(
                "enable_nature_layer",
                getattr(profile, "enable_nature_layer", True),
            )
        )

        # Loại ambience
        self.nature_profile: str = str(
            self.user_options.get(
                "nature_profile",
                getattr(profile, "nature_profile", "forest"),
            )
        ).lower()
        if self.nature_profile not in ("rain", "forest", "river", "ocean", "fireplace"):
            self.nature_profile = "forest"

        # Độ mạnh tổng riêng của nature
        self.nature_intensity: float = float(
            self.user_options.get(
                "nature_intensity",
                getattr(profile, "nature_intensity", 0.7),
            )
        )
        self.nature_intensity = _clamp(self.nature_intensity, 0.0, 1.0)

        # Intensity tổng thể preset (0–1): dùng chung với các engine khác
        self.master_intensity: float = float(
            self.user_options.get(
                "master_intensity",
                getattr(profile, "master_intensity", 0.6),
            )
        )
        self.master_intensity = _clamp(self.master_intensity, 0.0, 1.0)

        # Behaviour trong breakdown
        self.breakdown_mode: str = str(
            self.user_options.get(
                "nature_breakdown_mode",
                getattr(profile, "nature_breakdown_mode", "soft"),
            )
        ).lower()
        if self.breakdown_mode not in ("mute", "soft", "normal"):
            self.breakdown_mode = "soft"

        # Velocity base & jitter
        self.base_velocity: int = int(getattr(profile, "velocity", 90))
        self.vel_jitter: int = int(getattr(profile, "vel_jitter", 8))

        # Note gốc để map sample (tuỳ SoundFont)
        self.base_note: int = int(getattr(profile, "nature_root_note", 60))

        # Khoảng octave cho từng loại
        self.octave_low: int = int(getattr(profile, "nature_octave_low", 4))
        self.octave_high: int = int(getattr(profile, "nature_octave_high", 6))
        if self.octave_high < self.octave_low:
            self.octave_high = self.octave_low

        # Mật độ spacing cơ bản (theo beat)
        self.min_spacing_beats: float = float(
            getattr(profile, "nature_min_spacing_beats", 1.0)
        )
        if self.min_spacing_beats < 0.0:
            self.min_spacing_beats = 0.0

        # Activity threshold: né vùng đang rất bận
        self.activity_threshold: float = float(
            getattr(profile, "nature_activity_threshold", 0.85)
        )
        self.activity_threshold = _clamp(self.activity_threshold, 0.0, 1.0)

        # Mức độ "thở" theo hơi (0–1): scale ảnh hưởng của breath_phase_factor
        self.nature_breath_amount: float = float(
            getattr(profile, "nature_breath_amount", 0.7)
        )
        self.nature_breath_amount = _clamp(self.nature_breath_amount, 0.0, 1.0)

        # Pan jitter: rung nhẹ quanh center 64 cho mỗi event
        self.pan_jitter: int = int(getattr(profile, "nature_pan_jitter", 8))
        if self.pan_jitter < 0:
            self.pan_jitter = 0

        # Activity weight cho Nature trong ActivityMap
        self.nature_activity_weight: float = float(
            getattr(profile, "nature_activity_weight", 0.4)
        )

    # =========================
    # PUBLIC
    # =========================

    def render(
        self,
        segments: List[Segment],
        tempo_map: Optional[TempoMap] = None,
        activity_map: Optional[ActivityMap] = None,
    ) -> None:
        """
        Sinh layer Nature theo từng Segment:
        - Density dựa trên: Zen Arc (section_type) + energy_bias + nature_intensity + master_intensity.
        - Breath-aware: nếu có tempo_map, ưu tiên sự kiện theo pha breath (độ mạnh bởi nature_breath_amount).
        - Activity-aware: né vùng Melody/Pulse/Chime quá dày.
        - Breakdown behaviour: "mute" / "soft" / "normal".
        - ZenArcMatrix: bias nhẹ density (0.5–1.5).
        """
        if not segments:
            return
        if not self.enable_nature_layer:
            return
        if self.track is None:
            return

        if activity_map is not None:
            self.activity_map = activity_map

        last_event_tick = -10_000_000

        for seg in segments:
            if getattr(seg, "duration_ticks", 0) <= 0:
                continue

            section = (getattr(seg, "section", "") or "").lower()
            sec_type = (getattr(seg, "section_type", "") or section).lower()
            is_breakdown = sec_type == "breakdown"

            # Base energy từ segment (Zen Arc / energy_bias)
            energy = float(getattr(seg, "energy_bias", 0.5))
            energy = _clamp(energy, 0.0, 1.0)

            # Breakdown behaviour
            if is_breakdown:
                if self.breakdown_mode == "mute":
                    # Không sinh gì trong đoạn này
                    continue
                elif self.breakdown_mode == "soft":
                    # Giảm mạnh energy để nature rất nhẹ
                    energy *= 0.35

            # Mật độ cơ bản theo Arc + energy + intensity tổng
            density = self._compute_segment_density(sec_type or section, energy)

            # ZenArcMatrix factor (nếu có)
            if self.zen_arc_matrix is not None:
                try:
                    if hasattr(self.zen_arc_matrix, "get_factor_for_segment"):
                        zen_factor = float(self.zen_arc_matrix.get_factor_for_segment(seg))
                        zen_factor = _clamp(zen_factor, 0.5, 1.5)
                        density *= zen_factor
                except Exception:
                    pass

            density = _clamp(density, 0.0, 1.0)
            if density <= 0.0:
                continue

            # Spacing & grid theo nature_profile
            min_spacing_ticks, step_ticks = self._get_timing_params()

            t = seg.start_tick
            while t < seg.end_tick:
                # Né vùng activity cao (Melody/Pulse/Chime đang bận)
                if self.activity_map is not None:
                    act = self._get_activity(self.activity_map, t)
                    if act >= self.activity_threshold:
                        t += step_ticks
                        continue

                # Không bắn quá sát event trước
                if t - last_event_tick < min_spacing_ticks:
                    t += step_ticks
                    continue

                # Xác suất base
                prob = density

                # Breath factor: ưu tiên exhale (âm thiên nhiên "thở" cùng background)
                breath_factor = 1.0
                if tempo_map is not None:
                    breath_factor = self._breath_phase_factor(tempo_map, t)
                    # Blend với 1.0 theo nature_breath_amount
                    prob *= 1.0 + (breath_factor - 1.0) * self.nature_breath_amount

                prob = _clamp(prob, 0.0, 1.0)

                if random.random() < prob:
                    # Emit event: 1 cụm nature (1–3 note tuỳ loại)
                    event_len = self._emit_nature_event(
                        t,
                        seg,
                        sec_type=sec_type or section,
                        energy=energy,
                        breath_factor=breath_factor,
                    )
                    last_event_tick = t
                    # Dịch t nhẹ về phía sau (tránh spam)
                    t += max(step_ticks, event_len)
                else:
                    t += step_ticks

    # =========================
    # INTERNAL HELPERS
    # =========================

    def _compute_segment_density(self, sec_type: str, energy: float) -> float:
        """
        Mật độ nature theo Zen Arc + energy + intensity tổng:
        - Grounding/Intro: moderate, không quá đông.
        - Immersion: đều, ổn định.
        - Awakening/Peak: có thể hơi dày hơn (rừng thức dậy, chim nhiều hơn).
        - Integration/Outro: giảm dần.
        - Breakdown: rất thưa nếu không bị mute.
        """
        base = self.nature_intensity

        s = (sec_type or "").lower()
        if s in ("intro", "grounding"):
            arc_factor = 0.6
        elif s in ("immersion",):
            arc_factor = 0.9
        elif s in ("awakening", "peak"):
            arc_factor = 1.1
        elif s in ("integration", "outro"):
            arc_factor = 0.5
        elif s in ("breakdown", "silence"):
            arc_factor = 0.2
        else:
            arc_factor = 0.7

        # Energy 0–1 -> 0.7–1.3
        energy_factor = 0.7 + 0.6 * energy

        # Master intensity 0–1 -> 0.6–1.3
        intensity_factor = 0.6 + 0.7 * self.master_intensity

        density = base * arc_factor * energy_factor * intensity_factor
        return _clamp(density, 0.0, 1.0)

    def _get_timing_params(self) -> Tuple[int, int]:
        """
        Xác định spacing & grid step theo nature_profile:
        - rain       : dày hơn, step ~ 0.5 beat
        - forest     : bước 1 beat
        - river/ocean: dài & đều, step ~ 2 beat
        - fireplace  : crackle nhanh nhưng thưa -> 0.25–0.5 beat
        """
        if self.nature_profile == "rain":
            step_beats = 0.5
            spacing_beats = max(self.min_spacing_beats, 0.5)
        elif self.nature_profile == "forest":
            step_beats = 1.0
            spacing_beats = max(self.min_spacing_beats, 1.0)
        elif self.nature_profile in ("river", "ocean"):
            step_beats = 2.0
            spacing_beats = max(self.min_spacing_beats, 2.0)
        elif self.nature_profile == "fireplace":
            step_beats = 0.5
            spacing_beats = max(self.min_spacing_beats, 0.75)
        else:
            step_beats = 1.0
            spacing_beats = max(self.min_spacing_beats, 1.0)

        step_ticks = max(1, int(self.ppq * step_beats))
        min_spacing_ticks = max(1, int(self.ppq * spacing_beats))
        return min_spacing_ticks, step_ticks

    def _get_activity(self, activity_map: ActivityMap, tick: int) -> float:
        """
        Đọc activity từ ActivityMap:
        - Nếu có get_activity_and_breath: dùng luôn.
        - Nếu không: dùng get_activity_at.
        """
        if activity_map is None:
            return 0.0

        try:
            if hasattr(activity_map, "get_activity_and_breath"):
                val = activity_map.get_activity_and_breath(tick)
            else:
                val = activity_map.get_activity_at(tick)
            return float(val)
        except Exception:
            return 0.0

    def _breath_phase_factor(self, tempo_map: TempoMap, tick: int) -> float:
        """
        Hệ số ưu tiên theo pha breath:
        - Inhale (0.0–0.5): factor ≈ 0.7–0.9
        - Exhale (0.5–1.0): factor ≈ 1.0–1.3
        """
        if tempo_map is None:
            return 1.0

        cycle_bars = getattr(tempo_map, "breath_cycle_bars", 2.0) or 2.0
        try:
            bar_pos = tempo_map.get_bar_pos_at_tick(tick)
            phase = (bar_pos / cycle_bars) % 1.0  # 0..1
        except Exception:
            phase = 0.0

        # LFO sin: 0 tại inhale-start, 1 tại mid-exhale
        lfo = (math.sin(phase * 2.0 * math.pi - (math.pi / 2.0)) + 1.0) / 2.0  # 0..1
        factor = 0.7 + 0.6 * lfo  # 0.7–1.3
        return factor

    def _emit_nature_event(
        self,
        tick: int,
        seg: Segment,
        *,
        sec_type: str,
        energy: float,
        breath_factor: float,
    ) -> int:
        """
        Sinh 1 cụm NATURE và trả về độ dài event dài nhất trong cụm.
        """
        if self.nature_profile == "rain":
            return self._emit_rain(tick, seg, sec_type, energy, breath_factor)
        elif self.nature_profile == "forest":
            return self._emit_forest(tick, seg, sec_type, energy, breath_factor)
        elif self.nature_profile in ("river", "ocean"):
            return self._emit_water(tick, seg, sec_type, energy, breath_factor)
        elif self.nature_profile == "fireplace":
            return self._emit_fireplace(tick, seg, sec_type, energy, breath_factor)
        else:
            return self._emit_forest(tick, seg, sec_type, energy, breath_factor)

    # ===== PROFILE-SPECIFIC EMITTERS =====

    def _emit_rain(
        self,
        tick: int,
        seg: Segment,
        sec_type: str,
        energy: float,
        breath_factor: float,
    ) -> int:
        """
        Mưa: cụm 2–3 note rải gần nhau, velocity vừa.
        """
        max_dur = 0
        count = random.randint(2, 3)
        for _ in range(count):
            dt = int(random.uniform(0.0, 0.5) * self.ppq)
            t = tick + dt
            if t >= seg.end_tick:
                continue
            pitch = self._choose_pitch(layer="rain")
            dur = int(self.ppq * random.uniform(0.25, 1.0))
            vel = self._compute_velocity(kind="rain")
            self._apply_pan_jitter(t)
            self._add_note(
                pitch=pitch,
                velocity=vel,
                start_tick=t,
                duration=dur,
                seg=seg,
                energy=energy,
                breath_factor=breath_factor,
                nature_kind="rain",
            )
            max_dur = max(max_dur, dur)
        return max_dur or int(self.ppq * 0.5)

    def _emit_forest(
        self,
        tick: int,
        seg: Segment,
        sec_type: str,
        energy: float,
        breath_factor: float,
    ) -> int:
        """
        Rừng: 1–2 note ở quãng cao, như chim hót/thỉnh thoảng lá xào xạc.
        """
        max_dur = 0
        count = random.randint(1, 2)
        for _ in range(count):
            dt = int(random.uniform(0.0, 0.75) * self.ppq)
            t = tick + dt
            if t >= seg.end_tick:
                continue
            pitch = self._choose_pitch(layer="forest")
            dur = int(self.ppq * random.uniform(0.3, 1.2))
            vel = self._compute_velocity(kind="forest")
            self._apply_pan_jitter(t)
            self._add_note(
                pitch=pitch,
                velocity=vel,
                start_tick=t,
                duration=dur,
                seg=seg,
                energy=energy,
                breath_factor=breath_factor,
                nature_kind="forest",
            )
            max_dur = max(max_dur, dur)
        return max_dur or int(self.ppq * 0.75)

    def _emit_water(
        self,
        tick: int,
        seg: Segment,
        sec_type: str,
        energy: float,
        breath_factor: float,
    ) -> int:
        """
        River/Ocean: 1 note dài, hơi overlap sang event sau, tạo cảm giác flow liên tục.
        """
        pitch = self._choose_pitch(layer="water")
        dur = int(self.ppq * random.uniform(2.0, 4.0))
        end_tick = min(seg.end_tick, tick + dur)
        dur = max(1, end_tick - tick)
        vel = self._compute_velocity(kind="water")
        self._apply_pan_jitter(tick)
        self._add_note(
            pitch=pitch,
            velocity=vel,
            start_tick=tick,
            duration=dur,
            seg=seg,
            energy=energy,
            breath_factor=breath_factor,
            nature_kind="water",
        )
        return dur

    def _emit_fireplace(
        self,
        tick: int,
        seg: Segment,
        sec_type: str,
        energy: float,
        breath_factor: float,
    ) -> int:
        """
        Fireplace: crackle – cụm 1–3 note rất ngắn, random.
        """
        max_dur = 0
        count = random.randint(1, 3)
        for _ in range(count):
            dt = int(random.uniform(0.0, 0.3) * self.ppq)
            t = tick + dt
            if t >= seg.end_tick:
                continue
            pitch = self._choose_pitch(layer="fire")
            dur = int(self.ppq * random.uniform(0.1, 0.4))
            vel = self._compute_velocity(kind="fire")
            self._apply_pan_jitter(t)
            self._add_note(
                pitch=pitch,
                velocity=vel,
                start_tick=t,
                duration=dur,
                seg=seg,
                energy=energy,
                breath_factor=breath_factor,
                nature_kind="fire",
            )
            max_dur = max(max_dur, dur)
        return max_dur or int(self.ppq * 0.4)

    # =========================
    # PITCH & VELOCITY
    # =========================

    def _choose_pitch(self, layer: str) -> int:
        """
        Chọn pitch dựa trên nature_profile:
        - Không phụ thuộc scale, vì patch Nature thường là sample SFX.
        - Chỉ cần chọn quanh base_note ở các octave khác nhau.
        """
        low_oct = self.octave_low
        high_oct = self.octave_high

        if layer == "forest":
            # Chim: quãng cao hơn
            octv = random.randint(max(low_oct + 1, low_oct), high_oct)
            offset = random.choice([0, 2, 4, 7, 9])  # gần kiểu major pentatonic
        elif layer == "rain":
            octv = random.randint(
                low_oct, high_oct - 1 if high_oct > low_oct else high_oct
            )
            offset = random.choice([0, 1, 2, 3])  # cluster mưa nhẹ
        elif layer == "water":
            octv = random.randint(
                low_oct - 1 if low_oct > 0 else low_oct, low_oct + 1
            )
            offset = random.choice([0, -2, 2])  # hơi trầm
        elif layer == "fire":
            octv = random.randint(low_oct, low_oct + 1)
            offset = random.choice([-1, 0, 1, 2])
        else:
            octv = random.randint(low_oct, high_oct)
            offset = 0

        base_oct = self.base_note // 12
        base_pc = self.base_note % 12
        target_oct = base_oct + (octv - 4)
        pitch = base_pc + offset + target_oct * 12
        return max(0, min(127, pitch))

    def _compute_velocity(self, kind: str) -> int:
        """
        Velocity theo loại ambience + intensity:
        - rain/forest: trung bình, hơi random.
        - water/ocean: thấp nhưng đều.
        - fire: hơi sắc hơn.
        """
        base = self.base_velocity

        if kind == "rain":
            base_delta = -10
        elif kind == "forest":
            base_delta = -5
        elif kind == "water":
            base_delta = -15
        elif kind == "fire":
            base_delta = 0
        else:
            base_delta = -5

        # nature_intensity 0–1 -> 0.5–1.2
        nature_factor = 0.5 + 0.7 * self.nature_intensity

        # master_intensity 0–1 -> 0.6–1.2
        master_factor = 0.6 + 0.6 * self.master_intensity

        vel = int((base + base_delta) * nature_factor * master_factor)
        vel += random.randint(-self.vel_jitter, self.vel_jitter)
        vel = max(1, min(127, vel))
        return vel

    def _apply_pan_jitter(self, tick: int) -> None:
        """
        Pan nhẹ quanh center (64) để nature không đứng yên:
        - ± nature_pan_jitter (mặc định ~8).
        """
        if self.pan_jitter <= 0 or self.track is None:
            return
        center = 64
        offset = random.randint(-self.pan_jitter, self.pan_jitter)
        pan_val = max(0, min(127, center + offset))
        self.track.add_cc(tick, 10, pan_val)

    # =========================
    # NOTE + SAFETY + ACTIVITY
    # =========================

    def _add_note(
        self,
        *,
        pitch: int,
        velocity: int,
        start_tick: int,
        duration: int,
        seg: Segment,
        energy: float,
        breath_factor: float,
        nature_kind: str,
    ) -> None:
        """
        Ghi note Nature + áp dụng:
        - RegisterManager (nếu có).
        - SafetyFilter (có meta chuẩn).
        - ActivityMap.add_activity (Nature = weight nhẹ).
        """
        if duration <= 0 or self.track is None:
            return

        p = int(pitch)
        v = int(velocity)
        t = int(start_tick)
        d = int(duration)

        # RegisterManager
        if self.register_manager is not None:
            try:
                if hasattr(self.register_manager, "apply_register"):
                    p = int(
                        self.register_manager.apply_register(
                            self.layer_name, p, t
                        )
                    )
                elif hasattr(self.register_manager, "apply_for_layer"):
                    p = int(
                        self.register_manager.apply_for_layer(
                            layer=self.layer_name,
                            pitch=p,
                            tick=t,
                        )
                    )
                elif hasattr(self.register_manager, "constrain_pitch"):
                    p = int(self.register_manager.constrain_pitch(self.layer_name, p))
            except Exception:
                pass

        p = max(0, min(127, p))
        v = max(1, min(127, v))

        # SafetyFilter + meta
        allowed = True
        if self.safety_filter is not None:
            sec_type = (getattr(seg, "section_type", "") or "").lower()
            meta = {
                "layer": self.layer_name,
                "section_type": sec_type,
                "energy_bias": float(_clamp(energy, 0.0, 1.0)),
                "t_norm": getattr(seg, "t_norm", None),
                "nature_profile": self.nature_profile,
                "nature_kind": nature_kind,
                "breath_factor": float(_clamp(breath_factor, 0.0, 2.0)),
            }
            try:
                if hasattr(self.safety_filter, "filter_note"):
                    # Ưu tiên signature có meta, fallback nếu TypeError
                    try:
                        res = self.safety_filter.filter_note(
                            layer=self.layer_name,
                            pitch=p,
                            velocity=v,
                            tick=t,
                            meta=meta,
                        )
                    except TypeError:
                        res = self.safety_filter.filter_note(
                            layer=self.layer_name,
                            pitch=p,
                            velocity=v,
                            tick=t,
                        )

                    if isinstance(res, (tuple, list)) and len(res) >= 3:
                        allowed, p, v = (
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
                                pitch=p,
                                velocity=v,
                                tick=t,
                                meta=meta,
                            )
                        )
                    except TypeError:
                        allowed = bool(
                            self.safety_filter.allow_note(
                                layer=self.layer_name,
                                pitch=p,
                                velocity=v,
                                tick=t,
                            )
                        )
            except Exception:
                allowed = True

        if not allowed:
            return

        p = max(0, min(127, p))
        v = max(1, min(127, v))

        self.track.add_note(p, v, t, d)

        # Ghi activity nhẹ, để lớp sau biết Nature chiếm background
        if self.activity_map is not None:
            try:
                self.activity_map.add_activity(
                    t,
                    d,
                    weight=self.nature_activity_weight,
                )
            except Exception:
                pass
