# Tệp: src/core/melody_generator.py
# (FINAL V10.10.0) - MELODY GENERATOR V10 (BRAIN ONLY)
# Modes: FLOW / RUBATO / MANTRA / KINTSUGI / SPARKS
#
# Vai trò:
# - "Bộ não" của Melody: quyết định câu, pitch, độ dài, nghỉ theo Zen Arc.
# - Không xử lý Performance:
#     + Không CC11, không ActivityMap, không jitter micro.
#     + Ghost / breath / beat stress do Engine (performance layer) đảm nhiệm.
#
# API:
#     gen = MelodyGenerator(ppq=480, user_options=options_dict)
#     notes = gen.generate_full_melody(segments, key, scale)
#
# Tích hợp:
# - Học logic từ bản phác thảo:
#   + Modes: flow / rubato / mantra / kintsugi / sparks (qua user_options["melody_play_mode"])
#   + Rest theo Arc: energy_bias + section_type + master_intensity + breakdown_mode.
#   + Pentatonic Relax: melody_scale_mode = "pentatonic_relax".
#   + Breakdown: "soft" / "mute" / "normal".
#   + Flute ornament: tăng nhảy quãng 8 nhẹ nếu flute_ornament_mode=True
#     (grace note chi tiết vẫn để Engine/performance xử lý).
#
# MelodyNote vẫn là "thô": Engine phía sau có thể gọi
# src/utils/performance.enhance_melody_note() để hoàn thiện.

import random
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

from src.core.music_theory import Scale, Chord, note_number
from src.core.structure_builder import Segment


def _clamp(n: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, n))


@dataclass
class MelodyNote:
    start_tick: int
    duration_ticks: int
    pitch: int
    velocity: int
    # kind = "main" / "ghost" / "ornament" nếu Engine muốn phân biệt
    kind: str = "main"


