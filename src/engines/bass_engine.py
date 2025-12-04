# Tệp: src/engines/bass_engine.py
# (FINAL V11.0.2) - BASS ENGINE V1
# (CLEAN + TUNING PLAN HOOK + REGISTER SAFE + ACTIVITY AWARE + SAFETY FILTER)
#
# Upgrades vs V10:
# - Nhận TuningPlan để apply Global Register Shift (Solf Mode).
# - Dùng RegisterManager để clamp nốt Bass vào vùng an toàn (tránh sub-bass quá thấp).
# - Dùng ActivityMap để nhường nhịn khi mix quá dày.
# - Dùng SafetyFilter để lọc velocity / bỏ nốt nguy hiểm sau Register.
# - Hỗ trợ BreathSyncManager cho breath LFO (ưu tiên nếu có).
# - Hỗ trợ ZenArcMatrix để scale intensity theo Arc template.
#
# Interface:
#   eng = BassEngineV1(writer, profile, ppq, user_options, ...)
#   eng.render(segments, tempo_map, tuning_plan=plan, ...)

from __future__ import annotations
import math
import random
from typing import List, Optional, Dict, Any

from src.utils.midi_writer import MidiWriter
from src.core.structure_builder import Segment
from src.core.tempo_breath import TempoMap
from src.core.tuning_core import TuningCoreV3, TuningPlan
from src.utils.config_loader import InstrumentProfile
from src.core.music_theory import note_number
from src.utils.activity_map import ActivityMap

# Import các core type cho type hinting (optional)
try:
    from src.core.register_manager import RegisterManager
except ImportError:
    RegisterManager = Any  # type: ignore[name-defined]

try:
    from src.core.safety_filter import SafetyFilter
except ImportError:
    SafetyFilter = Any  # type: ignore[name-defined]

try:
    from src.core.breath_sync import BreathSyncManager
except ImportError:
    BreathSyncManager = Any  # type: ignore[name-defined]

try:
    from src.core.zen_arc_matrix import ZenArcMatrix
except ImportError:
    ZenArcMatrix = Any  # type: ignore[name-defined]

def _clamp(x, lo, hi):
    return max(lo, min(hi, x))

