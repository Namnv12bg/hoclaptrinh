from __future__ import annotations

import math
import random
from typing import List, Optional, Dict, Any, Tuple

from src.utils.midi_writer import MidiWriter
from src.core.structure_builder import Segment
from src.core.tempo_breath import TempoMap
from src.core.music_theory import Scale, note_number
from src.utils.config_loader import InstrumentProfile
from src.utils.activity_map import ActivityMap

# Các core type dùng làm hook (optional, để tránh lỗi Import khi test độc lập)
try:  # pragma: no cover
    from src.core.register_manager import RegisterManager
except Exception:  # pragma: no cover
    RegisterManager = None  # type: ignore[misc]

try:  # pragma: no cover
    from src.core.safety_filter import SafetyFilter
except Exception:  # pragma: no cover
    SafetyFilter = None  # type: ignore[misc]

try:  # pragma: no cover
    from src.core.breath_sync import BreathSyncManager
except Exception:  # pragma: no cover
    BreathSyncManager = None  # type: ignore[misc]

try:  # pragma: no cover
    from src.core.zen_arc_matrix import ZenArcMatrix
except Exception:  # pragma: no cover
    ZenArcMatrix = None  # type: ignore[misc]

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

class HandpanEngineV1:
    """
    Handpan Engine V1 (Neo Zen V11 Standard)

    Tính cách:
        - Không phải solo show, mà là lớp motif mềm trên nền Drone/Harm.
        - Ưu tiên pentatonic_relax / diatonic “an toàn tai”.
        - Tôn trọng Zen Arc + ActivityMap (không spam nốt khi mix đã dày).
    """

    def __init__(
        self,
        writer: MidiWriter,
        profile: InstrumentProfile,
        channel: int = 10,
        *,
        safety_filter: Optional["SafetyFilter"] = None,
        register_manager: Optional["RegisterManager"] = None,
        breath_sync: Optional["BreathSyncManager"] = None,
        activity_map: Optional["ActivityMap"] = None,
        zen_arc_matrix: Optional["ZenArcMatrix"] = None,
        tempo_map: Optional[TempoMap] = None,
        user_options: Optional[Dict[str, Any]] = None,
        layer_name: str = "handpan",
    ):
        self.writer = writer
        self.profile = profile
        self.channel = channel
        self.track = writer.get_track(self.channel)
        self.ppq = writer.ppq
        self.user_options = user_options or {}

        # Hooks
        self.safety_filter = safety_filter
        self.register_manager = register_manager
        self.breath_sync = breath_sync
        self.activity_map = activity_map
        self.zen_arc_matrix = zen_arc_matrix
        self.layer_name = layer_name or "handpan"
        self.tempo_map = tempo_map

        # ===== Switches =====
        self.enabled = bool(
            self.user_options.get(
                "enable_handpan_layer",
                getattr(profile, "enable_handpan_layer", False),
            )
        )

        # handpan_mode: "soft" / "flow" / "spark"
        self.mode = str(
            getattr(profile, "handpan_mode", self.user_options.get("handpan_mode", "soft"))
        ).lower()
        if self.mode not in ("soft", "flow", "spark"):
            self.mode = "soft"

        # ===== Tone & Mix =====
        self.base_velocity = int(getattr(profile, "velocity", 80))
        self.base_velocity = int(_clamp(self.base_velocity, 1, 127))

        self.mix_level = float(getattr(profile, "mix_level", 0.9))
        self.mix_level = _clamp(self.mix_level, 0.0, 1.0)

        # Accent note (ding) gain
        self.accent_boost = float(getattr(profile, "accent_boost", 1.25))
        self.accent_boost = _clamp(self.accent_boost, 1.0, 1.8)

        # ===== Rhythm & Density =====
        # Số hit cơ bản mỗi bar (4/4). Soft: ít, Flow: vừa, Spark: nhiều.
        default_hits = {
            "soft": 1.5,
            "flow": 3.0,
            "spark": 4.5,
        }.get(self.mode, 2.0)
        self.hits_per_bar = float(getattr(profile, "hits_per_bar", default_hits))
        self.hits_per_bar = _clamp(self.hits_per_bar, 0.5, 8.0)

        # Humanize (ms) – dịch tick nhẹ để tránh máy móc
        self.humanize_ms = float(getattr(profile, "humanize_ms", 30.0))
        self.humanize_ms = _clamp(self.humanize_ms, 0.0, 80.0)

        # Chia pattern thành bao nhiêu bước trong 1 bar (pattern grid)
        self.grid_division = int(getattr(profile, "grid_division", 8))
        if self.grid_division <= 0:
            self.grid_division = 8

        # ===== Pitch / Scale =====
        # Handpan thích hợp nhất với pentatonic_relax, fallback diatonic.
        self.scale_family = str(
            getattr(profile, "scale_family", "pentatonic_relax")
        ).lower()
        if self.scale_family not in ("pentatonic_relax", "diatonic"):
            self.scale_family = "pentatonic_relax"

        # Octave chính cho “ding” / motif
        self.main_oct = int(getattr(profile, "handpan_main_oct", 4))
        self.low_oct = int(getattr(profile, "handpan_low_oct", 3))
        self.high_oct = int(getattr(profile, "handpan_high_oct", 5))

        # Ding = note cao nhất (hoặc được chỉ định)
        self.ding_pc = getattr(profile, "ding_pc", None)  # type: ignore[attr-defined]

        # ===== Activity Aware =====
        self.activity_threshold = float(
            getattr(profile, "handpan_activity_threshold", 0.8)
        )
        self.activity_threshold = _clamp(self.activity_threshold, 0.0, 1.5)

        # ===== Breath CC (timbre modulation) =====
        self.enable_breath_cc = bool(
            getattr(profile, "enable_breath_cc", True)
        )
        self.breath_depth = float(getattr(profile, "breath_depth", 18.0))
        self.breath_depth = _clamp(self.breath_depth, 0.0, 36.0)

    # ================================================================
    # PUBLIC
    # ================================================================
    def render(
        self,
        segments: List[Segment],
        key: str,
        scale: str,
        tempo_map: Optional[TempoMap] = None,
        activity_map: Optional[ActivityMap] = None,
        *,
        tuning_plan: Optional[Any] = None,  # Phase 2 – hiện tại chưa sử dụng
        **kwargs,
    ) -> None:
        """
        Render lớp Handpan.

        - key / scale: dùng để build scale (thường pentatonic_relax).
        - tempo_map: dùng cho breath LFO + convert ms→ticks cho humanize.
        - activity_map: nếu truyền vào, ưu tiên hơn self.activity_map.
        - tuning_plan: hook cho Phase 2 (Solf / Journey) – hiện tại bỏ qua.
        """
        if not self.enabled:
            return
        if not segments:
            return
        if self.track is None:
            return

        if tempo_map is not None:
            self.tempo_map = tempo_map
        tempo_map = self.tempo_map

        if activity_map is not None:
            self.activity_map = activity_map

        # Xây scale/pitch pool một lần
        try:
            scale_obj = Scale(key, scale, family=self.scale_family)
        except Exception:
            scale_obj = Scale(key, scale)  # type: ignore[arg-type]

        pitch_pool, ding_pitch = self._build_pitch_pool(scale_obj)
        if not pitch_pool:
            # Không có pitch pool thì không nên cố render
            return

        ticks_per_bar = self.ppq * 4

        # Duyệt từng Segment
        for seg in segments:
            sec_type = (getattr(seg, "section_type", "") or "").lower()
            energy = float(getattr(seg, "energy_bias", 0.6) or 0.6)
            energy = float(_clamp(energy, 0.0, 1.0))

            # Zen Arc density (0.2..2.0)
            arc_density = self._arc_density(sec_type, energy)

            # ZenArcMatrix factor (bias nhẹ, chỉ scale density, không tắt hẳn)
            zen_arc_factor = 1.0
            if self.zen_arc_matrix is not None and ZenArcMatrix is not None:
                try:
                    fn = getattr(self.zen_arc_matrix, "get_factor_for_segment", None)
                    if callable(fn):
                        zen_arc_factor = float(fn(seg))
                except Exception:
                    zen_arc_factor = 1.0
            zen_arc_factor = _clamp(zen_arc_factor, 0.5, 1.5)

            # Activity: nếu mix đã rất bận → giảm mật độ
            act_level = self._get_activity_level(seg.start_tick)
            activity_factor = 1.0
            if act_level is not None and act_level > self.activity_threshold:
                # Giảm 50% mật độ khi mix dày, nhưng không tắt hẳn
                activity_factor = 0.5

            # Breakdown: xử lý mềm lại
            if sec_type == "breakdown":
                arc_density *= 0.5
                energy *= 0.7

            # Tính số bar & số hit trong segment
            bars = seg.duration_ticks / float(ticks_per_bar) if ticks_per_bar > 0 else 1.0
            base_hits = self.hits_per_bar * bars
            raw_hits = base_hits * arc_density * activity_factor * (0.6 + 0.8 * energy)
            raw_hits *= zen_arc_factor
            hits = int(raw_hits)

            if hits <= 0:
                continue

            # Tính step theo grid để pattern có nhịp
            grid_step = max(1, seg.duration_ticks // max(1, hits))
            humanize_ticks = self._ms_to_ticks(self.humanize_ms, tempo_map)

            for i in range(hits):
                base_tick = seg.start_tick + i * grid_step

                # Humanize
                jitter = (
                    random.randint(-humanize_ticks, humanize_ticks)
                    if humanize_ticks > 0
                    else 0
                )
                start_tick = base_tick + jitter
                if start_tick < seg.start_tick:
                    start_tick = seg.start_tick
                if start_tick >= seg.end_tick:
                    continue

                # Activity tại điểm nốt
                local_act = self._get_activity_level(start_tick) or 0.0
                local_act = float(_clamp(local_act, 0.0, 1.0))

                # Chọn pitch
                is_accent = (i == 0) or (i % max(1, self.grid_division // 2) == 0)
                pitch = self._pick_pitch(
                    pitch_pool,
                    ding_pitch,
                    sec_type,
                    energy,
                    is_accent,
                )

                # Register-safe
                pitch = self._apply_register_constraints(pitch)

                # Velocity theo Arc + Accent
                vel = self._compute_velocity(energy, sec_type, is_accent)
                duration = self._compute_duration(seg, hits, i)

                # Ghi nốt qua _emit_note để SafetyFilter/Meta xử lý
                self._emit_note(
                    pitch=pitch,
                    vel=vel,
                    start_tick=start_tick,
                    duration_ticks=duration,
                    segment=seg,
                    is_accent=is_accent,
                    activity_level=local_act,
                )

                # Breath CC (timbre) – nhẹ để không phá các lớp khác
                if (
                    self.enable_breath_cc
                    and self.breath_depth > 0.0
                    and tempo_map is not None
                ):
                    self._write_breath_cc(seg, tempo_map, base_vel=vel)

            # Đăng ký hoạt động vào ActivityMap để lớp sau biết Handpan đã “chiếm chỗ”
            self._commit_activity(seg)

    # ================================================================
    # INTERNAL UTILITIES
    # ================================================================
    def _build_pitch_pool(self, scale: Scale) -> Tuple[List[int], int]:
        """
        Tạo pitch pool cho Handpan:
        - Ưu tiên pentatonic_relax / diatonic an toàn.
        - Trải trên 3 octave: low / main / high.
        - Ding = note cao nhất (hoặc chỉ định).
        """
        pcs = list(getattr(scale, "pcs", []) or [])
        if not pcs:
            try:
                pcs = list(scale.get_pitch_classes())
            except Exception:
                pcs = [0]

        if not pcs:
            return [], 60

        # Nếu profile có ding_pc thì đảm bảo nó nằm trong tập
        if self.ding_pc is not None:
            try:
                ding_pc = int(self.ding_pc) % 12
            except Exception:
                ding_pc = pcs[-1]
        else:
            ding_pc = pcs[-1]

        pool: List[int] = []

        # Low notes (nhịp / nền)
        for pc in pcs:
            pool.append(note_number(pc, self.low_oct))

        # Main octave
        for pc in pcs:
            pool.append(note_number(pc, self.main_oct))

        # High octave (chỉ một vài note sáng, gồm ding)
        for pc in pcs:
            if pc == ding_pc or random.random() < 0.4:
                pool.append(note_number(pc, self.high_oct))

        pool = sorted(set(pool))
        ding_pitch = note_number(ding_pc, self.high_oct)
        return pool, ding_pitch

    def _arc_density(self, sec_type: str, energy: float) -> float:
        """
        Factor 0.2..2.0 theo Zen Arc:
        - Grounding/Intro: ít nốt, êm.
        - Immersion: đều.
        - Peak: dày hơn (nếu mode cho phép).
        - Breakdown/Integration: thưa & nhẹ.
        """
        s = (sec_type or "").lower()

        if s in ("intro", "grounding"):
            base = 0.6
        elif s == "immersion":
            base = 1.0
        elif s in ("peak", "awakening"):
            base = 1.3
        elif s in ("outro", "integration"):
            base = 0.7
        elif s in ("bridge", "breakdown"):
            base = 0.4
        else:
            base = 0.9

        # Soft mode: không được quá dày
        mode_scale = {
            "soft": 0.7,
            "flow": 1.0,
            "spark": 1.25,
        }.get(self.mode, 1.0)

        energy = float(_clamp(energy, 0.0, 1.0))
        val = base * mode_scale * (0.7 + 0.6 * energy)
        return float(_clamp(val, 0.2, 2.0))

    def _get_activity_level(self, tick: int) -> Optional[float]:
        if self.activity_map is None:
            return None
        try:
            # Ưu tiên API có track_name
            if hasattr(self.activity_map, "get_energy_at_tick"):
                return float(self.activity_map.get_energy_at_tick("MELODY", tick))
            if hasattr(self.activity_map, "get_track_energy"):
                return float(self.activity_map.get_track_energy("MELODY", tick))
            if hasattr(self.activity_map, "get_activity_at_tick"):
                return float(self.activity_map.get_activity_at_tick("MELODY", tick))
            if hasattr(self.activity_map, "get_activity_at"):
                return float(self.activity_map.get_activity_at(tick))
        except Exception:
            return None
        return None

    def _apply_register_constraints(self, pitch: int) -> int:
        if self.register_manager is None or RegisterManager is None:
            return int(_clamp(pitch, 0, 127))
        try:
            return int(
                self.register_manager.constrain_pitch(
                    self.layer_name or "handpan",
                    int(pitch),
                )
            )
        except Exception:
            return int(_clamp(pitch, 0, 127))

    def _compute_velocity(self, energy: float, sec_type: str, is_accent: bool) -> int:
        e = float(_clamp(energy, 0.0, 1.0))
        # Base theo Arc
        if sec_type in ("intro", "grounding"):
            base = 0.7
        elif sec_type == "immersion":
            base = 1.0
        elif sec_type in ("peak", "awakening"):
            base = 1.1
        elif sec_type in ("outro", "integration"):
            base = 0.8
        elif sec_type == "breakdown":
            base = 0.6
        else:
            base = 0.9

        val = self.base_velocity * self.mix_level * base * (0.7 + 0.5 * e)
        if is_accent:
            val *= self.accent_boost

        return int(_clamp(round(val), 1, 127))

    def _compute_duration(self, seg: Segment, hits: int, idx: int) -> int:
        """
        Dur đơn giản: dựa trên spacing giữa các hit,
        giữ sustain ~60–80% khoảng cách.
        """
        if hits <= 0:
            return max(1, seg.duration_ticks)
        gap = seg.duration_ticks / float(hits)
        sustain = gap * 0.7
        # Note cuối có thể ngân dài hơn một chút
        if idx == hits - 1:
            sustain *= 1.1
        return max(1, int(sustain))

    def _pick_pitch(
        self,
        pool: List[int],
        ding_pitch: int,
        sec_type: str,
        energy: float,
        is_accent: bool,
    ) -> int:
        """
        Chọn pitch:
        - Accent → ưu tiên ding / note cao.
        - Grounding/Intro → ưu tiên mid/low.
        - Peak → được phép lên cao nhiều hơn.
        """
        if not pool:
            return 60

        s = (sec_type or "").lower()
        energy = float(_clamp(energy, 0.0, 1.0))

        # Accent → ưu tiên ding hoặc note gần ding
        if is_accent:
            candidates = [p for p in pool if p >= ding_pitch - 2]
            if candidates and random.random() < 0.8:
                return random.choice(candidates)

        # Grounding/Intro/Integration → mid/low
        if s in ("intro", "grounding", "outro", "integration"):
            mid = [p for p in pool if self.low_oct * 12 <= p <= self.high_oct * 12 + 4]
            low = [p for p in pool if p <= self.main_oct * 12 + 3]
            cand = low + mid
            if cand:
                return random.choice(cand)

        # Immersion/Peak → cân bằng, nhưng energy cao cho phép note cao hơn
        if s in ("immersion", "peak", "awakening"):
            if random.random() < 0.3 + 0.4 * energy:
                high = [p for p in pool if p >= self.main_oct * 12]
                if high:
                    return random.choice(high)

        # Fallback
        return random.choice(pool)

    # ================================================================
    # BREATH LFO (CC11)
    # ================================================================
    def _write_breath_cc(
        self,
        seg: Segment,
        tempo_map: TempoMap,
        base_vel: int,
    ) -> None:
        if self.breath_depth <= 0.0:
            return

        start = seg.start_tick
        end = seg.end_tick
        step = max(1, self.ppq // 2)

        for t in range(start, end, step):
            breath = self._breath_lfo(t, tempo_map)
            expr = int(base_vel * (0.7 + 0.3 * breath))
            expr = int(_clamp(expr, 1, 127))
            self.track.add_cc(t, 11, expr)

    def _breath_lfo(self, tick: int, tempo_map: TempoMap) -> float:
        """
        Breath LFO:
        - 0 → inhale, 1 → exhale (sin dịch pha -π/2).
        """
        try:
            bar_pos = tempo_map.get_bar_pos_at_tick(tick)
            cycle = float(getattr(tempo_map, "breath_cycle_bars", 2.0) or 2.0)
            phase = (bar_pos / cycle) * 2 * math.pi
            val = (math.sin(phase - math.pi / 2) + 1) / 2
            return float(_clamp(val, 0.0, 1.0))
        except Exception:
            return 1.0

    # ================================================================
    # EMIT NOTE (Register + SafetyFilter)
    # ================================================================
    def _emit_note(
        self,
        pitch: int,
        vel: int,
        start_tick: int,
        duration_ticks: int,
        segment: Segment,
        is_accent: bool,
        activity_level: float,
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

        # RegisterManager (nếu có)
        if self.register_manager is not None and RegisterManager is not None:
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
                    p = int(
                        self.register_manager.constrain_pitch(
                            self.layer_name, p
                        )
                    )
            except Exception:
                pass

        p = int(_clamp(p, 0, 127))
        v = int(_clamp(v, 1, 127))

        # SafetyFilter (nếu có)
        allowed = True
        if self.safety_filter is not None and SafetyFilter is not None:
            sec = (getattr(segment, "section_type", "") or "").lower()
            meta = {
                "layer": self.layer_name,
                "section_type": sec,
                "energy_bias": getattr(segment, "energy_bias", None),
                "t_norm": getattr(segment, "t_norm", None),
                "handpan_mode": self.mode,
                "is_accent": is_accent,
                "activity_level": float(_clamp(activity_level, 0.0, 1.0)),
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
                allowed = True

        if not allowed:
            return

        p = int(_clamp(p, 0, 127))
        v = int(_clamp(v, 1, 127))
        self.track.add_note(p, v, t, d)

    # ================================================================
    # ACTIVITY COMMIT
    # ================================================================
    def _commit_activity(self, seg: Segment) -> None:
        if self.activity_map is None:
            return
        try:
            if hasattr(self.activity_map, "add_activity"):
                # Handpan = weight vừa phải (không quá chiếm ưu thế)
                self.activity_map.add_activity(
                    seg.start_tick,
                    seg.duration_ticks,
                    weight=0.6,
                )
        except Exception:
            pass

    # ================================================================
    # PRIVATE
    # ================================================================
    def _ms_to_ticks(self, ms: float, tempo_map: Optional[TempoMap]) -> int:
        if tempo_map is None:
            return 0
        try:
            return int(tempo_map.ms_to_ticks(ms))
        except Exception:
            return 0

# Alias cho kiến trúc Zen Core (giữ phong cách như các engine khác)
HandpanEngine = HandpanEngineV1