class MelodyGenerator:
    def __init__(self, ppq: int = 480, user_options: Optional[Dict[str, Any]] = None):
        self.ppq = int(ppq)
        self.user_options = user_options or {}

        # ====== Core config ======
        self.base_velocity: int = int(self.user_options.get("melody_base_velocity", 70))
        self.humanize_amt: int = int(self.user_options.get("humanize_velocity", 5))

        # Register (quãng) cho melody
        reg_low = int(self.user_options.get("melody_register_low", 60))
        reg_high = int(self.user_options.get("melody_register_high", 84))
        if reg_low > reg_high:
            reg_low, reg_high = reg_high, reg_low
        self.reg_low = reg_low
        self.reg_high = reg_high

        # Giới hạn pitch cứng (MIDI)
        self.min_pitch = int(self.user_options.get("melody_min_pitch", reg_low))
        self.max_pitch = int(self.user_options.get("melody_max_pitch", reg_high))

        # Play mode: flow / rubato / mantra / kintsugi / sparks
        self.play_mode: str = str(
            self.user_options.get("melody_play_mode", "rubato")
        ).lower()

        # Scale mode: diatonic / pentatonic_relax
        self.scale_mode: str = str(
            self.user_options.get("melody_scale_mode", "diatonic")
        ).lower()

        # Intensity + Arc rest
        self.master_intensity: float = _clamp(
            float(self.user_options.get("melody_master_intensity", 0.6)), 0.0, 1.0
        )
        self.phrase_rest_prob: float = _clamp(
            float(self.user_options.get("melody_phrase_rest_prob", 0.4)), 0.0, 1.0
        )
        self.arc_rest_bias: float = _clamp(
            float(self.user_options.get("melody_arc_rest_bias", 1.0)), 0.5, 1.5
        )

        # Breakdown behavior: "soft" / "mute" / "normal"
        self.breakdown_mode: str = str(
            self.user_options.get("melody_breakdown_mode", "soft")
        ).lower()
        if self.breakdown_mode not in ("soft", "mute", "normal"):
            self.breakdown_mode = "soft"

        # Flute ornament (ở level Brain: bias pitch jump, không vẽ grace note)
        self.flute_ornament_mode: bool = bool(
            self.user_options.get("flute_ornament_mode", False)
        )
        self.ornament_octave_jump_prob: float = _clamp(
            float(self.user_options.get("ornament_octave_jump_prob", 0.15)),
            0.0,
            1.0,
        )

        # Motif memory cho Kintsugi / Mantra
        self.motif_memory: List[int] = []
        self.motif_counter: int = 0

        # Pitch hiện tại để tránh nhảy quá xa
        self.cur_pitch: Optional[int] = None

    # =========================================================
    # PUBLIC API
    # =========================================================
    def generate_full_melody(
        self,
        segments: List[Segment],
        key: str,
        scale: str,
    ) -> List[MelodyNote]:
        """
        Tạo list MelodyNote "thô" cho toàn bộ track.
        - Tôn trọng Zen Arc (energy_bias, section_type).
        - Mode tuỳ theo self.play_mode.
        - Không xử lý Performance (CC, jitter micro, ActivityMap).
        """
        full_melody: List[MelodyNote] = []
        if not segments:
            return full_melody

        key = str(key).upper()
        scale = str(scale).lower()

        # Chuẩn bị scale pentatonic_relax / diatonic
        scale_pcs = self._get_scale_pcs(key, scale)

        for idx, seg in enumerate(segments):
            if seg.duration_ticks <= 0:
                continue

            energy = self._get_segment_energy(seg)
            if self._should_rest(seg, energy, idx):
                continue

            # Chord của segment (fallback: dùng key nếu parse thất bại)
            try:
                chord = Chord(seg.chord_name, key, scale)
            except Exception:
                chord = Chord(key, key, scale)

            # Nếu chord không parse được thì bỏ qua segment
            if not getattr(chord, "pcs", None):
                continue

            if self.play_mode == "kintsugi":
                seg_notes = self._render_kintsugi(seg, chord, scale_pcs, energy)
            elif self.play_mode == "mantra":
                seg_notes = self._render_mantra(seg, chord, scale_pcs, energy)
            elif self.play_mode == "sparks":
                seg_notes = self._render_sparks(seg, chord, scale_pcs, energy)
            else:
                # flow / rubato
                if self.play_mode == "flow":
                    seg_notes = self._render_flow_rhythmic(
                        seg, chord, scale_pcs, energy
                    )
                else:
                    seg_notes = self._render_flow_rubato(
                        seg, chord, scale_pcs, energy
                    )

            if seg_notes:
                full_melody.extend(seg_notes)
                self.cur_pitch = seg_notes[-1].pitch

        return full_melody

    # =========================================================
    # SCALE / ENERGY / REST
    # =========================================================
    def _get_scale_pcs(self, key: str, scale: str) -> List[int]:
        """
        Lấy pitch-classes cho melody:
        - Nếu melody_scale_mode="pentatonic_relax": lọc ra ngũ cung mềm.
        - Ngược lại: dùng full scale.
        """
        base = Scale(key, scale)
        pcs = list(base.get_pitch_classes())
        root = base.root_pc

        if self.scale_mode == "pentatonic_relax":
            if "minor" in scale.lower() or "dorian" in scale.lower():
                allowed = [0, 3, 5, 7, 10]  # minor pentatonic
            else:
                allowed = [0, 2, 4, 7, 9]  # major pentatonic

            filtered: List[int] = []
            for pc in pcs:
                interval = (pc - root) % 12
                if interval in allowed:
                    filtered.append(pc)
            if filtered:
                return filtered

        return pcs

    def _get_segment_energy(self, segment: Segment) -> float:
        """
        Năng lượng của melody tại segment:
        - Base: segment.energy_bias.
        - Mod thêm theo section_type + master_intensity.
        """
        seg_energy = float(getattr(segment, "energy_bias", 0.5))
        seg_energy = _clamp(seg_energy, 0.0, 1.0)

        sec = (getattr(segment, "section_type", "") or "").lower()
        if sec in ("intro", "grounding"):
            seg_energy *= 0.85
        elif sec in ("immersion",):
            seg_energy *= 1.0
        elif sec in ("awakening", "peak"):
            seg_energy *= 1.15
        elif sec in ("integration", "outro"):
            seg_energy *= 0.8
        elif sec in ("breakdown", "silence"):
            seg_energy *= 0.4

        seg_energy *= (0.5 + 0.5 * self.master_intensity)
        return _clamp(seg_energy, 0.0, 1.0)

    def _should_rest(self, segment: Segment, energy: float, idx: int) -> bool:
        """
        Quyết định nghỉ cả segment (rest phrase).
        - Dựa trên phrase_rest_prob, energy, section_type, master_intensity, breakdown_mode.
        """
        base = self.phrase_rest_prob + (1.0 - energy) * 0.3

        sec = (getattr(segment, "section_type", "") or "").lower()
        if sec in ("intro", "grounding"):
            base *= 1.2
        elif sec in ("immersion",):
            base *= 0.7
        elif sec in ("awakening", "peak"):
            base *= 0.6
        elif sec in ("integration", "outro"):
            base *= 1.1
        elif sec in ("breakdown", "silence"):
            if self.breakdown_mode == "mute":
                return True
            base = max(base, 0.7)

        base *= (1.2 - 0.4 * self.master_intensity)
        base *= self.arc_rest_bias

        prob = _clamp(base, 0.0, 0.98)
        return random.random() < prob

    def _get_weighted_pool(self, chord: Chord, scale_pcs: List[int]) -> Dict[int, float]:
        pool: Dict[int, float] = {}
        chord_pcs = set(getattr(chord, "pcs", []) or [])
        for pc in scale_pcs:
            weight = 2.0 if pc in chord_pcs else 1.0
            pool[pc] = weight
        return pool

    # =========================================================
    # NOTE SELECTION (PITCH) - BRAIN LEVEL
    # =========================================================
    def _choose_pitch_from_pool(
        self,
        weights: Dict[int, float],
        energy: float,
    ) -> int:
        """
        Chọn pitch (MIDI) từ weighted pool:
        - Ưu tiên chord tones.
        - Hạn chế nhảy quãng xa, trừ khi energy cao.
        - Nếu flute_ornament_mode: thỉnh thoảng nhảy quãng 8 nhẹ (ở level Brain).
        """
        if not weights:
            return self.cur_pitch or 72

        pcs = list(weights.keys())
        w = [max(0.01, weights[pc]) for pc in pcs]
        target_pc = random.choices(pcs, w, k=1)[0]

        # Center register
        center_ref = (self.reg_low + self.reg_high) // 2
        center = self.cur_pitch if self.cur_pitch is not None else center_ref
        center = _clamp(center, self.reg_low, self.reg_high)

        candidates = [
            note_number(target_pc, o)
            for o in range(2, 8)
            if self.reg_low <= note_number(target_pc, o) <= self.reg_high
        ]
        if not candidates:
            return 72

        # Energy → cho phép bước nhảy lớn hơn
        max_step = 2 if energy < 0.5 else 5

        if self.cur_pitch is not None:
            step_dir = random.choice([-1, 1])
            desired = self.cur_pitch + (step_dir * random.randint(0, max_step))
            pitch = min(candidates, key=lambda x: abs(x - desired))
        else:
            pitch = min(candidates, key=lambda x: abs(x - center))

        pitch = int(_clamp(pitch, self.min_pitch, self.max_pitch))

        # Brain-level flute ornament: thỉnh thoảng nhảy quãng 8
        if self.flute_ornament_mode and random.random() < self.ornament_octave_jump_prob:
            direction = random.choice([-12, 12])
            new_pitch = pitch + direction
            if self.reg_low <= new_pitch <= self.reg_high:
                pitch = new_pitch

        return pitch

    def _new_motif_from_scale(self, scale_pcs: List[int]) -> None:
        """
        Tạo motif 3 nốt từ scale (giống logic phác thảo).
        """
        if len(scale_pcs) >= 3:
            base = scale_pcs[0]
            self.motif_memory = [(p - base) % 12 for p in scale_pcs[:3]]
        else:
            self.motif_memory = [0, 2, 4]

    # =========================================================
    # FLOW MODES
    # =========================================================
    def _render_flow_rhythmic(
        self,
        segment: Segment,
        chord: Chord,
        scale_pcs: List[int],
        energy: float,
    ) -> List[MelodyNote]:
        """
        Flow rhythmic:
        - Lấp đầy ~90% segment.
        - Nhịp rõ, phù hợp meditative nhưng vẫn "có bước".
        """
        duration = segment.duration_ticks
        active_duration = int(duration * 0.9)
        current_pos = 0

        weights = self._get_weighted_pool(chord, scale_pcs)
        notes: List[MelodyNote] = []

        if energy < 0.3:
            note_choices = [2.0, 4.0]
            weights_len = [0.7, 0.3]
        elif energy < 0.7:
            note_choices = [1.0, 2.0, 0.5]
            weights_len = [0.6, 0.3, 0.1]
        else:
            note_choices = [0.5, 1.0]
            weights_len = [0.6, 0.4]

        while current_pos < active_duration:
            beat_len = random.choices(note_choices, weights_len, k=1)[0]
            note_dur_ticks = int(beat_len * self.ppq)

            if current_pos + note_dur_ticks > active_duration:
                note_dur_ticks = active_duration - current_pos
                if note_dur_ticks < self.ppq // 4:
                    break

            pitch = self._choose_pitch_from_pool(weights, energy)
            vel = int(
                self.base_velocity
                + (energy - 0.5) * 30
                + random.randint(-self.humanize_amt, self.humanize_amt)
            )
            vel = int(_clamp(vel, 1, 127))

            t_on = segment.start_tick + current_pos
            dur = max(1, int(note_dur_ticks * 0.95))  # light legato, micro do Engine xử lý

            notes.append(
                MelodyNote(
                    start_tick=t_on,
                    duration_ticks=dur,
                    pitch=pitch,
                    velocity=vel,
                    kind="main",
                )
            )

            self.cur_pitch = pitch
            current_pos += note_dur_ticks

        return notes

    def _render_flow_rubato(
        self,
        segment: Segment,
        chord: Chord,
        scale_pcs: List[int],
        energy: float,
    ) -> List[MelodyNote]:
        """
        Flow rubato:
        - Ít nốt hơn, kéo dài hơn.
        - Hợp deep meditation, nhiều khoảng trống.
        """
        duration = segment.duration_ticks
        active_duration = int(duration * 0.95)
        current_pos = 0

        weights = self._get_weighted_pool(chord, scale_pcs)
        notes: List[MelodyNote] = []

        if energy < 0.4:
            note_choices = [4.0, 2.0]
            weights_len = [0.7, 0.3]
        else:
            note_choices = [2.0, 1.0]
            weights_len = [0.6, 0.4]

        while current_pos < active_duration:
            beat_len = random.choices(note_choices, weights_len, k=1)[0]
            note_dur_ticks = int(beat_len * self.ppq)

            if current_pos + note_dur_ticks > active_duration:
                note_dur_ticks = active_duration - current_pos
                if note_dur_ticks < self.ppq // 2:
                    break

            pitch = self._choose_pitch_from_pool(weights, energy)
            vel = int(
                self.base_velocity
                + (energy - 0.5) * 25
                + random.randint(-self.humanize_amt, self.humanize_amt)
            )
            vel = int(_clamp(vel, 1, 127))

            t_on = segment.start_tick + current_pos
            dur = max(1, int(note_dur_ticks * 0.98))

            notes.append(
                MelodyNote(
                    start_tick=t_on,
                    duration_ticks=dur,
                    pitch=pitch,
                    velocity=vel,
                    kind="main",
                )
            )

            self.cur_pitch = pitch
            current_pos += note_dur_ticks

        return notes

    # =========================================================
    # KINTSUGI / MANTRA / SPARKS
    # =========================================================
    def _render_kintsugi(
        self,
        segment: Segment,
        chord: Chord,
        scale_pcs: List[int],
        energy: float,
    ) -> List[MelodyNote]:
        """
        Kintsugi:
        - Dùng motif 3 nốt lặp lại, offset trong segment.
        - Nhẹ nhàng nhưng có cấu trúc rõ ràng.
        """
        if not self.motif_memory or self.motif_counter % 3 == 0:
            self._new_motif_from_scale(scale_pcs)
        self.motif_counter += 1

        notes: List[MelodyNote] = []
        root_pc = chord.root_pc

        base_oct = (self.reg_low // 12) + 1
        mot = self.motif_memory

        for i, interval in enumerate(mot):
            pc = (root_pc + interval) % 12
            oct_shift = 1 if i == 2 else 0
            pitch = note_number(pc, base_oct + oct_shift)
            pitch = int(_clamp(pitch, self.min_pitch, self.max_pitch))

            offset_beats = i * 0.75
            t_on = segment.start_tick + int(offset_beats * self.ppq)
            if t_on >= segment.end_tick:
                break

            dur = int(self.ppq * (1.2 if i == 0 else 0.9))
            vel = int(
                self.base_velocity
                + (energy - 0.5) * 20
                + random.randint(-self.humanize_amt, self.humanize_amt)
            )
            vel = int(_clamp(vel, 1, 127))

            notes.append(
                MelodyNote(
                    start_tick=t_on,
                    duration_ticks=dur,
                    pitch=pitch,
                    velocity=vel,
                    kind="main",
                )
            )

        if notes:
            self.cur_pitch = notes[-1].pitch

        return notes

    def _render_mantra(
        self,
        segment: Segment,
        chord: Chord,
        scale_pcs: List[int],
        energy: float,
    ) -> List[MelodyNote]:
        """
        Mantra:
        - Motif ngắn lặp đều, mỗi note cách nhau 2 phách.
        - Không lấp đầy toàn bộ segment → chừa khoảng trống cho hơi thở.
        """
        if not self.motif_memory or self.motif_counter % 2 == 0:
            self._new_motif_from_scale(scale_pcs)
        self.motif_counter += 1

        notes: List[MelodyNote] = []
        root_pc = chord.root_pc

        center_oct = (self.reg_low // 12) + 1
        step_ticks = int(self.ppq * 2.0)  # mỗi note cách 2 phách
        dur = int(self.ppq * 1.5)

        for i, interval in enumerate(self.motif_memory):
            pc = (root_pc + interval) % 12
            pitch = note_number(pc, center_oct)
            pitch = int(_clamp(pitch, self.min_pitch, self.max_pitch))

            t_on = segment.start_tick + i * step_ticks
            if t_on >= segment.end_tick:
                break

            vel = int(
                self.base_velocity
                + (energy - 0.5) * 15
                + random.randint(-self.humanize_amt, self.humanize_amt)
            )
            vel = int(_clamp(vel, 1, 127))

            notes.append(
                MelodyNote(
                    start_tick=t_on,
                    duration_ticks=dur,
                    pitch=pitch,
                    velocity=vel,
                    kind="main",
                )
            )

        if notes:
            self.cur_pitch = notes[-1].pitch

        return notes

    def _render_sparks(
        self,
        segment: Segment,
        chord: Chord,
        scale_pcs: List[int],
        energy: float,
    ) -> List[MelodyNote]:
        """
        Sparks:
        - Đôi khi tung 1 nốt rất cao, kéo dài.
        - Không có gì → im lặng (nhiều rest).
        """
        notes: List[MelodyNote] = []

        # 60% trường hợp → im lặng hoàn toàn
        if random.random() < 0.6:
            return notes

        weights = self._get_weighted_pool(chord, scale_pcs)
        pitch = self._choose_pitch_from_pool(weights, max(energy, 0.5))

        # Đẩy lên quãng cao
        while pitch < 84 and pitch + 12 <= self.max_pitch:
            pitch += 12

        # Nếu vượt quá register → bỏ
        if pitch < self.min_pitch or pitch > self.max_pitch:
            return notes

        t_on = segment.start_tick + random.randint(0, int(self.ppq * 2))
        if t_on >= segment.end_tick:
            return notes

        dur = int(segment.duration_ticks * 0.6)
        if dur <= 0:
            dur = int(self.ppq * 2)

        vel = int(
            self.base_velocity
            + (energy - 0.5) * 35
            + random.randint(-self.humanize_amt, self.humanize_amt)
        )
        vel = int(_clamp(vel, 1, 127))

        notes.append(
            MelodyNote(
                start_tick=t_on,
                duration_ticks=dur,
                pitch=pitch,
                velocity=vel,
                kind="main",
            )
        )

        self.cur_pitch = pitch
        return notes