class BassEngineV1:
    """
    Bass Engine V1 (Neo Zen V11 Standard)
    - Tạo lớp nền Bass theo hợp âm.
    - 3 Modes: Om (Sustain), Zen (Smooth), Breath (Modulation).
    - Tích hợp đầy đủ TuningPlan, RegisterManager, ActivityMap, SafetyFilter, ZenArcMatrix, BreathSyncManager.
    """

    def __init__(
        self,
        writer: MidiWriter,
        profile: InstrumentProfile,
        ppq: Optional[int] = None,
        user_options: Optional[Dict[str, Any]] = None,
        # Neo Zen Hooks
        safety_filter: Optional[SafetyFilter] = None,
        register_manager: Optional[RegisterManager] = None,
        breath_sync: Optional[BreathSyncManager] = None,
        activity_map: Optional[ActivityMap] = None,
        zen_arc_matrix: Optional[ZenArcMatrix] = None,
        layer_name: str = "bass",
        channel: Optional[int] = None,
    ):
        self.writer = writer
        self.profile = profile
        # PPQ: cho phép bỏ trống -> auto lấy từ writer.ppq (DynamicTransposingWriter / MidiWriter)
        self.ppq = int(ppq if ppq is not None else getattr(writer, "ppq", 480))

        # Channel: ưu tiên override từ tham số, sau đó đến profile.channel, cuối cùng default = 9
        if channel is not None:
            try:
                self.channel = int(channel)
            except (TypeError, ValueError):
                self.channel = getattr(profile, "channel", 9) or 9
        else:
            self.channel = getattr(profile, "channel", 9) or 9

        self.track = writer.get_track(self.channel)
        self.user_options = user_options or {}

        # Hooks
        self.safety_filter = safety_filter
        self.register_manager = register_manager
        self.breath_sync = breath_sync
        self.activity_map = activity_map
        self.zen_arc_matrix = zen_arc_matrix
        self.layer_name = layer_name

        # ===== Switches =====
        self.enable_bass = bool(
            self.user_options.get(
                "enable_bass_layer",
                getattr(profile, "enable_bass_layer", True),
            )
        )
        self.bass_mode = str(
            self.user_options.get(
                "bass_mode",
                getattr(profile, "bass_mode", "om"),
            )
        ).lower()
        if self.bass_mode not in ("om", "zen", "breath"):
            self.bass_mode = "om"

        # ===== Params =====
        self.velocity = int(getattr(profile, "velocity", 85))
        self.mix_level = float(getattr(profile, "mix_level", 0.8))
        self.velocity = _clamp(self.velocity, 1, 127)
        self.mix_level = _clamp(self.mix_level, 0.0, 1.0)

        self.overlap_ticks = int(getattr(profile, "overlap_ticks", self.ppq * 0.3))
        if self.overlap_ticks < 0:
            self.overlap_ticks = 0

        # ===== Tuning =====
        self.tuning_mode = str(
            self.user_options.get(
                "tuning_mode",
                getattr(profile, "tuning_mode", "equal"),
            )
        ).lower()

        solf_from_opt = self.user_options.get("solf_hz", None)
        if solf_from_opt is None:
            solf_from_opt = getattr(profile, "solf_hz", 432.0)
        try:
            self.solf_hz = float(solf_from_opt)
        except Exception:
            self.solf_hz = 432.0

        # (Optional) root freq theo key cho TuningCore
        self.key_root_freq = getattr(profile, "key_root_freq", None)

        # ===== Breath =====
        # biên độ CC11 modulation (0–36) – hiện tại dùng nhẹ nhàng qua _write_breath_cc
        self.breath_depth = float(getattr(profile, "breath_depth", 18.0))
        self.breath_depth = _clamp(self.breath_depth, 0.0, 36.0)

        # ===== Breakdown =====
        self.breakdown_mode = str(
            getattr(profile, "breakdown_bass_mode", "soft")
        ).lower()
        if self.breakdown_mode not in ("soft", "mute", "normal"):
            self.breakdown_mode = "soft"

        # ===== Octaves =====
        self.om_oct = int(getattr(profile, "om_oct", 1))
        self.zen_oct = int(getattr(profile, "zen_oct", 2))
        self.breath_oct = int(getattr(profile, "breath_oct", 2))

        # ===== Activity Aware Config =====
        self.activity_threshold = float(
            getattr(profile, "bass_activity_threshold", 0.85)
        )

    # ================================================================
    # PUBLIC
    # ================================================================
    def render(
        self,
        segments: List[Segment],
        tempo_map: Optional[TempoMap] = None,
        *,
        tuning_plan: Optional[TuningPlan] = None,
        **kwargs,
    ) -> None:
        """
        Render Bass layer.
        - tuning_plan: Dùng để lấy register_shift_semitones (Global Register Shift).
        - tempo_map: Dùng cho Breath LFO (hoặc fallback khi không có BreathSyncManager).
        """
        if not self.enable_bass:
            return
        if not segments:
            return
        if self.track is None:
            return

        # Lấy Global Shift từ TuningPlan (nếu có)
        global_shift = 0
        if tuning_plan is not None:
            try:
                global_shift = tuning_plan.register_shift_semitones()
            except Exception:
                global_shift = 0

        for seg in segments:
            sec = (getattr(seg, "section_type", "") or "").lower()

            # 1. Breakdown Behavior
            energy = float(getattr(seg, "energy_bias", 0.6))
            if sec == "breakdown":
                if self.breakdown_mode == "mute":
                    continue
                elif self.breakdown_mode == "soft":
                    energy *= 0.35

            energy = _clamp(energy, 0.0, 1.0)

            # 2. Activity Check (Nhường nhịn nếu mix quá dày)
            if self.activity_map is not None:
                try:
                    act_level = 0.0
                    if hasattr(self.activity_map, "get_activity_at"):
                        act_level = float(
                            self.activity_map.get_activity_at(seg.start_tick)
                        )
                    elif hasattr(self.activity_map, "get_track_energy"):  # API cũ
                        act_level = float(
                            self.activity_map.get_track_energy(
                                "MELODY", seg.start_tick
                            )
                        )

                    if act_level > self.activity_threshold:
                        # Nếu quá bận, giảm energy (velocity) thay vì mute cứng
                        energy *= 0.5
                except Exception:
                    pass

            # 3. Get Root & Basic Pitch
            root_pc = self._get_root_pc(getattr(seg, "chord_name", "C"))
            octave = self._get_oct_for_mode()
            pitch_raw = note_number(root_pc, octave)

            # 4. Apply Global Shift (TuningPlan)
            pitch_shifted = pitch_raw + global_shift

            # 5. Register Constrain (RegisterManager)
            if self.register_manager is not None:
                try:
                    pitch_shifted = self.register_manager.constrain_pitch(
                        self.layer_name, pitch_shifted
                    )
                except Exception:
                    pass  # nếu lỗi thì giữ nguyên

            # 6. Micro-Tuning (MTS / Pitch Bend)
            tuned_pitch, bend = TuningCoreV3.get_tuned_pitch(
                pitch_shifted,
                tuning_mode=self.tuning_mode,
                solf_hz=self.solf_hz,
                key_root_freq=self.key_root_freq,
            )

            # Clamp final values
            tuned_pitch = int(_clamp(int(tuned_pitch), 0, 127))
            bend = int(_clamp(int(bend), -8192, 8191))

            # 7. Scale Velocity by Arc (+ ZenArcMatrix nếu có)
            arc_scale = self._zen_arc_scale(sec, energy)

            # 8. Render by Mode (SafetyFilter chạy bên trong từng mode)
            if self.bass_mode == "om":
                self._render_om_bass(seg, tuned_pitch, bend, arc_scale, tempo_map, sec, energy)
            elif self.bass_mode == "zen":
                self._render_zen_bass(seg, tuned_pitch, bend, arc_scale, sec, energy)
            else:  # "breath"
                self._render_breath_bass(seg, tuned_pitch, bend, arc_scale, tempo_map, sec, energy)

            # 9. Commit Activity (để layer sau biết Bass đã chiếm chỗ)
            if self.activity_map is not None:
                try:
                    if hasattr(self.activity_map, "commit_event"):
                        self.activity_map.commit_event(
                            layer=self.layer_name,
                            start_tick=seg.start_tick,
                            duration_ticks=seg.duration_ticks,
                            weight=0.5,
                        )
                    elif hasattr(self.activity_map, "add_activity"):
                        self.activity_map.add_activity(
                            seg.start_tick,
                            seg.duration_ticks,
                            weight=0.5,  # type: ignore[arg-type]
                        )
                except Exception:
                    pass

    # ================================================================
    # INTERNAL UTILITIES
    # ================================================================
    def _get_root_pc(self, chord_name: str) -> int:
        """
        Nhận diện root chính xác: hỗ trợ C#, Db, Eb, F#, Ab, Bb...
        """
        try:
            name = (chord_name or "").strip().upper()
            if not name:
                return 0

            # lấy root có xử lý # hoặc b
            if len(name) >= 2 and name[1] in ("#", "B"):
                root = name[:2]
            else:
                root = name[0]

            mapping = {
                "C": 0,
                "C#": 1,
                "DB": 1,
                "D": 2,
                "D#": 3,
                "EB": 3,
                "E": 4,
                "F": 5,
                "F#": 6,
                "GB": 6,
                "G": 7,
                "G#": 8,
                "AB": 8,
                "A": 9,
                "A#": 10,
                "BB": 10,
                "B": 11,
            }
            return mapping.get(root, 0)
        except Exception:
            return 0

    def _get_oct_for_mode(self) -> int:
        if self.bass_mode == "om":
            return self.om_oct
        if self.bass_mode == "zen":
            return self.zen_oct
        return self.breath_oct

    def _get_arc_intensity_factor(self, sec: str, energy: float) -> float:
        """
        Lấy thêm factor từ ZenArcMatrix (nếu có) để scale intensity bass.
        """
        if self.zen_arc_matrix is None:
            return 1.0
        try:
            if hasattr(self.zen_arc_matrix, "get_intensity_factor"):
                return float(
                    self.zen_arc_matrix.get_intensity_factor(
                        layer=self.layer_name,
                        section_type=(sec or "").lower(),
                        energy=float(_clamp(energy, 0.0, 1.0)),
                    )
                )
        except Exception:
            return 1.0
        return 1.0

    def _zen_arc_scale(self, sec: str, energy: float) -> float:
        sec = (sec or "").lower()
        e = _clamp(energy, 0.0, 1.0)

        if sec in ("grounding", "intro"):
            base = 0.6 * e
        elif sec == "immersion":
            base = 1.0 * e
        elif sec == "peak":
            base = 1.2 * e
        elif sec in ("outro", "integration"):
            base = 0.5 * e
        elif sec == "breakdown":
            # fallback nếu breakdown_mode != soft đã xử lý ở trên
            base = 0.3 * e
        else:
            base = 0.8 * e

        arc_factor = self._get_arc_intensity_factor(sec, energy)
        return float(base * arc_factor)

    # -------- SafetyFilter helpers --------
    def _build_note_meta(
        self,
        seg: Segment,
        pitch: int,
        energy: float,
        sec: str,
    ) -> Dict[str, Any]:
        """
        Meta tối thiểu cho SafetyFilter.
        """
        return {
            "layer": self.layer_name,
            "section_type": (sec or "").lower(),
            "energy_bias": float(_clamp(energy, 0.0, 1.0)),
            "start_tick": int(getattr(seg, "start_tick", 0)),
            "duration_ticks": int(getattr(seg, "duration_ticks", 0)),
            "segment_start": int(getattr(seg, "start_tick", 0)),
            "segment_end": int(getattr(seg, "end_tick", getattr(seg, "start_tick", 0))),
            "pitch": int(pitch),
            "mode": self.bass_mode,
        }

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

    # ================================================================
    # OM BASS – deep breathing sustain
    # ================================================================
    def _render_om_bass(
        self,
        seg: Segment,
        pitch: int,
        bend: int,
        scale: float,
        tempo_map: Optional[TempoMap],
        sec: str,
        energy: float,
    ) -> None:
        start = seg.start_tick
        end = seg.end_tick
        dur = end - start

        # Base velocity
        vel = int(self.velocity * scale * self.mix_level)
        vel = int(_clamp(vel, 1, 127))

        # SafetyFilter meta
        meta = self._build_note_meta(seg, pitch, energy, sec)
        vel_filtered = self._apply_safety_filter(pitch, vel, start, meta)
        if vel_filtered is None:
            return
        vel = vel_filtered

        # Pitch bend 1 lần đầu segment
        self.track.add_pitch_bend(start, bend)

        base_dur = max(1, dur + self.overlap_ticks)

        # Single sustain note (true-sustain, không spam)
        self.track.add_note(pitch, vel, start, base_dur)

        # Breath LFO on CC11
        self._write_breath_cc(seg, tempo_map, vel)

    # ================================================================
    # Zen Bass – smooth sustain
    # ================================================================
    def _render_zen_bass(
        self,
        seg: Segment,
        pitch: int,
        bend: int,
        scale: float,
        sec: str,
        energy: float,
    ) -> None:
        start = seg.start_tick
        end = seg.end_tick
        dur = end - start

        vel = int(self.velocity * scale * self.mix_level)
        vel = int(_clamp(vel, 1, 127))

        meta = self._build_note_meta(seg, pitch, energy, sec)
        vel_filtered = self._apply_safety_filter(pitch, vel, start, meta)
        if vel_filtered is None:
            return
        vel = vel_filtered

        self.track.add_pitch_bend(start, bend)
        self.track.add_note(pitch, vel, start, dur + self.overlap_ticks)

    # ================================================================
    # Breath Bass – timbre mod by breath cycle
    # ================================================================
    def _render_breath_bass(
        self,
        seg: Segment,
        pitch: int,
        bend: int,
        scale: float,
        tempo_map: Optional[TempoMap],
        sec: str,
        energy: float,
    ) -> None:
        start = seg.start_tick
        end = seg.end_tick
        dur = end - start

        base_vel = int(self.velocity * scale * self.mix_level)
        base_vel = int(_clamp(base_vel, 1, 127))

        meta = self._build_note_meta(seg, pitch, energy, sec)
        vel_filtered = self._apply_safety_filter(pitch, base_vel, start, meta)
        if vel_filtered is None:
            return
        base_vel = vel_filtered

        self.track.add_pitch_bend(start, bend)
        self.track.add_note(pitch, base_vel, start, dur + self.overlap_ticks)

        # breath shaping on CC11
        self._write_breath_cc(seg, tempo_map, base_vel)

    # ================================================================
    # BREATH LFO + CC modulation
    # ================================================================
    def _write_breath_cc(
        self,
        seg: Segment,
        tempo_map: Optional[TempoMap],
        base_vel: int,
    ) -> None:
        if tempo_map is None or self.breath_depth <= 0.0:
            return

        start = seg.start_tick
        end = seg.end_tick

        # update CC11 every half-beat
        step = max(1, self.ppq // 2)

        for t in range(start, end, step):
            breath = self._breath_lfo(t, tempo_map)
            # 0 → inhale (nhỏ hơn), 1 → exhale (lớn hơn)
            expr = int(base_vel * (0.75 + 0.25 * breath))
            expr = _clamp(expr, 1, 127)
            self.track.add_cc(t, 11, expr)

    def _breath_lfo(self, tick: int, tempo_map: TempoMap) -> float:
        """
        Breath LFO theo chu kỳ thở:
        - Ưu tiên lấy phase từ BreathSyncManager (0..1) nếu có.
        - Nếu không, fallback: phase từ vị trí bar/tick + breath_cycle_bars.
        - Trả về 0 → inhale, 1 → exhale.
        """
        # BreathSyncManager ưu tiên
        if self.breath_sync is not None:
            try:
                if hasattr(self.breath_sync, "get_phase_at_tick"):
                    phase_val = float(self.breath_sync.get_phase_at_tick(tick))
                    # Nếu là radians (lớn), chuẩn hoá 0..1
                    if phase_val > 1.5 * math.pi:
                        phase_norm = (phase_val / (2 * math.pi)) % 1.0
                    else:
                        phase_norm = float(_clamp(phase_val, 0.0, 1.0))
                    # phase_norm đã là 0..1 inhale/exhale
                    return float(_clamp(phase_norm, 0.0, 1.0))
            except Exception:
                pass

        # Fallback: TempoMap + breath_cycle_bars như bản cũ
        try:
            bar_pos = tempo_map.get_bar_pos_at_tick(tick)
            cycle = float(getattr(tempo_map, "breath_cycle_bars", 2.0) or 2.0)
            phase = (bar_pos / cycle) * 2 * math.pi

            # 0 → inhale, 1 → exhale
            sinv = (math.sin(phase - math.pi / 2) + 1) / 2
            return float(_clamp(sinv, 0.0, 1.0))
        except Exception:
            return 1.0
