from __future__ import annotations

# Tệp: src/engines/air_engine.py
# (FINAL V10.10.2) - AIR ENGINE V1
# (ZEN DENSITY 2.0 + ARC-AWARE + SPECTRAL MORPHING + AIR MOTION + BREATH PHASE + PENTATONIC AIR + ZEN CORE HOOKS)
#
# Mục tiêu:
# - Tạo lớp AIR (hơi, tiếng gió, hạt) ở quãng cao, thưa.
# - Zen Density 2.0:
#       density = air_intensity * density_arg * arc * energy_factor * activity_factor * zen_arc_factor.
# - Arc-aware: phản ứng với section_type (intro / immersion / peak / breakdown...).
# - Né Melody khi khu vực đó đang quá bận (dựa trên ActivityMap).
# - Spectral Morphing: CC1 / CC74 / CC71 để gió "biến hình" mềm mại.
# - Air Motion: pan & brightness trôi chậm theo tick.
# - Breath:
#       + air_breath_amount = độ sâu hiệu ứng thở (0–1).
#       + Nếu ActivityMap trả về breath_phase (0–1), brightness sẽ "thở" theo chu kỳ.
# - Pentatonic Air:
#       + profile.air_scale_mode = "diatonic" / "pentatonic_relax"
#       + Nếu "pentatonic_relax" → lọc scale giống logic MelodyEngineV10 (major/minor pent).
#
# Zen Core Integration:
# - Hooks:
#       + safety_filter, register_manager, breath_sync, activity_map, zen_arc_matrix, layer_name="air".
# - Mọi nốt Air đều có thể đi qua:
#       + RegisterManager → constrain quãng nếu preset dùng patch tonal.
#       + SafetyFilter     → scan pitch/velocity/density với meta chuẩn hoá.
#
# Thiết kế:
#   eng = AirEngineV1(
#       writer, profile,
#       density=0.7,
#       channel=10,
#       scale_family="diatonic",
#       safety_filter=...,
#       register_manager=...,
#       breath_sync=...,
#       activity_map=...,
#       zen_arc_matrix=...,
#       layer_name="air",
#   )
#   eng.render(segments, key, scale_type, activity_map_from_melody)
#
# Backward-compatible:
# - Giữ nguyên signature render(..., melody_map) để không phá code cũ.
# - Nếu melody_map=None nhưng self.activity_map có → dùng self.activity_map.

import random
import math
from typing import List, Optional, Tuple, Any

from src.utils.midi_writer import MidiWriter
from src.core.music_theory import Scale, Chord, note_number
from src.utils.activity_map import ActivityMap
from src.utils.config_loader import InstrumentProfile
from src.core.structure_builder import Segment


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

