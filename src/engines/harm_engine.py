"""
# Tệp: src/engines/harm_engine.py
# (FINAL V10.11.1) - ZEN LIQUID HARMONY ENGINE (HARM ENGINE V3 MERGED + SAFETY/ACTIVITY/ARC)
#
# Base:
#   - (FINAL V9.9.80) LIQUID HARMONY UPGRADE
#   - (DRAFT V10.7.1) HARM ENGINE V3 (CLEAN + TUNING FIX)
#
# Mục tiêu:
#   - Giữ nguyên "chất" HARM cũ: Liquid Overlap, Neo Zen Open Voicing,
#     Layer Strings = Power Chord mỏng, Asymmetric Breathing.
#   - Bổ sung:
#       + Zen Arc Density: Intro/Immersion/Peak/Breakdown/Outro
#         ảnh hưởng mức "độ dày" & màu sắc hợp âm (có thể bias thêm bởi ZenArcMatrix).
#       + Register-safe: dùng RegisterManager (nếu có) để giữ HARM đúng quãng.
#       + Hook cho SafetyFilter, BreathSync, ActivityMap (theo đúng lý thuyết đã chốt).
#   - Không tự làm lại Solf tuning; tôn trọng TuningCoreV3/TuningPlan & writer
#     (DynamicTransposingWriter) ở Zen Core.
#
# Interface (Zen Core đang dùng):
#   eng_main  = HarmEngine(
#       writer=trans_writer,
#       profile=prof_main,
#       channel=1,
#       role="main",
#       safety_filter=safety_filter,
#       register_manager=register_manager,
#       breath_sync=breath_sync,
#       activity_map=activity_map,
#       zen_arc_matrix=zen_arc,
#       layer_name="harm_main",
#   )
#   eng_layer = HarmEngine(... role="layer", layer_name="harm_layer")
#
#   eng_main.render_main(segments, key, scale, tempo_map, fade_cfg={})
#   eng_layer.render_layer(segments, eng_main.get_voicing_map(), "normal", 1, tempo_map)
"""

from __future__ import annotations

import random
import math
from typing import List, Dict, Optional, Tuple, Any

from src.utils.midi_writer import MidiWriter
from src.core.music_theory import Chord, VoiceLeading, Scale, note_number
from src.core.structure_builder import Segment
from src.core.tempo_breath import TempoMap

# Các class Zen Core mới (tùy chọn, không bắt buộc phải có khi import)
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
    from src.utils.activity_map import ActivityMap
except Exception:  # pragma: no cover
    ActivityMap = None  # type: ignore[misc]

try:  # pragma: no cover
    from src.core.zen_arc_matrix import ZenArcMatrix
except Exception:  # pragma: no cover
    ZenArcMatrix = None  # type: ignore[misc]

