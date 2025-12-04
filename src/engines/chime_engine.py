# Tệp: src/engines/chime_engine.py
# (FINAL V11.0.0) - ZEN CHIME ENGINE V1 (PATCHED FOR ZEN CORE PHASE 3)
#
# Features:
# - Zen Arc aware (density, presence, vel bias)
# - Breath-aware (BreathSyncManager override > LFO fallback)
# - Activity-aware (hard skip + soft reduction)
# - SafetyFilter + RegisterManager fully integrated
# - Backward compatible với V9/V10
#
# Alias:
#   ChimeEngine   = ChimeEngineV1
#   ChimeEngineV3 = ChimeEngineV1

from __future__ import annotations

import random
import math
from typing import List, Optional, Dict, Any

from src.utils.midi_writer import MidiWriter
from src.core.music_theory import Scale, Chord, note_number
from src.utils.activity_map import ActivityMap
from src.utils.config_loader import InstrumentProfile
from src.core.structure_builder import Segment
from src.core.tempo_breath import TempoMap

def _clamp(n: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, n))

class ChimeEngineV1:
    def __init__(
        self,
        writer: MidiWriter,
        profile: InstrumentProfile,
        channel: int = 11,
        density: float = 0.5,
        activity_map: Optional[ActivityMap] = None,
        user_options: Optional[Dict[str, Any]] = None,
        scale_family: str = "diatonic",
        *,
        safety_filter: Any = None,
        register_manager: Any = None,
        breath_sync: Any = None,
        zen_arc_matrix: Any = None,
        layer_name: str = "chime",
    ):

        self.writer = writer
        self.track = writer.get_track(channel) if writer is not None else None
        self.profile = profile
        self.channel = channel
        self.ppq = int(getattr(writer, "ppq", 480))

        self.scale_family = scale_family or "diatonic"
        self.user_options: Dict[str, Any] = user_options or {}

        self._default_activity_map: Optional[ActivityMap] = activity_map

        # Zen Core buses
        self.layer_name: str = layer_name or "chime"
        self.safety_filter = safety_filter
        self.register_manager = register_manager
        self.breath_sync = breath_sync
        self.zen_arc_matrix = zen_arc_matrix

        # ===== Master switches =====
        self.enable_chime_layer: bool = bool(
            self.user_options.get(
                "enable_chime_layer",
                getattr(profile, "enable_chime_layer", True),
            )
        )

        # Breakdown behavior
        self.chime_breakdown_mode: str = str(
            self.user_options.get(
                "chime_breakdown_mode",
                getattr(profile, "chime_breakdown_mode", "mute"),
            )
        ).lower()
        if self.chime_breakdown_mode not in ("mute", "soft", "normal"):
            self.chime_breakdown_mode = "mute"

        # Base density
        base_density = self.user_options.get(
            "chime_density",
            getattr(profile, "chime_density", density),
        )
        try:
            self.base_density: float = float(base_density)
        except Exception:
            self.base_density = float(density)
        self.base_density = _clamp(self.base_density, 0.0, 1.0)

        self.chime_mode: str = str(
            self.user_options.get("chime_mode", getattr(profile, "chime_mode", "breathing"))
        ).lower()

        self.master_intensity: float = float(
            self.user_options.get(
                "master_intensity",
                getattr(profile, "master_intensity", 0.5),
            )
        )
        self.master_intensity = _clamp(self.master_intensity, 0.0, 1.0)

        self.chime_breath_amount: float = float(
            getattr(profile, "chime_breath_amount", 0.9)
        )
        self.chime_breath_amount = _clamp(self.chime_breath_amount, 0.0, 1.0)

        self.min_spacing_beats: float = float(
            getattr(profile, "chime_min_spacing_beats", 2.0)
        )
        self.min_spacing_beats = max(0.0, self.min_spacing_beats)

        self.base_velocity: int = int(getattr(profile, "velocity", 80))
        self.vel_jitter: int = int(getattr(profile, "vel_jitter", 8))

        self.pan_jitter: int = int(getattr(profile, "chime_pan_jitter", 10))
        if self.pan_jitter < 0:
            self.pan_jitter = 0

        self.activity_threshold: float = float(
            getattr(profile, "chime_activity_threshold", 0.8)
        )
        self.activity_threshold = _clamp(self.activity_threshold, 0.0, 1.0)

        self.octave_range: List[int] = list(
            getattr(profile, "chime_octave_range", [5, 6])
        ) or [5, 6]

        self.max_notes_per_segment: int = int(
            getattr(profile, "chime_max_per_segment", 128)
        )

        if self.base_density < 0.15 and self.min_spacing_beats < 4.0:
            self.min_spacing_beats = 4.0 + (0.15 - self.base_density) * 8.0

    # ---------------------------------------------------------
    # PUBLIC RENDER
    # ---------------------------------------------------------
    def render(
        self,
        segments: List[Segment],
        key: str,
        scale_type: str,
        tempo_map: Optional[TempoMap] = None,
        activity_map: Optional[ActivityMap] = None,
    ) -> None:

        if not segments or not self.enable_chime_layer or self.track is None:
            return

        scale = Scale(key, scale_type, family=self.scale_family)
        last_chime_tick = -10_000_000

        act_map: Optional[ActivityMap] = activity_map or self._default_activity_map

        for seg in segments:
            section = (getattr(seg, "section", "") or "").lower()
            sec_type = (getattr(seg, "section_type", "") or section).lower()
            is_breakdown = sec_type == "breakdown"

            try:
                chord = Chord(seg.chord_name, key, scale_type)
            except Exception:
                chord = Chord(key, key, scale_type)

            if not chord or not getattr(chord, "pcs", None):
                continue

            energy = float(getattr(seg, "energy_bias", 0.5))
            energy = _clamp(energy, 0.0, 1.0)

            # Breakdown behavior
            if is_breakdown:
                if self.chime_breakdown_mode == "mute":
                    continue
                elif self.chime_breakdown_mode == "soft":
                    energy *= 0.35

            # Base density
            local_density = self._compute_segment_density(sec_type, energy)

            # ----- ZEN ARC MATRIX Φ OVERRIDE -----
            if self.zen_arc_matrix is not None:
                try:
                    arc_cfg = self.zen_arc_matrix.query(
                        self.layer_name,
                        sec_type,
                        getattr(seg, "t_norm", 0.0),
                        energy,
                    )
                    if "presence" in arc_cfg:
                        local_density *= float(arc_cfg["presence"])
                    if "density_factor" in arc_cfg:
                        local_density *= float(arc_cfg["density_factor"])
                    local_density = _clamp(local_density, 0.0, 1.0)
                except Exception:
                    pass

            if local_density <= 0.0:
                continue

            min_spacing_ticks = int(self.min_spacing_beats * self.ppq)
            if min_spacing_ticks <= 0:
                min_spacing_ticks = self.ppq

            pitch_pool = self._build_pitch_pool(scale, chord)
            if not pitch_pool:
                continue

            grid_div = 1.0 if energy < 0.7 else 0.5
            step_ticks = int(self.ppq * grid_div)
            if step_ticks <= 0:
                step_ticks = self.ppq

            notes_this_segment = 0
            t = seg.start_tick
            end_tick = seg.end_tick

            loop_guard = 0
            max_loops = max(
                100000,
                int((end_tick - seg.start_tick) / max(1, step_ticks)) + 10,
            )

            while (
                t < end_tick
                and loop_guard < max_loops
                and notes_this_segment < self.max_notes_per_segment
            ):
                loop_guard += 1

                # ----- HARD SKIP IF ACTIVITY TOO HIGH -----
                if act_map is not None:
                    act_val = self._get_activity_level(act_map, t)
                    if act_val >= self.activity_threshold:
                        t += step_ticks
                        continue

                if t - last_chime_tick < min_spacing_ticks:
                    t += step_ticks
                    continue

                # ----------------------------
                # PROBABILITY CALCULATION
                # ----------------------------
                probability = local_density

                # ----- SOFT REDUCTION NEAR ACTIVITY LOAD -----
                if act_map is not None:
                    act_val = self._get_activity_level(act_map, t)
                    if act_val >= self.activity_threshold * 0.8:
                        probability *= 0.65

                # ----- BREATHSYNC MANAGER OVERRIDE -----
                if self.chime_mode == "breathing":
                    if self.breath_sync is not None:
                        try:
                            phase = float(self.breath_sync.get_phase(t))  # 0..1
                            breath_factor = 0.6 + 0.8 * phase
                        except Exception:
                            breath_factor = 1.0
                    else:
                        breath_factor = self._breath_phase_factor(tempo_map, t)

                    probability *= (
                        1.0 + (breath_factor - 1.0) * self.chime_breath_amount
                    )

                probability = _clamp(probability, 0.0, 1.0)

                if random.random() < probability:
                    pitch = random.choice(pitch_pool)
                    vel = self._compute_velocity(energy)

                    dur = int(self.ppq * random.uniform(0.75, 1.5))
                    dur = max(1, dur)

                    self._apply_pan_jitter(t)

                    # ==================================================
                    # SAFETY FILTER + REGISTER MANAGER (FULL PATCH)
                    # ==================================================
                    meta = {
                        "section_type": sec_type,
                        "energy_bias": energy,
                        "t_norm": getattr(seg, "t_norm", 0.0),
                        "movement_hint": getattr(seg, "movement_hint", None),
                        "layer": self.layer_name,
                    }

                    # 1. Safety Filter
                    if self.safety_filter is not None:
                        try:
                            safe_pitch, safe_vel, allow, info = self.safety_filter.apply_note(
                                self.layer_name, pitch, vel, t, meta=meta
                            )
                            if not allow:
                                t += step_ticks
                                continue
                            pitch, vel = safe_pitch, safe_vel
                        except Exception:
                            pass

                    # 2. Register Manager
                    if self.register_manager is not None:
                        try:
                            pitch = self.register_manager.clamp_pitch(
                                self.layer_name, pitch, tick=t
                            )
                        except Exception:
                            pass

                    # 3. Write note
                    self.track.add_note(pitch, vel, t, dur)

                    # 4. Log activity
                    if act_map is not None:
                        try:
                            act_map.add_activity(t, dur)
                        except TypeError:
                            try:
                                act_map.add_activity(t, dur, weight=0.8)
                            except Exception:
                                pass
                        except Exception:
                            pass

                    last_chime_tick = t
                    notes_this_segment += 1

                t += step_ticks

    # ---------------------------------------------------------
    # HELPERS
    # ---------------------------------------------------------
    def _compute_segment_density(self, section: str, energy: float) -> float:
        sec = (section or "").lower()

        if sec in ("intro", "grounding"):
            arc_factor = 0.15
        elif sec in ("immersion",):
            arc_factor = 0.5
        elif sec in ("awakening", "peak"):
            arc_factor = 1.0
        elif sec in ("integration", "outro"):
            arc_factor = 0.25
        elif sec in ("breakdown", "silence"):
            arc_factor = 0.1
        else:
            arc_factor = 0.4

        energy_factor = 0.7 + 0.6 * _clamp(energy, 0.0, 1.0)
        intensity_factor = 0.5 + 0.8 * _clamp(self.master_intensity, 0.0, 1.0)

        density = self.base_density * arc_factor * energy_factor * intensity_factor
        return float(_clamp(density, 0.0, 1.0))

    def _build_pitch_pool(self, scale: Scale, chord: Chord) -> List[int]:
        pcs: List[int] = []

        if chord and getattr(chord, "pcs", None):
            root = chord.root_pc
            candidates = [
                root,
                (root + 4) % 12,
                (root + 7) % 12,
                (root + 2) % 12,
            ]
            for pc in candidates:
                try:
                    if hasattr(scale, "contains_pc") and scale.contains_pc(pc):
                        pcs.append(pc)
                    elif pc in getattr(scale, "pcs", []):
                        pcs.append(pc)
                except Exception:
                    if pc in getattr(scale, "pcs", []):
                        pcs.append(pc)

            if not pcs:
                pcs = list(getattr(chord, "pcs", []) or [])
        else:
            try:
                pcs = list(scale.get_pitch_classes())
            except Exception:
                pcs = list(getattr(scale, "pcs", [])) or [getattr(scale, "root_pc", 0)]

        if not pcs:
            pcs = [getattr(scale, "root_pc", 0)]

        pitches: List[int] = []
        for octv in self.octave_range:
            o = int(octv)
            for pc in pcs:
                pitches.append(note_number(pc, o))

        if not pitches:
            pitches = [
                note_number(
                    getattr(chord, "root_pc", getattr(scale, "root_pc", 0)),
                    6,
                )
            ]

        return pitches

    def _get_activity_level(self, activity_map: ActivityMap, tick: int) -> float:
        try:
            if hasattr(activity_map, "get_activity_and_breath"):
                val = activity_map.get_activity_and_breath(tick)
                if isinstance(val, (list, tuple)) and len(val) > 0:
                    return float(val[0])
                return float(val)
            if hasattr(activity_map, "get_activity_at"):
                return float(activity_map.get_activity_at(tick))
        except Exception:
            return 0.0
        return 0.0

    def _breath_phase_factor(self, tempo_map: TempoMap, tick: int) -> float:
        cycle_bars = float(getattr(tempo_map, "breath_cycle_bars", 2.0) or 2.0)
        try:
            bar_pos = tempo_map.get_bar_pos_at_tick(tick)
            phase = (bar_pos / cycle_bars) % 1.0
        except Exception:
            phase = 0.0

        lfo = (math.sin(phase * 2.0 * math.pi - (math.pi / 2.0)) + 1.0) / 2.0
        factor = 0.5 + 0.7 * lfo
        return float(_clamp(factor, 0.4, 1.4))

    def _compute_velocity(self, energy: float) -> int:
        base = int(self.base_velocity)
        delta_e = int(-12 + 20 * _clamp(energy, 0.0, 1.0))
        intensity_scale = 0.6 + 0.6 * _clamp(self.master_intensity, 0.0, 1.0)

        vel = int((base + delta_e) * intensity_scale)
        vel += random.randint(-self.vel_jitter, self.vel_jitter)

        # ZenArcMatrix vel_bias
        if self.zen_arc_matrix is not None:
            try:
                cfg = getattr(self.zen_arc_matrix, "cached_last", None)
                if isinstance(cfg, dict) and "vel_bias" in cfg:
                    vel += int(cfg["vel_bias"])
            except Exception:
                pass

        return int(_clamp(float(vel), 1.0, 127.0))

    def _apply_pan_jitter(self, tick: int) -> None:
        if self.pan_jitter <= 0 or self.track is None:
            return
        center = 64
        offset = random.randint(-self.pan_jitter, self.pan_jitter)
        pan_val = int(_clamp(center + offset, 0, 127))
        self.track.add_cc(tick, 10, pan_val)

ChimeEngine = ChimeEngineV1
ChimeEngineV3 = ChimeEngineV1
