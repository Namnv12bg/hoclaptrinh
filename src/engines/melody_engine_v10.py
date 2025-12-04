from __future__ import annotations

import random
import math
from typing import List, Dict, Any, Optional, TYPE_CHECKING, Tuple

from src.utils.midi_writer import MidiWriter, MidiTrack
from src.utils.activity_map import ActivityMap
from src.utils.config_loader import InstrumentProfile
from src.core.structure_builder import Segment
from src.core.tempo_breath import TempoMap
from src.core.melody_generator import MelodyGenerator, MelodyNote

if TYPE_CHECKING:
    # Chỉ dùng cho type-hint, không ép import lúc runtime
    from src.core.safety_filter import SafetyFilter
    from src.core.register_manager import RegisterManager
    from src.core.breath_sync import BreathSyncManager
    from src.core.zen_arc_matrix import ZenArcMatrix


def _clamp(n: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, n))


class MelodyEngineV10:
    """
    Melody Engine cho Neo Zen V10.

    Khởi tạo (Zen Core):
        eng = MelodyEngineV10(
            writer: MidiWriter,
            profile: InstrumentProfile,
            ppq: int,
            user_options: Dict[str, Any],
            *,
            safety_filter: Optional[SafetyFilter] = None,
            register_manager: Optional[RegisterManager] = None,
            breath_sync: Optional[BreathSyncManager] = None,
            activity_map: Optional[ActivityMap] = None,
            zen_arc_matrix: Optional[ZenArcMatrix] = None,
            layer_name: str = "melody",
        )

    Render (Zen Core):
        eng.render(
            segments: List[Segment],
            key: str,
            scale: str,
            tempo_map: TempoMap,
            activity_map: Optional[ActivityMap] = None,
        )
    """

    def __init__(
        self,
        writer: MidiWriter,
        profile: InstrumentProfile,
        ppq: int,
        user_options: Optional[Dict[str, Any]] = None,
        *,
        # Neo Zen cores (tuỳ chọn) – khớp Zen Core
        safety_filter: Optional["SafetyFilter"] = None,
        register_manager: Optional["RegisterManager"] = None,
        breath_sync: Optional["BreathSyncManager"] = None,
        activity_map: Optional[ActivityMap] = None,
        zen_arc_matrix: Optional["ZenArcMatrix"] = None,
        layer_name: str = "melody",
    ):
        self.writer: MidiWriter = writer
        self.ppq: int = int(ppq or getattr(writer, "ppq", 480))
        self.profile: InstrumentProfile = profile
        self.options: Dict[str, Any] = user_options or {}

        # Track melody
        channel = getattr(profile, "channel", 3) or 3
        name = getattr(profile, "name", "Melody")
        self.track: MidiTrack = writer.get_track(channel)
        self.track.set_name(f"{channel}. VOICE ({name})")

        program = getattr(profile, "program", 73) or 73  # default flute
        self.track.set_program(program)

        # Key / Scale từ user_options (có thể override ở render)
        self.key: str = str(self.options.get("key", "C")).upper()
        self.scale_type: str = str(self.options.get("scale", "major")).lower()
        self.scale_family: str = getattr(profile, "scale_family", "diatonic")

        # Rhythm / Play mode
        #   profile.rhythm_mode: "flow" / "rubato" / "kintsugi" / "mantra" / "sparks"
        self.play_mode: str = getattr(profile, "rhythm_mode", "rubato")
        if self.play_mode == "grid":
            self.play_mode = "flow"
        self.articulation: str = getattr(profile, "articulation", "sustained")

        # Intensity
        self.master_intensity: float = _clamp(
            float(
                self.options.get(
                    "melody_master_intensity",
                    getattr(profile, "melody_master_intensity", 0.6),
                )
            ),
            0.0,
            1.0,
        )

        # Register & phrasing (ổn định hoá register về [low, high])
        raw_reg = getattr(profile, "register", [60, 84]) or [60, 84]
        if isinstance(raw_reg, (list, tuple)) and len(raw_reg) > 0:
            vals = [int(v) for v in raw_reg]
            low = min(vals)
            high = max(vals)
        else:
            low, high = 60, 84
        self.register: List[int] = [low, high]

        self.legato: float = float(getattr(profile, "legato", 0.95))
        self.legato = _clamp(self.legato, 0.1, 1.2)

        # Rest bias
        self.phrase_rest_prob: float = _clamp(
            float(getattr(profile, "phrase_rest_prob", 0.4)), 0.0, 1.0
        )

        # Humanize / ghosts
        self.jitter_range: int = max(0, int(getattr(profile, "humanize_ms", 15)))
        self.enable_ghosts: bool = bool(getattr(profile, "enable_ghosts", False))
        self.base_ghost_prob: float = _clamp(
            float(getattr(profile, "ghost_prob", 0.3)), 0.0, 1.0
        )

        # Soul configs
        self.scale_mode: str = getattr(profile, "scale_mode", "diatonic")
        self.breath_phrasing: bool = bool(getattr(profile, "breath_phrasing", False))

        # Zen-aware melody params
        self.melody_breath_amount: float = _clamp(
            float(getattr(profile, "melody_breath_amount", 1.0)), 0.0, 1.0
        )
        self.arc_rest_bias: float = _clamp(
            float(getattr(profile, "melody_arc_rest_bias", 1.0)), 0.5, 1.5
        )
        self.breakdown_mode: str = str(
            getattr(profile, "melody_breakdown_mode", "soft")
        ).lower()
        if self.breakdown_mode not in ("soft", "mute", "normal"):
            self.breakdown_mode = "soft"

        # Flute ornament mode
        self.flute_ornament_mode: bool = bool(
            getattr(profile, "flute_ornament_mode", False)
        )
        self.ornament_grace_prob: float = _clamp(
            float(getattr(profile, "ornament_grace_prob", 0.35)), 0.0, 1.0
        )
        self.ornament_octave_jump_prob: float = _clamp(
            float(getattr(profile, "ornament_octave_jump_prob", 0.18)), 0.0, 1.0
        )

        # Breath state (cho CC11 arc)
        self._last_breath_phase: float = 0.5

        # Neo Zen cores (hook)
        self.safety_filter: Optional["SafetyFilter"] = safety_filter
        self.register_manager: Optional["RegisterManager"] = register_manager
        self.breath_sync: Optional["BreathSyncManager"] = breath_sync
        self.activity_map: Optional[ActivityMap] = activity_map
        self.zen_arc_matrix: Optional["ZenArcMatrix"] = zen_arc_matrix
        self.layer_name: str = layer_name or "melody"

        # Debug flag
        self.debug: bool = bool(self.options.get("debug_melody", False))

        # Brain (MelodyGenerator)
        brain_options = self._build_brain_options()
        self.generator = MelodyGenerator(ppq=self.ppq, user_options=brain_options)

    # =========================================================
    # INTERNAL CONFIG FOR BRAIN
    # =========================================================
    def _build_brain_options(self) -> Dict[str, Any]:
        """
        Chuyển một phần cấu hình từ profile/options sang MelodyGenerator.
        Mục tiêu: Brain và Engine nhìn cùng "tính cách" melody.
        """
        o: Dict[str, Any] = {}

        # Base velocity lấy từ profile.velocity nếu có
        base_vel = getattr(self.profile, "velocity", 70)
        o["melody_base_velocity"] = int(
            self.options.get("melody_base_velocity", base_vel)
        )

        # Register
        o["melody_register_low"] = self.register[0]
        o["melody_register_high"] = self.register[1]
        o["melody_min_pitch"] = self.register[0]
        o["melody_max_pitch"] = self.register[1]

        # Intensity / rest / arc / breakdown
        o["melody_master_intensity"] = self.master_intensity
        o["melody_phrase_rest_prob"] = self.phrase_rest_prob
        o["melody_arc_rest_bias"] = self.arc_rest_bias
        o["melody_breakdown_mode"] = self.breakdown_mode

        # Scale mode (diatonic / pentatonic_relax)
        o["melody_scale_mode"] = self.scale_mode

        # Play mode
        o["melody_play_mode"] = self.play_mode

        # Flute ornament (Brain-level: octave jump nhẹ)
        o["flute_ornament_mode"] = self.flute_ornament_mode
        o["ornament_octave_jump_prob"] = self.ornament_octave_jump_prob

        # Humanize velocity
        o["humanize_velocity"] = int(self.options.get("humanize_velocity", 5))

        return o

    # =========================================================
    # HELPERS: SEGMENT / ACTIVITY / ARC / META
    # =========================================================
    @staticmethod
    def _build_segment_index(segments: List[Segment]) -> List[Segment]:
        """
        Đảm bảo segments được sort theo start_tick để tìm nhanh segment cho mỗi note.
        """
        return sorted(segments, key=lambda s: getattr(s, "start_tick", 0))

    def _find_segment_for_tick(
        self, segs_sorted: List[Segment], tick: int, start_idx: int
    ) -> Tuple[Optional[Segment], int]:
        """
        Tìm Segment chứa tick (nếu có), dùng pointer để không O(N*M).
        """
        if not segs_sorted:
            return None, start_idx

        idx = max(0, min(start_idx, len(segs_sorted) - 1))
        while idx < len(segs_sorted) and tick >= segs_sorted[idx].end_tick:
            idx += 1

        if idx < len(segs_sorted):
            seg = segs_sorted[idx]
            if seg.start_tick <= tick < seg.end_tick:
                return seg, idx

        return None, idx

    def _get_activity_factor(
        self, start_tick: int, duration_ticks: int
    ) -> Optional[float]:
        """
        Lấy mức Activity 0..1 cho layer melody tại vùng [start_tick, end_tick].
        Nếu không có ActivityMap / API khác → None.
        """
        if self.activity_map is None:
            return None
        end_tick = start_tick + max(1, duration_ticks)
        try:
            if hasattr(self.activity_map, "get_activity_for_layer"):
                return float(
                    self.activity_map.get_activity_for_layer(
                        self.layer_name, start_tick, end_tick
                    )
                )
            if hasattr(self.activity_map, "get_activity"):
                return float(
                    self.activity_map.get_activity(
                        start_tick, end_tick, layer=self.layer_name
                    )
                )
        except Exception:
            return None
        return None

    def _get_arc_intensity_factor(
        self, section_type: str, energy: float
    ) -> float:
        """
        Nếu ZenArcMatrix có cung cấp intensity_factor cho layer melody,
        dùng để scale velocity (ví dụ template 'melody_low' → Peak bớt dày).
        """
        if self.zen_arc_matrix is None:
            return 1.0
        try:
            if hasattr(self.zen_arc_matrix, "get_intensity_factor"):
                return float(
                    self.zen_arc_matrix.get_intensity_factor(
                        layer=self.layer_name,
                        section_type=(section_type or "").lower(),
                        energy=float(energy),
                    )
                )
        except Exception:
            return 1.0
        return 1.0

    def _build_note_meta(
        self,
        note: int,
        start_tick: int,
        duration_ticks: int,
        kind: str,
        segment: Optional[Segment],
        activity: Optional[float],
    ) -> Dict[str, Any]:
        """
        Meta gửi cho SafetyFilter (và các core khác nếu cần).
        """
        section_type = ""
        energy = 0.5
        if segment is not None:
            section_type = getattr(segment, "section_type", "") or ""
            energy = float(getattr(segment, "energy_bias", 0.5) or 0.5)

        meta: Dict[str, Any] = {
            "layer": self.layer_name,
            "kind": kind,
            "section_type": section_type,
            "energy_bias": energy,
            "start_tick": int(start_tick),
            "duration_ticks": int(duration_ticks),
            "segment_start": int(getattr(segment, "start_tick", start_tick))
            if segment is not None
            else int(start_tick),
            "segment_end": int(getattr(segment, "end_tick", start_tick + duration_ticks))
            if segment is not None
            else int(start_tick + duration_ticks),
            "pitch": int(note),
        }

        if activity is not None:
            meta["activity"] = float(activity)

        # Breath info (nếu BreathSyncManager hỗ trợ)
        if self.breath_sync is not None:
            try:
                if hasattr(self.breath_sync, "get_breath_info_at_tick"):
                    meta["breath_info"] = self.breath_sync.get_breath_info_at_tick(
                        start_tick
                    )
            except Exception:
                pass

        return meta

    def _apply_register(self, pitch: int) -> int:
        """
        Dùng RegisterManager (nếu có) để clamp pitch vào vùng an toàn của layer melody.
        Nếu không có → clamp nhẹ theo profile.register (0..127).
        """
        p = int(pitch)

        if self.register_manager is not None:
            try:
                if hasattr(self.register_manager, "constrain_pitch"):
                    return int(
                        self.register_manager.constrain_pitch(self.layer_name, p)
                    )
            except Exception:
                pass

        # Fallback: clamp theo register [low, high]
        low, high = sorted([int(self.register[0]), int(self.register[-1])])
        return int(_clamp(p, low, high))

    def _apply_safety_filter(
        self,
        pitch: int,
        velocity: int,
        tick: int,
        meta: Dict[str, Any],
    ) -> Optional[int]:
        """
        Gọi SafetyFilter.adjust(layer, pitch, velocity, tick, meta) nếu có.
        Trả về velocity mới, hoặc None nếu bỏ nốt.
        """
        vel = int(velocity)
        if self.safety_filter is None:
            return vel
        try:
            if hasattr(self.safety_filter, "adjust"):
                new_vel = self.safety_filter.adjust(
                    layer=self.layer_name,
                    pitch=int(pitch),
                    velocity=vel,
                    tick=int(tick),
                    meta=meta,
                )
                if new_vel is None:
                    # Giữ nguyên vel, coi như filter không muốn can thiệp
                    return vel
                new_vel = int(new_vel)
                if new_vel <= 0:
                    return None
                return max(1, min(127, new_vel))
        except Exception:
            return vel
        return vel

    def _get_breath_phase_for_tick(
        self, tick: int, tempo_map: Optional[TempoMap]
    ) -> float:
        """
        Lấy breath_phase 0..1 tại tick:
        - Ưu tiên BreathSyncManager nếu có.
        - Fallback TempoMap.get_phase_at_bar.
        - Nếu không, dùng _last_breath_phase.
        """
        # BreathSync
        if self.breath_sync is not None:
            try:
                if hasattr(self.breath_sync, "get_phase_at_tick"):
                    phase_val = float(self.breath_sync.get_phase_at_tick(tick))
                    # Nếu đã là 0..1 thì clamp; nếu là radians thì normalize
                    if phase_val > 1.5 * math.pi:
                        return (phase_val / (2 * math.pi)) % 1.0
                    return float(_clamp(phase_val, 0.0, 1.0))
            except Exception:
                pass

        # TempoMap
        if tempo_map is not None:
            try:
                bar_pos = tempo_map.get_bar_pos_at_tick(tick)
                phase_rad = tempo_map.get_phase_at_bar(bar_pos)
                return (phase_rad / (2 * math.pi)) % 1.0
            except Exception:
                pass

        return float(_clamp(self._last_breath_phase, 0.0, 1.0))

    # =========================================================
    # PUBLIC
    # =========================================================
    def render(
        self,
        segments: List[Segment],
        key: str,
        scale: str,
        tempo_map: Optional[TempoMap],
        activity_map: Optional[ActivityMap] = None,
    ) -> None:
        """
        Render melody cho toàn bộ list Segment.

        - key / scale: từ Zen Core; nếu None → dùng self.key / self.scale_type.
        - activity_map:
            + Nếu truyền vào: override ActivityMap cho lần render này.
            + Nếu None: dùng self.activity_map đã cấu hình trong __init__.
        """
        if not segments:
            return

        # Cập nhật key / scale nếu được truyền từ Zen Core
        if key:
            self.key = str(key).upper()
        if scale:
            self.scale_type = str(scale).lower()

        # Activity Map cho lần render này
        if activity_map is not None:
            self.activity_map = activity_map

        if self.debug:
            print(
                f"[MelodyV10] Render mode={self.play_mode}, "
                f"key={self.key}, scale={self.scale_type}, "
                f"scale_mode={self.scale_mode}, intensity={self.master_intensity:.2f}"
            )

        # ===== 1. Gọi Brain để lấy list MelodyNote \"thô\" =====
        notes: List[MelodyNote] = self.generator.generate_full_melody(
            segments, self.key, self.scale_type
        )
        if not notes:
            return

        # Chuẩn bị index segment để gắn meta/Arc
        segs_sorted = self._build_segment_index(segments)
        seg_idx = 0

        # ===== 2. Performance layer: biến MelodyNote thành MIDI =====
        for n in notes:
            note = int(n.pitch)
            t_on = int(n.start_tick)
            dur = max(1, int(n.duration_ticks))

            # Tìm segment chứa note (nếu có)
            current_seg, seg_idx = self._find_segment_for_tick(
                segs_sorted, t_on, seg_idx
            )
            section_type = ""
            energy_bias = 0.5
            if current_seg is not None:
                section_type = getattr(current_seg, "section_type", "") or ""
                energy_bias = float(
                    getattr(current_seg, "energy_bias", 0.5) or 0.5
                )

            # Activity ở vùng note này
            activity = self._get_activity_factor(t_on, dur)

            # Ưu tiên bỏ ghost/ornament khi Activity cao
            if activity is not None and float(activity) > 0.75:
                if str(getattr(n, "kind", "main")) in ("ghost", "ornament"):
                    # Skip hẳn nốt ghost/ornament này để mở chỗ cho lớp khác
                    continue

            # breath_phase (0..1) tại t_on
            breath_phase = self._get_breath_phase_for_tick(t_on, tempo_map)
            self._last_breath_phase = breath_phase

            # Flute octave jump nhẹ ở Engine-level (bổ sung thêm "spark")
            note = self._maybe_apply_octave_jump(note)

            # Apply RegisterManager / register clamp
            note = self._apply_register(note)

            # Velocity: lấy từ Brain → scale theo intensity + breath + Arc + Activity
            vel = int(n.velocity or getattr(self.profile, "velocity", 70))
            vel = int(vel * (0.5 + 0.5 * self.master_intensity))

            # Breath shaping
            if self.breath_phrasing and self.melody_breath_amount > 0.0:
                if breath_phase >= 0.5:
                    breath_gain = 1.0 + 0.25 * self.melody_breath_amount
                else:
                    breath_gain = 1.0 - 0.15 * self.melody_breath_amount
                vel = int(vel * breath_gain)

            # Arc / template (ZenArcMatrix) – scale intensity theo Arc
            arc_factor = self._get_arc_intensity_factor(section_type, energy_bias)
            vel = int(vel * arc_factor)

            # Activity → giảm thêm chút vel nếu rất cao (nhưng không tắt melody)
            if activity is not None:
                a = float(_clamp(float(activity), 0.0, 1.0))
                # activity=0 → 1.0 ;  activity=1 → ~0.75
                vel_scale_act = 1.0 - 0.25 * a
                vel = int(vel * vel_scale_act)

            vel = int(_clamp(vel, 1, 127))

            # Ghost note: scale nhẹ như cũ (sau Arc/Activity)
            if n.kind == "ghost":
                vel = int(vel * 0.6)

            # Meta cho SafetyFilter
            meta = self._build_note_meta(
                note=note,
                start_tick=t_on,
                duration_ticks=dur,
                kind=str(getattr(n, "kind", "main")),
                segment=current_seg,
                activity=activity,
            )

            # SafetyFilter: áp dụng cho mọi loại note (main/ghost/ornament)
            vel_filtered = self._apply_safety_filter(
                pitch=note, velocity=vel, tick=t_on, meta=meta
            )
            if vel_filtered is None:
                # Filter yêu cầu bỏ nốt
                continue
            vel = vel_filtered

            # Flute grace-note ở Engine-level (ornament) – cũng qua Register + SafetyFilter
            if n.kind == "main" and self.flute_ornament_mode:
                self._maybe_add_flute_ornament(
                    main_note=note,
                    t_on=t_on,
                    dur=dur,
                    base_vel=vel,
                    segment=current_seg,
                    activity=activity,
                )

            # Ghi note chính
            self.track.add_note(note, vel, t_on, dur)

            # ActivityMap V2: dùng commit_event, fallback add_activity nếu còn V1
            if self.activity_map is not None:
                try:
                    # API mới
                    self.activity_map.commit_event(
                        layer=self.layer_name,
                        start_tick=t_on,
                        duration_ticks=dur,
                        weight=1.0,
                    )
                except AttributeError:
                    # Tương thích ActivityMap V1 (nếu còn)
                    try:
                        self.activity_map.add_activity(  # type: ignore[attr-defined]
                            t_on, dur
                        )
                    except AttributeError:
                        pass

            # CC11 arc cho main sustained
            if self.articulation == "sustained" and n.kind == "main":
                self._write_cc11_arc(t_on, dur, current_seg, tempo_map)

    # =========================================================
    # ORNAMENTS (FLUTE MODE)
    # =========================================================
    def _maybe_add_flute_ornament(
        self,
        main_note: int,
        t_on: int,
        dur: int,
        base_vel: int,
        segment: Optional[Segment],
        activity: Optional[float],
    ) -> None:
        """
        Thêm 1 grace note ngắn trước nốt chính (giống láy sáo).
        Grace-note cũng đi qua RegisterManager + SafetyFilter.
        """
        if not self.flute_ornament_mode:
            return

        if random.random() > self.ornament_grace_prob:
            return

        grace_dur = max(1, int(self.ppq * 0.25))
        grace_on = max(0, t_on - grace_dur)

        interval_choices = [-2, -1, 1, 2, 3]
        interval = random.choice(interval_choices)
        grace_note = main_note + interval

        # Register-safe
        grace_note = self._apply_register(grace_note)

        reg_low, reg_high = sorted([int(self.register[0]), int(self.register[-1])])
        grace_note = int(_clamp(grace_note, reg_low, reg_high))

        vel = int(base_vel * 0.8)
        vel = int(_clamp(vel, 1, 127))

        # Meta cho SafetyFilter (kind="ornament")
        meta = self._build_note_meta(
            note=grace_note,
            start_tick=grace_on,
            duration_ticks=grace_dur,
            kind="ornament",
            segment=segment,
            activity=activity,
        )
        vel_filtered = self._apply_safety_filter(
            pitch=grace_note, velocity=vel, tick=grace_on, meta=meta
        )
        if vel_filtered is None:
            return
        vel = vel_filtered

        self.track.add_note(grace_note, vel, grace_on, grace_dur)

    def _maybe_apply_octave_jump(self, note: int) -> int:
        """
        Thỉnh thoảng nhảy quãng 8 nhẹ, tạo cảm giác 'hú' của sáo/shakuhachi'.
        (Layer bổ sung cho Brain; vẫn clamp theo register.)
        """
        if not self.flute_ornament_mode:
            return note

        if random.random() > self.ornament_octave_jump_prob:
            return note

        direction = random.choice([-12, 12])
        new_note = note + direction

        reg_low, reg_high = sorted([int(self.register[0]), int(self.register[-1])])
        if reg_low <= new_note <= reg_high:
            return new_note
        return note

    # =========================================================
    # OUTPUT / CC
    # =========================================================
    def _write_cc11_arc(
        self,
        start: int,
        dur: int,
        segment: Optional[Segment],
        tempo_map: Optional[TempoMap],
    ) -> None:
        """
        Tạo 1 đường CC11 (Expression):
        - Lên → giữ → xuống.
        - Scale theo master_intensity + breath phase + Arc Matrix (nếu có).
        """
        steps = 4
        step_len = max(1, dur // steps)

        # Arc factor (nếu có ZenArcMatrix)
        section_type = ""
        energy_bias = 0.5
        if segment is not None:
            section_type = getattr(segment, "section_type", "") or ""
            energy_bias = float(
                getattr(segment, "energy_bias", 0.5) or 0.5
            )
        arc_factor = self._get_arc_intensity_factor(section_type, energy_bias)

        for i in range(steps):
            if i == 0:
                val = 60
            elif i == 1:
                val = 90
            elif i == 2:
                val = 80
            else:
                val = 50

            # Breath phase tại tick cụ thể
            tick_i = start + i * step_len
            phase = self._get_breath_phase_for_tick(tick_i, tempo_map=tempo_map)
            breath_factor = 1.0
            if self.breath_phrasing and self.melody_breath_amount > 0.0:
                if phase >= 0.5:
                    breath_factor = 1.0 + 0.2 * self.melody_breath_amount
                else:
                    breath_factor = 1.0 - 0.1 * self.melody_breath_amount

            val = int(val * (0.7 + 0.3 * self.master_intensity))
            val = int(val * breath_factor * arc_factor)
            self.track.add_cc(tick_i, 11, min(127, max(0, val)))


# Alias thống nhất cho Zen Core
MelodyEngine = MelodyEngineV10