class HarmEngine:
    """
    Zen Liquid Harmony Engine:
    - Vai trò: tạo lớp HARM (Pad/Texture) + Layer Strings mỏng.
    - Tôn trọng hợp âm: mọi voicing đều khởi nguồn từ chord.pcs + scale.
    """

    def __init__(
        self,
        writer: MidiWriter,
        profile,
        channel: int,
        role: str = "main",
        scale_family: str = "diatonic",
        *,
        # Neo Zen cores (tuỳ chọn)
        safety_filter: Optional["SafetyFilter"] = None,
        register_manager: Optional["RegisterManager"] = None,
        breath_sync: Optional["BreathSyncManager"] = None,
        activity_map: Optional["ActivityMap"] = None,
        zen_arc_matrix: Optional["ZenArcMatrix"] = None,
        layer_name: str = "harm",
        user_options: Optional[Dict[str, Any]] = None,
    ):
        self.writer = writer
        self.track = writer.get_track(channel)
        self.profile = profile
        self.channel = channel
        self.role = role
        self.ppq = writer.ppq
        self.scale_family = scale_family or "diatonic"

        self.safety_filter = safety_filter
        self.register_manager = register_manager
        self.breath_sync = breath_sync
        self.activity_map = activity_map
        self.zen_arc_matrix = zen_arc_matrix
        self.layer_name = layer_name or "harm"
        self.user_options = user_options or {}

        # ========= Mix & Tone =========
        self.base_velocity = int(getattr(profile, "velocity", 80))
        self.base_velocity = max(1, min(127, self.base_velocity))

        # Chế độ hòa âm (pad / arpeggio / modal_texture)
        self.mode = getattr(profile, "v7_harm_mode", None) or "pad"

        # Neo Zen params
        self.color_intensity = float(getattr(profile, "v9_color_intensity", 0.6))
        self.motion_intensity = float(getattr(profile, "v9_motion_intensity", 0.4))
        self.voicing_mode = getattr(profile, "v9_voicing_mode", "normal")

        # Micro Drift (Slight detune)
        self.enable_breath_filter = bool(
            getattr(profile, "enable_breath_filter", False)
        )
        self.filter_min_cc = int(getattr(profile, "filter_min_cc", 30))
        self.filter_max_cc = int(getattr(profile, "filter_max_cc", 90))

        self.enable_drift = bool(getattr(profile, "enable_drift", False))
        self.drift_amount_cents = float(getattr(profile, "drift_amount_cents", 8.0))
        self.drift_cycle_secs = float(getattr(profile, "drift_cycle_secs", 30.0))

        # Liquid overlap
        self.overlap_factor = float(getattr(profile, "overlap_factor", 0.5))
        if self.overlap_factor < 0.0:
            self.overlap_factor = 0.0
        if self.overlap_factor > 2.0:
            self.overlap_factor = 2.0

        # Zen Arc density bias (base)
        self.base_density = float(getattr(profile, "base_density", 1.0))

        # Range hint (dùng cho RegisterManager)
        self.default_register_layer = "harm" if role == "main" else "harm_layer"

        # Internal voicing memory
        self.voicing_map: Dict[int, List[int]] = {}
        self.voice_leading_module = VoiceLeading()
        self.last_voicing: List[int] = []
        self.last_chord_name: Optional[str] = None

    # -------------------------------------------------
    # Public API
    # -------------------------------------------------
    def get_voicing_map(self) -> Dict[int, List[int]]:
        """
        Map: segment.start_tick -> list[pitch int]
        Dùng cho Layer Strings bám theo voicing của main pad.
        """
        return self.voicing_map

    # ==================================================
    # Helpers: Activity / Meta
    # ==================================================
    def _get_activity_factor(self, segment: Segment) -> Optional[float]:
        """
        Lấy mức Activity 0..1 cho layer HARM trên segment này, nếu có ActivityMap.
        Nếu không có/không tương thích → trả về None (fallback về hành vi cũ).
        """
        if self.activity_map is None or ActivityMap is None:
            return None
        try:
            # Ưu tiên API dạng: get_activity_for_layer(layer, start_tick, end_tick)
            if hasattr(self.activity_map, "get_activity_for_layer"):
                return float(
                    self.activity_map.get_activity_for_layer(
                        self.layer_name,
                        segment.start_tick,
                        segment.end_tick,
                    )
                )
            # Fallback: API dạng get_activity(start_tick, end_tick, layer=...)
            if hasattr(self.activity_map, "get_activity"):
                return float(
                    self.activity_map.get_activity(
                        segment.start_tick,
                        segment.end_tick,
                        layer=self.layer_name,
                    )
                )
        except Exception:
            return None
        return None

    def _build_note_meta(self, segment: Segment, real_start: int, real_duration: int) -> Dict[str, Any]:
        """
        Meta chung gửi cho SafetyFilter/ActivityMap:
        - layer, role, section_type, energy_bias, t_range, v.v.
        """
        meta: Dict[str, Any] = {
            "layer": self.layer_name,
            "role": self.role,
            "section_type": getattr(segment, "section_type", ""),
            "energy_bias": float(getattr(segment, "energy_bias", 0.5) or 0.5),
            "start_tick": int(real_start),
            "duration_ticks": int(real_duration),
            "segment_start": int(segment.start_tick),
            "segment_end": int(segment.end_tick),
        }

        # Activity (nếu có)
        act = self._get_activity_factor(segment)
        if act is not None:
            meta["activity"] = float(act)

        # Breath info (nếu BreathSyncManager hỗ trợ)
        if self.breath_sync is not None and BreathSyncManager is not None:
            try:
                if hasattr(self.breath_sync, "get_breath_info_at_tick"):
                    info = self.breath_sync.get_breath_info_at_tick(real_start)
                    meta["breath_info"] = info
            except Exception:
                pass

        return meta

    def _resolve_phase_radians(self, current_tick: int, tempo_map: Optional[TempoMap]) -> float:
        """
        Tìm phase (rad) dựa trên BreathSync nếu có, fallback về TempoMap.
        """
        if self.breath_sync is not None and BreathSyncManager is not None:
            try:
                if hasattr(self.breath_sync, "get_phase_at_tick"):
                    return float(self.breath_sync.get_phase_at_tick(current_tick))
            except Exception:
                pass

        if tempo_map is not None:
            try:
                bar = tempo_map.get_bar_pos_at_tick(current_tick)
                return tempo_map.get_phase_at_bar(bar)
            except Exception:
                return 0.0

        return 0.0

    def _resolve_phase_ratio(self, current_tick: int, tempo_map: Optional[TempoMap]) -> float:
        """
        Chuẩn hoá phase về 0..1 để dùng cho các phép nội suy (Inhale/Exhale).
        """
        radians = self._resolve_phase_radians(current_tick, tempo_map)
        return (radians / (2 * math.pi)) % 1.0

    # ---------------- MAIN LAYER ----------------
    def render_main(
        self,
        segments: List[Segment],
        key: str,
        scale_type: str,
        tempo_map: TempoMap,
        fade_cfg: Optional[Dict[str, int]],
        retune_offset_cents: float = 0.0,  # giữ cho tương thích cũ, hiện không dùng
    ) -> None:
        """
        Lớp HARM chính (Pad / Texture):
        - Voicing theo hợp âm + Scale (đảm bảo "đúng" nhạc lý).
        - Zen Arc điều khiển density/màu sắc (có thể bias thêm bởi ZenArcMatrix).
        - ActivityMap điều tiết: Activity cao → giảm "màu" & velocity nhẹ (không cúp pad).
        - Liquid Overlap + Breath/Filter CC.
        """
        if self.role != "main":
            return
        if not segments:
            return

        full_scale = Scale(key, scale_type, family=self.scale_family)

        # Micro drift cho pad tĩnh (bỏ qua nếu không cần)
        if self.mode == "pad" and self.enable_drift and segments:
            total_ticks = segments[-1].end_tick
            self._apply_micro_drift(total_ticks)

        timeline: List[Tuple[Segment, List[int]]] = []

        for segment in segments:
            energy_bias = float(getattr(segment, "energy_bias", 0.5) or 0.5)
            sec_type = (getattr(segment, "section_type", "") or "").lower()

            # Zen Arc density factor 0.1..2.0 (có thể bias bởi ZenArcMatrix)
            arc_density = self._arc_density(sec_type, energy_bias)

            # ActivityMap (nhẹ): Activity cao → giảm nhẹ density (chủ yếu ảnh hưởng color tone)
            act = self._get_activity_factor(segment)
            if act is not None:
                a = max(0.0, min(1.0, float(act)))
                # Activity=0 → 1.0 ; Activity=1 → ~0.6
                density_damper = 1.0 - 0.4 * a
                arc_density *= density_damper

            should_restrike = True
            if self.mode == "pad":
                motion_factor = (
                    1.6
                    if getattr(self.profile, "v9_motion_mode", "normal") == "low_motion"
                    else 1.0
                )
                # Nếu chord không đổi và motion thấp, giữ voicing cũ để liền mạch
                if (
                    self.last_chord_name == segment.chord_name
                    and self.last_voicing
                    and random.random()
                    > (self.motion_intensity * motion_factor * arc_density)
                ):
                    should_restrike = False

            voicing: List[int] = []
            if not should_restrike and self.last_voicing:
                voicing = self.last_voicing
            else:
                chord = Chord(segment.chord_name, key, scale_type)
                if chord and chord.pcs:
                    target_pcs = self._get_zen_voicing(
                        chord, full_scale, arc_density
                    )

                    # Lựa chọn voicing mode:
                    if self.voicing_mode == "stable_locked":
                        voicing = self._shape_voicing_stable_locked(
                            target_pcs, target_octave=3
                        )
                    elif self.voicing_mode == "neo_zen_open":
                        voicing = self._shape_voicing_neo_zen_open(
                            target_pcs, chord.root_pc
                        )
                    elif self.voicing_mode == "ambient_open":
                        dummy = Chord(segment.chord_name)
                        dummy.pcs = target_pcs
                        raw = self.voice_leading_module.find_next_voicing(
                            dummy, self.last_voicing
                        )
                        voicing = self._shape_voicing_ambient_open(raw)
                    else:
                        dummy = Chord(segment.chord_name)
                        dummy.pcs = target_pcs
                        voicing = self.voice_leading_module.find_next_voicing(
                            dummy, self.last_voicing
                        )

            # Lưu voicing để layer dùng
            self.last_voicing = voicing
            self.last_chord_name = segment.chord_name
            timeline.append((segment, voicing))
            self.voicing_map[segment.start_tick] = voicing

        # Render timeline
        active_tied_notes = set()  # type: ignore[var-annotated]
        for i, (segment, voicing) in enumerate(timeline):
            next_voicing: List[int] = []
            if i < len(timeline) - 1:
                next_voicing = timeline[i + 1][1]

            energy_bias = float(getattr(segment, "energy_bias", 0.5) or 0.5)

            if self.mode == "pad":
                notes_to_attack: List[Tuple[int, int]] = []
                next_tied_notes = set()

                for note in voicing:
                    duration = segment.duration_ticks
                    if note in next_voicing:
                        duration += timeline[i + 1][0].duration_ticks
                        next_tied_notes.add(note)
                    if note in active_tied_notes:
                        continue
                    notes_to_attack.append((note, duration))

                # ActivityMap ảnh hưởng velocity (nhẹ): Activity cao → vel_scale ~0.8
                vel_scale = 1.0
                act = self._get_activity_factor(segment)
                if act is not None:
                    a = max(0.0, min(1.0, float(act)))
                    vel_scale = 1.0 - 0.2 * a

                self._render_pad_notes(notes_to_attack, segment, velocity_scale=vel_scale)

                self._apply_breathing_cc(
                    segment, tempo_map, fade_cfg, energy_bias
                )

                if self.enable_breath_filter:
                    self._apply_breath_filter(segment, tempo_map)

                active_tied_notes = next_tied_notes

            elif self.mode == "arpeggio":
                self._render_zen_strum(voicing, segment)
            elif self.mode == "modal_texture":
                cloud_voicing = [n + 12 for n in voicing]
                self._render_cloud(cloud_voicing, segment, full_scale, tempo_map)

    # ---------------- LAYER STRINGS ----------------
    def render_layer(
        self,
        segments: List[Segment],
        base_voicing_map: Dict[int, List[int]],
        layer_logic: str,
        octave_shift: int = 0,
        tempo_map: Optional[TempoMap] = None,
    ) -> None:
        """
        Lớp phụ (Layer): đánh Root + 5th (Power Chord) mỏng hơn,
        dùng voicing_map của Harm chính để bám theo.
        - ActivityMap có thể giảm thêm velocity khi Activity cao.
        """
        if self.role != "layer":
            return

        for segment in segments:
            base_voicing = base_voicing_map.get(segment.start_tick)
            if not base_voicing:
                continue

            # Thin Layering (Power Chord)
            sorted_v = sorted(base_voicing)
            if len(sorted_v) >= 1:
                root = sorted_v[0]
                thin_voicing = [root]
                fifth = root + 7
                if fifth < 80:  # hạn chế quá cao
                    thin_voicing.append(fifth)

                # Dịch octave (thường là hạ xuống làm nền)
                final_notes = [p + (12 * (octave_shift - 1)) for p in thin_voicing]
            else:
                final_notes = []

            if not final_notes:
                continue

            note_data = [(n, segment.duration_ticks) for n in final_notes]

            # Giảm Velocity của lớp phụ (so với profile gốc)
            original_vel = int(getattr(self.profile, "velocity", 80))
            self.profile.velocity = int(original_vel * 0.7)

            # ActivityMap ảnh hưởng thêm velocity scale
            vel_scale = 1.0
            act = self._get_activity_factor(segment)
            if act is not None:
                a = max(0.0, min(1.0, float(act)))
                vel_scale = 1.0 - 0.3 * a  # layer dễ bị rối hơn nên giảm mạnh hơn chút

            # Render với Liquid Overlap + SafetyFilter/Register
            self._render_pad_notes(note_data, segment, velocity_scale=vel_scale)

            # Trả lại velocity cũ
            self.profile.velocity = original_vel

            # Breath CC nhẹ cho Layer
            energy_bias = getattr(segment, "energy_bias", 0.5)
            self._apply_breathing_cc(
                segment, tempo_map, fade_cfg=None, energy_level=energy_bias
            )

            if self.enable_breath_filter and tempo_map is not None:
                self._apply_breath_filter(segment, tempo_map)

    # ==================================================
    # ZEN ARC DENSITY (từ bản nháp V3, tinh giản)
    # ==================================================
    def _arc_density(self, sec_type: str, energy: float) -> float:
        """
        Trả về factor 0.1..2.0 để điều chỉnh "độ dày" hoà âm theo:
        - section_type (Grounding / Immersion / Peak / Breakdown / Integration...)
        - energy_bias (0..1).
        Có thể được bias thêm bởi ZenArcMatrix (nếu có).
        """
        s = (sec_type or "").lower()
        if s in ("intro", "grounding"):
            arc = 0.7
        elif s == "immersion":
            arc = 1.0
        elif s in ("peak", "awakening"):
            arc = 1.25
        elif s in ("outro", "integration"):
            arc = 0.6
        elif s in ("bridge", "breakdown"):
            arc = 0.3
        else:
            arc = 0.8

        energy = max(0.0, min(1.0, float(energy)))
        base = self.base_density if self.base_density > 0 else 1.0
        val = arc * base * (0.7 + 0.6 * energy)

        # Bias thêm từ ZenArcMatrix nếu có
        if self.zen_arc_matrix is not None and ZenArcMatrix is not None:
            try:
                layer = self.layer_name or self.default_register_layer
                if hasattr(self.zen_arc_matrix, "get_density_factor"):
                    factor = float(
                        self.zen_arc_matrix.get_density_factor(
                            layer=layer,
                            section_type=s,
                            energy=energy,
                        )
                    )
                    val *= factor
            except Exception:
                # Nếu matrix khác interface, bỏ qua để không phá hành vi cũ
                pass

        return float(max(0.1, min(2.0, val)))

    # ==================================================
    # Voicing & Color (hòa hợp với hợp âm + scale)
    # ==================================================
    def _get_zen_voicing(
        self,
        chord: Chord,
        scale: Scale,
        arc_density: float,
    ) -> List[int]:
        """
        Xây dựng tập pcs "đẹp, hòa hợp":
        - Luôn chứa root + 3rd/5th theo chord.pcs.
        - Tùy theo density & color_intensity mới thêm 7th/9th (nếu nằm trong Scale).
        """
        pcs = set(chord.pcs)

        # Thêm 9th dựa trên color_intensity * arc_density (Immersion/Peak sẽ "màu" hơn)
        effective_color = self.color_intensity * arc_density
        if random.random() < effective_color:
            ninth = (chord.root_pc + 2) % 12
            if scale.contains_pc(ninth):
                pcs.add(ninth)

        # Có thể thêm 7th nếu chord đã là dominant/maj7/m7 sẵn (pcs đã chứa).
        # Không thêm tùy tiện ngoài chord.pcs để tránh sai ngữ điệu.

        return list(pcs)

    def _shape_voicing_stable_locked(
        self,
        pcs: List[int],
        target_octave: int = 3,
    ) -> List[int]:
        """Voicing cố định trong một register (C3..B3...)."""
        base = [note_number(pc, target_octave) for pc in pcs]
        base = sorted(list(set(base)))
        return self._apply_register_constraints(base)

    def _shape_voicing_neo_zen_open(
        self,
        pcs: List[int],
        root_pc: int,
    ) -> List[int]:
        """
        Spread voicing:
        - Bass (Root) ở Octave 2.
        - Fifth ở Octave 2.
        - Color tones ở Octave 3/4.
        """
        voicing: List[int] = []

        # 1. Root (C2..B2)
        voicing.append(note_number(root_pc, 2))

        # 2. Fifth
        fifth_pc = (root_pc + 7) % 12
        if fifth_pc in pcs:
            voicing.append(note_number(fifth_pc, 2))

        # 3. Color tones
        remaining_pcs = [p for p in pcs if p != root_pc and p != fifth_pc]
        for pc in remaining_pcs:
            cand_3 = note_number(pc, 3)
            cand_4 = note_number(pc, 4)
            if cand_3 < 53:
                voicing.append(cand_4)
            else:
                voicing.append(cand_3)

        voicing = sorted(list(set(voicing)))
        return self._apply_register_constraints(voicing)

    def _shape_voicing_ambient_open(self, voicing: List[int]) -> List[int]:
        """
        Ambient open: giữ ba điểm neo (low/mid/high).
        """
        if len(voicing) <= 3:
            return self._apply_register_constraints(voicing)
        s = sorted(voicing)
        shaped = [s[0], s[len(s) // 2], s[-1]]
        return self._apply_register_constraints(shaped)

    # ==================================================
    # Register constraints (dùng RegisterManager nếu có)
    # ==================================================
    def _apply_register_constraints(self, pitches: List[int]) -> List[int]:
        """
        Nếu có RegisterManager:
            - Clamp từng pitch vào band của layer_name tương ứng.
        Nếu không:
            - Giữ nguyên (tránh phá bản cũ).
        """
        if not pitches:
            return pitches

        if self.register_manager is None or RegisterManager is None:
            return pitches

        layer = self.layer_name or self.default_register_layer
        constrained: List[int] = []
        for p in pitches:
            safe_p = self.register_manager.constrain_pitch(layer, int(p))
            constrained.append(safe_p)
        return constrained

    # ==================================================
    # Rendering helpers
    # ==================================================
    def _render_pad_notes(
        self,
        note_data: List[Tuple[int, int]],
        segment: Segment,
        velocity_scale: float = 1.0,
    ) -> None:
        """
        Render nhóm nốt Pad với Liquid Overlap + Register-safe + SafetyFilter.
        note_data: List[(pitch, duration_ticks)] tính theo segment.
        - RegisterManager: clamp quãng theo layer.
        - SafetyFilter: mọi note đi qua adjust(layer, pitch, velocity, tick, meta).
            + new_vel <= 0 → bỏ note.
        """
        if not note_data:
            return

        base_vel_profile = int(getattr(self.profile, "velocity", self.base_velocity))
        base_vel_profile = max(1, min(127, base_vel_profile))
        base_vel = int(base_vel_profile * float(velocity_scale))
        base_vel = max(1, min(127, base_vel))

        start_tick = segment.start_tick

        # Liquid Overlap: ngân thêm 1/2 bar (có thể scale theo overlap_factor)
        overlap_ticks = int(self.ppq * 4 * self.overlap_factor)

        # Áp Register trước khi sort/strum
        safe_notes: List[Tuple[int, int]] = []
        for n, dur in note_data:
            if self.register_manager is not None and RegisterManager is not None:
                layer = self.layer_name or self.default_register_layer
                try:
                    n = self.register_manager.constrain_pitch(layer, int(n))
                except Exception:
                    n = int(n)
            safe_notes.append((n, dur))

        sorted_notes = sorted(safe_notes, key=lambda x: x[0])

        ticks_per_ms = self.ppq / 500.0
        current_delay = 0.0

        for note, duration in sorted_notes:
            real_duration = duration + overlap_ticks
            real_start = start_tick + int(current_delay)

            vel = base_vel
            meta = self._build_note_meta(segment, real_start, real_duration)

            # SafetyFilter: cho phép chỉnh velocity / bỏ nốt
            if self.safety_filter is not None and SafetyFilter is not None:
                try:
                    if hasattr(self.safety_filter, "adjust"):
                        new_vel = self.safety_filter.adjust(
                            layer=self.layer_name,
                            pitch=int(note),
                            velocity=int(vel),
                            tick=int(real_start),
                            meta=meta,
                        )
                        if new_vel is None:
                            new_vel = vel
                        new_vel = int(new_vel)
                        if new_vel <= 0:
                            # Bỏ nốt này
                            current_delay += random.uniform(150, 400) * ticks_per_ms
                            continue
                        vel = max(1, min(127, new_vel))
                except Exception:
                    # Nếu SafetyFilter khác interface, bỏ qua để không phá hành vi cũ
                    pass

            self.track.add_note(
                int(note),
                int(vel),
                int(real_start),
                int(real_duration),
            )
            # Strum nhẹ 150–400 ms
            current_delay += random.uniform(150, 400) * ticks_per_ms

    def _apply_breathing_cc(
        self,
        segment: Segment,
        tempo_map: Optional[TempoMap],
        fade_cfg: Optional[Dict[str, int]],
        energy_level: float = 0.5,
    ) -> None:
        """
        Volume + Filter Morph theo nhịp thở.
        ĐÃ LÀM AN TOÀN với fade_cfg=None hoặc {}.
        - Nếu có BreathSyncManager hỗ trợ phase → ưu tiên dùng.
        - Nếu không → fallback TempoMap như bản cũ.
        """
        if tempo_map is None:
            return

        step = max(1, self.ppq // 2)

        # Các tham số fade an toàn
        fade_in_len = int((fade_cfg or {}).get("in", 0) or 0)
        out_start = int((fade_cfg or {}).get("out_start", 10**12))
        fade_out_len = int((fade_cfg or {}).get("out", 0) or 0)
        total = int((fade_cfg or {}).get("total", segment.end_tick))

        for t in range(0, segment.duration_ticks, step):
            current_tick = segment.start_tick + t

            # Fade factor
            fade = 1.0
            if fade_in_len > 0 and current_tick < fade_in_len:
                fade = current_tick / float(max(1, fade_in_len))
            if current_tick > out_start and fade_out_len > 0:
                fade = max(
                    0.0,
                    (total - current_tick) / float(max(1, fade_out_len)),
                )

            phase = self._resolve_phase_radians(current_tick, tempo_map)

            # 1. Volume (CC11)
            vol = int((70 + 15 * math.sin(phase)) * fade)
            vol = max(0, min(127, vol))
            self.track.add_cc(current_tick, 11, vol)

            # 2. Filter (CC74) – chỉ vẽ nếu Breath Filter tắt
            if not self.enable_breath_filter:
                base_filt = 30 + int(energy_level * 20)
                range_filt = 40 + int(energy_level * 30)
                filt = int(
                    base_filt
                    + range_filt * ((math.sin(phase - 1.0) + 1) / 2.0)
                )
                filt = int(filt * fade)
                self.track.add_cc(current_tick, 74, max(0, min(127, filt)))

            # 3. Morph (CC1)
            macro_phase = current_tick / float(self.ppq * 256) * 2 * math.pi
            morph_val = int(30 + 70 * ((math.sin(macro_phase) + 1) / 2.0))
            morph_val = max(0, min(127, morph_val))
            self.track.add_cc(current_tick, 1, morph_val)

    def _apply_breath_filter(self, segment: Segment, tempo_map: TempoMap) -> None:
        """
        Asymmetric Breathing (30% Inhale - 70% Exhale) trên Filter (CC74).
        - Nếu BreathSyncManager có hỗ trợ phase → có thể dùng, nếu không → TempoMap như cũ.
        """
        if segment.duration_ticks <= 0:
            return

        step = max(1, self.ppq // 4)
        INHALE_RATIO = 0.3
        last_cc_val: Optional[int] = None

        for t in range(0, segment.duration_ticks, step):
            current_tick = segment.start_tick + t

            phase_ratio = self._resolve_phase_ratio(current_tick, tempo_map)

            if phase_ratio < INHALE_RATIO:
                local_p = phase_ratio / INHALE_RATIO
                mod = math.sin(local_p * (math.pi / 2))
            else:
                local_p = (phase_ratio - INHALE_RATIO) / (1.0 - INHALE_RATIO)
                mod = math.cos(local_p * (math.pi / 2))

            cc_val = int(
                self.filter_min_cc
                + (mod * (self.filter_max_cc - self.filter_min_cc))
            )
            cc_val = max(0, min(127, cc_val))

            if last_cc_val is not None and cc_val == last_cc_val:
                continue

            self.track.add_cc(current_tick, 74, cc_val)
            last_cc_val = cc_val

    def _render_zen_strum(self, voicing: List[int], segment: Segment) -> None:
        """
        Arpeggio / Strum nhẹ nhàng: dùng pcs của voicing, trải trên 2 octave.
        """
        expanded: List[int] = []
        for off in [0, 1]:
            for pc in [n % 12 for n in voicing]:
                expanded.append(note_number(pc, 3 + off))
        expanded = self._apply_register_constraints(sorted(list(set(expanded))))
        step = max(1, self.ppq // 2)
        for k, n in enumerate(expanded):
            t = segment.start_tick + k * step
            if t < segment.end_tick:
                self.track.add_note(
                    n,
                    int(getattr(self.profile, "velocity", self.base_velocity)),
                    t,
                    segment.end_tick - t,
                )

    def _render_cloud(
        self,
        voicing: List[int],
        segment: Segment,
        scale: Scale,
        tempo_map: TempoMap,
    ) -> None:
        """
        Modal Texture: cụm nốt rải ngẫu nhiên, nhẹ, phía trên HARM chính.
        """
        self.track.add_cc(segment.start_tick, 73, 100)
        self.track.add_cc(segment.start_tick, 72, 90)

        for _ in range(random.randint(3, 5)):
            if random.random() < 0.7 and voicing:
                note = random.choice(voicing)
            else:
                note = note_number(
                    random.choice(scale.pcs), random.choice([5, 6])
                )
            start = segment.start_tick + random.randint(
                0, max(1, segment.duration_ticks // 2)
            )
            dur = random.randint(self.ppq, self.ppq * 3)
            self.track.add_note(note, 50, start, dur)

    # ==================================================
    # Micro Drift (pad float)
    # ==================================================
    def _apply_micro_drift(self, total_ticks: int) -> None:
        if total_ticks <= 0:
            return

        # Bước cập nhật drift (mỗi beat)
        step = max(1, self.ppq)

        # Ước lượng: ~1.5 beat / sec
        avg_ticks_per_sec = self.ppq * 1.5
        cycle_ticks = int(self.drift_cycle_secs * avg_ticks_per_sec)
        if cycle_ticks <= 0:
            cycle_ticks = 1000

        for t in range(0, total_ticks, step):
            phase = (t / cycle_ticks) * 2 * math.pi
            drift_cents = math.sin(phase) * self.drift_amount_cents

            # 8192 center; 100 cents = 1 semitone ≈ 4096 units
            bend_val_offset = int(drift_cents * (4096.0 / 100.0))
            final_bend = max(0, min(16383, 8192 + bend_val_offset))
            self.track.add_pitch_bend(t, final_bend)

# Alias cho code cũ còn dùng HarmEngineV9
HarmEngineV9 = HarmEngine