class AirEngineV1:
    def __init__(
        self,
        writer: MidiWriter,
        profile: InstrumentProfile,
        density: float = 0.7,
        channel: int = 10,
        scale_family: str = "diatonic",
        # Neo Zen hooks (tuỳ chọn, giữ backward-compatible)
        safety_filter: Optional[object] = None,
        register_manager: Optional[object] = None,
        breath_sync: Optional[object] = None,
        activity_map: Optional[ActivityMap] = None,
        zen_arc_matrix: Optional[object] = None,
        layer_name: str = "air",
        **kwargs: Any,
    ) -> None:
        """
        :param writer: MidiWriter hoặc DynamicTransposingWriter.
        :param profile: InstrumentProfile (program, enable_morph...).
        :param density: Mật độ tương đối (0.0–1.5) cho số "gusts".
        :param channel: MIDI channel cho lớp AIR.
        :param scale_family: họ scale cho lớp Air (diatonic / pentatonic...).
        :param safety_filter: Neo Zen SafetyFilter (optional).
        :param register_manager: RegisterManager (optional).
        :param breath_sync: BreathSyncManager (optional, chưa dùng trực tiếp).
        :param activity_map: ActivityMap toàn cục (fallback nếu không truyền melody_map ở render).
        :param zen_arc_matrix: ZenArcMatrix (bias nhẹ density theo Arc).
        :param layer_name: tên layer cho meta/safety ("air").
        """
        self.writer = writer
        self.track = writer.get_track(channel) if writer is not None else None
        self.profile = profile
        self.channel = int(channel)
        self.ppq = int(getattr(writer, "ppq", 480))

        # Neo Zen hooks
        self.safety_filter = safety_filter
        self.register_manager = register_manager
        self.breath_sync = breath_sync
        self.activity_map = activity_map
        self.zen_arc_matrix = zen_arc_matrix
        self.layer_name = layer_name or "air"

        # Hệ scale cho AIR
        self.scale_family = scale_family or "diatonic"

        # Air scale mode: "diatonic" / "pentatonic_relax"
        self.air_scale_mode: str = str(
            getattr(profile, "air_scale_mode", "diatonic")
        ).lower()

        # Vùng octave: ưu tiên quãng cao; cho phép override từ profile
        octave_range = getattr(profile, "air_octave_range", [6, 7])
        if not isinstance(octave_range, (list, tuple)) or not octave_range:
            octave_range = [6, 7]
        vals = [int(o) for o in octave_range]
        lo_o = min(vals)
        hi_o = max(vals)
        self.octave_range = [lo_o, hi_o]

        # [V9.9.32] Config Morphing (bật/tắt qua profile)
        self.enable_morph = bool(getattr(profile, "enable_morph", True))

        # Air Motion: pan/brightness trôi chậm
        self.enable_motion = bool(getattr(profile, "enable_air_motion", True))

        # Zen Density shaping theo energy/activity
        self.enable_energy_shaping = bool(
            getattr(profile, "enable_energy_shaping", True)
        )

        # Cường độ tổng thể Air (0–1): giống "mix" cho lớp khí
        base_air_intensity = float(getattr(profile, "air_intensity", 0.6))
        base_air_intensity = _clamp(base_air_intensity, 0.0, 1.0)

        # Tham số density từ constructor (giữ backward compatible)
        self.density_arg = _clamp(float(density), 0.0, 1.5)

        # Air intensity cuối cùng dùng trong Zen Density 2.0
        self.air_intensity = _clamp(
            base_air_intensity * max(self.density_arg, 0.1), 0.0, 1.0
        )

        # Velocity base & jitter
        self.base_velocity = int(getattr(profile, "velocity", 60))
        self.vel_jitter = int(getattr(profile, "vel_jitter", 8))
        self.vel_jitter = max(0, self.vel_jitter)

        # Activity threshold: nếu ActivityMap vượt ngưỡng thì né
        self.activity_threshold = float(
            getattr(profile, "air_activity_threshold", 0.7)
        )
        self.activity_threshold = _clamp(self.activity_threshold, 0.0, 1.0)

        # Air Motion amounts
        self.pan_motion_amount = float(getattr(profile, "pan_motion_amount", 0.7))
        self.pan_motion_amount = _clamp(self.pan_motion_amount, 0.0, 1.0)

        self.filter_motion_amount = float(
            getattr(profile, "filter_motion_amount", 0.5)
        )
        self.filter_motion_amount = _clamp(self.filter_motion_amount, 0.0, 1.0)

        # Breakdown mode: "soft" / "mute" / "normal"
        self.breakdown_mode = str(
            getattr(profile, "air_breakdown_mode", "soft")
        ).lower()
        if self.breakdown_mode not in ("soft", "mute", "normal"):
            self.breakdown_mode = "soft"

        # Breath amount cho Air (0–1): độ sâu hiệu ứng "thở" trên brightness
        self.breath_amount = float(getattr(profile, "air_breath_amount", 0.4))
        self.breath_amount = _clamp(self.breath_amount, 0.0, 1.0)

        # Lưu breath_phase gần nhất (fallback nếu không có từ ActivityMap)
        self._last_breath_phase: float = 0.5

    # ------------------------------------------------------
    # Helper: resolve ActivityMap source
    # ------------------------------------------------------
    def _resolve_activity_map(
        self, local_map: Optional[ActivityMap]
    ) -> Optional[ActivityMap]:
        """
        Ưu tiên ActivityMap truyền vào render (melody_map).
        Nếu None → fallback sang self.activity_map.
        """
        if local_map is not None:
            return local_map
        return self.activity_map

    # ------------------------------------------------------
    # Helper: đọc activity + breath từ ActivityMap
    # ------------------------------------------------------
    def _get_activity_and_breath(
        self, activity_map: Optional[ActivityMap], tick: int
    ) -> Tuple[float, float]:
        """
        Cố gắng đọc:
        - activity   ∈ [0, 1]: mức độ "bận" tại tick.
        - breath     ∈ [0, 1]: pha thở, nếu có.
        Hỗ trợ nhiều API khác nhau để tương thích các version ActivityMap:
        - get_activity_and_breath(tick) -> (activity, breath)
        - get_energy_at_tick(track_name, tick)
        - get_track_energy(track_name, tick)
        - get_activity_at_tick(track_name, tick)
        - get_activity_at(tick)
        """
        activity = 0.0
        breath = self._last_breath_phase

        if activity_map is None:
            return activity, breath

        try:
            # API mới: có cả activity & breath
            if hasattr(activity_map, "get_activity_and_breath"):
                val = activity_map.get_activity_and_breath(tick)
                if isinstance(val, (list, tuple)):
                    if len(val) >= 1:
                        activity = float(val[0])
                    if len(val) >= 2:
                        breath = float(val[1])
                else:
                    activity = float(val)
            else:
                # Ưu tiên API có track_name
                if hasattr(activity_map, "get_energy_at_tick"):
                    activity = float(
                        activity_map.get_energy_at_tick("MELODY", tick)
                    )
                elif hasattr(activity_map, "get_track_energy"):
                    activity = float(
                        activity_map.get_track_energy("MELODY", tick)
                    )
                elif hasattr(activity_map, "get_activity_at_tick"):
                    activity = float(
                        activity_map.get_activity_at_tick("MELODY", tick)
                    )
                # API cũ: không có track_name
                elif hasattr(activity_map, "get_activity_at"):
                    activity = float(activity_map.get_activity_at(tick))
        except Exception:
            activity = 0.0

        activity = _clamp(activity, 0.0, 1.0)
        breath = _clamp(breath, 0.0, 1.0)
        self._last_breath_phase = breath
        return activity, breath

    def _get_activity_level(
        self, activity_map: Optional[ActivityMap], tick: int
    ) -> float:
        """
        Wrapper cho code cũ: chỉ cần activity.
        (Giữ để không phải đổi signature ở chỗ khác.)
        """
        act, _ = self._get_activity_and_breath(activity_map, tick)
        return act

    # ------------------------------------------------------
    # Render
    # ------------------------------------------------------
    def render(
        self,
        segments: List[Segment],
        key: str,
        scale_type: str,
        melody_map: Optional[ActivityMap],
    ) -> None:
        """
        Render lớp AIR:

        - Mỗi Segment sẽ sinh ra 0–3 "gusts" (cụm gió) tuỳ Zen Density 2.0 + ZenArcMatrix.
        - Gust né vùng có Activity > activity_threshold.
        - Trong mỗi gust: random vài note rải ở quãng cao, dùng nốt tránh root & fifth.
        - Nếu ActivityMap cung cấp breath_phase → brightness "thở" theo chu kỳ.
        - Mọi nốt Air đều có thể đi qua RegisterManager + SafetyFilter (nếu có).
        """
        if not segments or self.track is None:
            return

        full_scale = Scale(key, scale_type, family=self.scale_family)
        activity_source = self._resolve_activity_map(melody_map)

        for segment in segments:
            if segment.duration_ticks <= 0:
                continue

            # Ưu tiên section_type; fallback sang section
            sec = (
                getattr(segment, "section_type", None)
                or getattr(segment, "section", "")
                or ""
            ).lower()
            is_breakdown = sec in ("breakdown", "silence")

            # Energy của đoạn (0.0–1.0)
            energy = float(getattr(segment, "energy_bias", 0.5))
            energy = _clamp(energy, 0.0, 1.0)

            # Breakdown handling
            if is_breakdown:
                if self.breakdown_mode == "mute":
                    # Không sinh Air trong breakdown
                    continue
                elif self.breakdown_mode == "soft":
                    # Giảm energy để Air gần như rất thưa
                    energy *= 0.35

            # Xây Chord an toàn
            try:
                chord = Chord(segment.chord_name, key, scale_type)
            except Exception:
                chord = Chord(key, key, scale_type)
            if not getattr(chord, "pcs", None):
                continue

            # Mức activity + breath tại giữa segment
            mid_tick = segment.start_tick + segment.duration_ticks // 2
            activity_level, mid_breath = self._get_activity_and_breath(
                activity_source, mid_tick
            )

            # ZenArcMatrix factor (bias nhẹ 0.5–1.5)
            zen_arc_factor = 1.0
            if self.zen_arc_matrix is not None:
                try:
                    fn = getattr(self.zen_arc_matrix, "get_factor_for_segment", None)
                    if callable(fn):
                        zen_arc_factor = float(fn(segment))
                except Exception:
                    zen_arc_factor = 1.0
            zen_arc_factor = _clamp(zen_arc_factor, 0.5, 1.5)

            # Mật độ local (0–1) theo Zen Density 2.0 (+ ZenArcMatrix)
            local_density = self._compute_local_density(
                energy, activity_level, sec, zen_arc_factor
            )
            if local_density <= 0.0:
                continue

            # Tạo danh sách pitch ứng viên dựa trên scale (có pentatonic_relax), né root + fifth
            pitches = self._build_pitch_pool(full_scale, chord, scale_type)
            if not pitches:
                continue

            # Ước lượng số "luồng gió" trong segment
            num_gusts = self._estimate_gust_count(energy, local_density)
            if num_gusts <= 0:
                continue

            for _ in range(num_gusts):
                # Một chút random để tránh đều đều
                if random.random() > local_density:
                    continue

                # Bắt đầu gust nằm trong 70% đầu của segment
                start = segment.start_tick + random.randint(
                    0, max(1, int(segment.duration_ticks * 0.7))
                )
                if start >= segment.end_tick:
                    continue

                # Né khu vực Melody quá bận ngay tại start
                local_act, breath_start = self._get_activity_and_breath(
                    activity_source, start
                )
                if local_act >= self.activity_threshold:
                    continue

                # Độ dài cửa sổ gust
                gust_len = random.randint(self.ppq, self.ppq * 2)

                # Áp dụng motion/morph tại đầu gust (dùng breath_start)
                self._apply_air_motion_and_morph(start, energy, breath_start)

                # Mỗi gust gồm 3–6 note, rải trong cửa sổ gust_len
                burst_count = random.randint(3, 6)
                for _ in range(burst_count):
                    t_on = start + random.randint(0, gust_len)
                    if t_on >= segment.end_tick:
                        continue

                    pitch = random.choice(pitches)
                    dur = random.randint(
                        int(self.ppq * 0.25), int(self.ppq * 0.8)
                    )

                    vel = self._compute_velocity(energy)

                    # Emit note qua RegisterManager + SafetyFilter (nếu có)
                    self._emit_note(
                        pitch=pitch,
                        vel=vel,
                        start_tick=t_on,
                        duration_ticks=dur,
                        segment=segment,
                        activity_level=local_act,
                        breath_phase=breath_start,
                    )

    # =========================
    # INTERNAL HELPERS
    # =========================
    def _get_air_scale_pcs(
        self, scale: Scale, scale_type: str, chord: Chord
    ) -> set[int]:
        """
        Lấy pitch classes cho Air, có hỗ trợ:
        - air_scale_mode = "pentatonic_relax" → lọc ngũ cung mềm (major/minor).
        """
        # Vẫn tương thích với scale cũ (có thể có field pcs hoặc method)
        try:
            pcs = list(getattr(scale, "pcs", []) or scale.get_pitch_classes())
        except Exception:
            pcs = list(getattr(scale, "pcs", []) or [])

        if not pcs:
            root_pc = getattr(scale, "root_pc", chord.root_pc)
            pcs = [root_pc]

        if self.air_scale_mode == "pentatonic_relax":
            # Lấy root từ scale, fallback sang chord
            root = getattr(scale, "root_pc", chord.root_pc)
            st = (scale_type or "").lower()

            if "minor" in st or "dorian" in st:
                allowed_intervals = [0, 3, 5, 7, 10]  # minor pentatonic
            else:
                allowed_intervals = [0, 2, 4, 7, 9]   # major pentatonic

            filtered: List[int] = []
            for pc in pcs:
                interval = (pc - root) % 12
                if interval in allowed_intervals:
                    filtered.append(pc)

            if filtered:
                pcs = filtered

        return set(pcs)

    def _build_pitch_pool(
        self, scale: Scale, chord: Chord, scale_type: str
    ) -> List[int]:
        """
        Tạo danh sách pitch cho Air:
        - Dựa trên scale chung (có thể pentatonic_relax).
        - Né root & perfect fifth để không đè drone chính.
        """
        avoid = {chord.root_pc, (chord.root_pc + 7) % 12}

        scale_pcs = self._get_air_scale_pcs(scale, scale_type, chord)
        if not scale_pcs:
            scale_pcs = {getattr(scale, "root_pc", chord.root_pc)}

        candidates = list(scale_pcs - avoid)
        if not candidates:
            candidates = [p for p in scale_pcs if p != chord.root_pc]
        if not candidates:
            candidates = list(scale_pcs) or [chord.root_pc]

        pitches: List[int] = []
        lo_oct = int(self.octave_range[0])
        hi_oct = int(self.octave_range[1])
        if lo_oct > hi_oct:
            lo_oct, hi_oct = hi_oct, lo_oct

        for o in range(lo_oct, hi_oct + 1):
            for pc in candidates:
                pitches.append(note_number(pc, o))
        return pitches

    def _compute_local_density(
        self,
        energy: float,
        activity_level: float,
        section_type: str,
        zen_arc_factor: float = 1.0,
    ) -> float:
        """
        Tính mật độ Air:
        - Dựa trên:
            + air_intensity * density_arg (tổng mix của lớp khí)
            + energy (Zen Arc)
            + section_type (Intro/Immersion/Peak/Outro/Breakdown)
            + ActivityMap (né chỗ đang quá dày)
            + zen_arc_factor từ ZenArcMatrix (bias nhẹ 0.5–1.5)
        """
        if not self.enable_energy_shaping:
            base = self.air_intensity
            return _clamp(base, 0.0, 1.0)

        sec = (section_type or "").lower()
        if sec in ("intro", "grounding"):
            arc = 0.4
        elif sec in ("immersion",):
            arc = 0.9
        elif sec in ("awakening", "peak"):
            arc = 1.1
        elif sec in ("integration", "outro"):
            arc = 0.5
        elif sec in ("breakdown", "silence"):
            arc = 0.2
        else:
            arc = 0.7

        # Energy factor 0.5–1.2
        energy_factor = 0.5 + 0.7 * _clamp(energy, 0.0, 1.0)

        # Activity factor: activity càng cao, density càng giảm
        act = _clamp(activity_level, 0.0, 1.0)
        activity_factor = 1.0 - 0.7 * act  # activity = 1 → -70% density

        density = self.air_intensity * arc * energy_factor * activity_factor * zen_arc_factor
        return _clamp(density, 0.0, 1.0)

    def _estimate_gust_count(self, energy: float, density: float) -> int:
        """
        Ước lượng số "luồng gió" trong 1 segment:
        - Energy thấp / density thấp → 0–1 gust.
        - Energy vừa → 1–2 gust.
        - Energy cao + density cao → tối đa ~3 gust.
        """
        if density <= 0.05 or energy <= 0.1:
            return 0

        base = 1
        if energy > 0.4 and density > 0.2:
            base += 1
        if energy > 0.75 and density > 0.5:
            base += 1

        jitter = random.choice([0, 0, 1, -1])
        gusts = max(0, base + jitter)
        return min(gusts, 3)

    def _compute_velocity(self, energy: float) -> int:
        """
        Tính velocity cho từng nốt Air:
        - Nền tảng: base_velocity.
        - Scale theo energy + air_intensity.
        - Jitter nhẹ để tránh máy móc.
        """
        vel = int(self.base_velocity)

        # Scale theo energy: 0.5–1.1
        vel = int(vel * (0.5 + 0.6 * _clamp(energy, 0.0, 1.0)))

        # Scale theo cường độ lớp khí: 0.4–1.0
        vel = int(vel * (0.4 + 0.6 * self.air_intensity))

        # Jitter
        vel += random.randint(-self.vel_jitter, self.vel_jitter)

        return max(1, min(127, vel))

    def _apply_air_motion_and_morph(
        self, tick: int, energy: float, breath_phase: Optional[float] = None
    ) -> None:
        """
        Áp dụng:
        - Air Motion: pan & brightness trôi chậm theo tick.
        - Spectral Morphing cũ (CC1, CC74, CC71) nếu enable_morph.
        - Breath phase:
            + Nếu có breath_phase (0–1) và breath_amount > 0:
              brightness sẽ "hít vào / thở ra" theo sin(phase * pi).
        """
        if self.track is None:
            return

        if breath_phase is None:
            breath_phase = self._last_breath_phase
        breath_phase = _clamp(breath_phase, 0.0, 1.0)
        self._last_breath_phase = breath_phase

        # ----- AIR MOTION -----#
        if self.enable_motion:
            # Motion phase rất chậm: 1 chu kỳ ~ 32 beat
            norm = tick / float(max(1, self.ppq * 32))
            phase = (norm % 1.0) * 2.0 * math.pi

            # Pan quanh center 64, biên độ tùy pan_motion_amount
            pan_center = 64
            pan_span = int(40 * self.pan_motion_amount)  # tối đa ±40
            pan_offset = int(math.sin(phase) * pan_span)
            pan_val = max(0, min(127, pan_center + pan_offset))
            self.track.add_cc(tick, 10, pan_val)

            # Brightness chuyển động nhẹ, phụ thuộc energy
            base_bright = 50 + int(20 * energy)
            bright_span = int(25 * self.filter_motion_amount)
            bright_offset = int(math.cos(phase) * bright_span)
            bright_val = base_bright + bright_offset

            # Hiệu ứng "thở": sin(pi * breath_phase) (0 ở 0/1, 1 ở 0.5)
            if self.breath_amount > 0.0:
                inhale_curve = math.sin(breath_phase * math.pi)
                breath_scale = 1.0 + self.breath_amount * 0.3 * inhale_curve
            else:
                breath_scale = 1.0

            bright_val = int(bright_val * breath_scale)
            bright_val = max(0, min(127, bright_val))
            self.track.add_cc(tick, 74, bright_val)

        # ----- SPECTRAL MORPHING (giữ tương thích preset cũ) -----#
        if self.enable_morph:
            self._apply_spectral_morphing(tick)

    # ------------------------------------------------------
    # Spectral Morphing CC (giữ lại từ V9.9.32)
    # ------------------------------------------------------
    def _apply_spectral_morphing(self, tick: int) -> None:
        """
        V9.9.32 - Spectral Morphing:
        - CC1  (Modulation)   : Rung / chuyển động.
        - CC74 (Brightness)   : Độ sáng tối.
        - CC71 (Resonance)    : Độ cộng hưởng.
        """
        if self.track is None:
            return

        # CC1 (Modulation)
        mod_val = random.randint(20, 80)
        self.track.add_cc(tick, 1, mod_val)

        # CC74 (Brightness)
        bright_val = random.randint(40, 90)
        self.track.add_cc(tick, 74, bright_val)

        # CC71 (Resonance)
        res_val = random.randint(10, 50)
        self.track.add_cc(tick, 71, res_val)

    # ------------------------------------------------------
    # Emit note qua RegisterManager + SafetyFilter
    # ------------------------------------------------------
    def _emit_note(
        self,
        pitch: int,
        vel: int,
        start_tick: int,
        duration_ticks: int,
        segment: Segment,
        activity_level: float,
        breath_phase: float,
    ) -> None:
        """
        Lớp phát nốt trung gian:
        - Cho phép RegisterManager + SafetyFilter can thiệp.
        - Chuẩn hoá meta cho SafetyFilter.
        """
        if self.track is None:
            return

        p = int(pitch)
        v = int(vel)
        t = int(start_tick)
        d = int(duration_ticks)

        # 1) RegisterManager (nếu có) – chỉ dùng nếu patch AIR tonal
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
            except Exception:
                # fallback giữ nguyên pitch
                pass

        p = max(0, min(127, p))
        v = max(1, min(127, v))

        # 2) SafetyFilter (nếu có)
        allowed = True
        if self.safety_filter is not None:
            sec = (
                getattr(segment, "section_type", None)
                or getattr(segment, "section", "")
                or ""
            )
            meta = {
                "layer": self.layer_name,
                "section_type": sec,
                "energy_bias": getattr(segment, "energy_bias", None),
                "t_norm": getattr(segment, "t_norm", None),
                "activity_level": activity_level,
                "breath_phase": breath_phase,
            }
            try:
                # Pattern 1: filter_note(...) trả (allowed, new_pitch, new_vel)
                if hasattr(self.safety_filter, "filter_note"):
                    try:
                        res = self.safety_filter.filter_note(
                            layer=self.layer_name,
                            pitch=p,
                            velocity=v,
                            tick=t,
                            meta=meta,
                        )
                    except TypeError:
                        # SafetyFilter cũ không có tham số meta
                        res = self.safety_filter.filter_note(
                            layer=self.layer_name,
                            pitch=p,
                            velocity=v,
                            tick=t,
                        )

                    if isinstance(res, (tuple, list)) and len(res) >= 3:
                        allowed, p, v = bool(res[0]), int(res[1]), int(res[2])
                    else:
                        allowed = bool(res)
                # Pattern 2: allow_note(...) trả bool
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
                # Bất kỳ lỗi nào trong SafetyFilter đều không chặn pipeline
                allowed = True

        if not allowed:
            return

        p = max(0, min(127, int(p)))
        v = max(1, min(127, int(v)))
        self.track.add_note(p, v, t, d)
