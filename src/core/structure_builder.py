# Tệp: src/core/structure_builder.py
# (BETA V10.11.0) - ZEN NARRATIVE ARC + SAFE KEY NORMALIZATION + PHASE TAGGING
#
# Features:
# - Zen Narrative Structure (Grounding -> Immersion -> Breakdown -> Awakening -> Integration)
# - Global Energy Curve gắn trực tiếp với ZenArcMatrix (base_energy + movement_bias)
# - Breath-based Segment Duration (1 Breath = 1 Unit * breath_cycle_bars)
# - Hỗ trợ đầy đủ Major family (major / ionian / mixolydian / lydian)
#   + Minor family (minor / dorian / aeolian / phrygian...)
# - SAFE: key được chuẩn hoá qua NOTE_TO_PC/PC_TO_NOTE
#
# PHASE 2+:
# - Zen Core đã có TuningCoreV3, truyền vào đây effective_key = tuning_plan.new_key.
# - StructureBuilder giữ API cũ, chỉ cần đảm bảo key hợp lệ với NOTE_TO_PC.
# - NEW: mỗi Segment được gắn:
#       + phase_name      (grounding/immersion/breakdown/awakening/integration)
#       + phase_index     (1..5)
#       + phase_energy    (từ ZenArcMatrix.base_energy)
#       + movement_hint   (0..1)
#       + stillness_hint  (0..1)
#       + is_breakdown    (bool)

from dataclasses import dataclass
from typing import List, Dict, Any, Sequence, Tuple, Union, Optional

from src.core.tempo_breath import TempoMap
from src.core.music_theory import NOTE_TO_PC, PC_TO_NOTE, parse_progression_string
from src.core.zen_arc_matrix import ZenArcMatrix, ZenPhaseDefinition


@dataclass
class Segment:
    start_tick: int
    end_tick: int
    duration_ticks: int
    chord_name: str
    label: str
    section_type: str
    energy_bias: float

    # NEW: Zen Arc tagging
    phase_name: str = "grounding"
    phase_index: int = 1
    phase_energy: float = 0.0

    # NEW: gợi ý cho ActivityMap / Engines
    movement_hint: float = 0.5       # 0 = rất tĩnh, 1 = rất động
    stillness_hint: float = 0.5      # thường = 1 - movement_hint
    is_breakdown: bool = False       # true nếu phase = "breakdown"


def _normalize_key_name(name: str) -> str:
    """
    Chuẩn hoá key về dạng mà NOTE_TO_PC hiểu được, ví dụ:
    - 'c'  -> 'C'
    - 'C#' -> 'C#'
    - 'B#' -> 'C', 'E#' -> 'F'
    Nếu không hợp lệ -> 'C'.
    """
    if not isinstance(name, str) or not name:
        return "C"

    raw = name.strip()
    if not raw:
        return "C"

    # Chuẩn hóa ký hiệu ♭/♯ về ASCII để dễ xử lý.
    sanitized = raw.replace("♭", "b").replace("♯", "#")

    # Lấy ký tự note và accidental (nếu có) mà không phá vỡ ký hiệu 'b'.
    letter = sanitized[0].upper()
    accidental = ""
    if len(sanitized) >= 2 and sanitized[1] in {"#", "b"}:
        accidental = sanitized[1]

    cand = f"{letter}{accidental}" if accidental else letter

    # Các trường hợp đặc biệt: B# = C, E# = F (giữ cho an toàn)
    if cand == "B#":
        cand = "C"
    elif cand == "E#":
        cand = "F"

    if cand in NOTE_TO_PC:
        return cand

    # Fallback: lấy pitch class gần nhất của ký tự đầu, nếu có
    pc = NOTE_TO_PC.get(letter, 0)
    return PC_TO_NOTE.get(pc, "C")


class StructureBuilder:
    """
    Xây dựng cấu trúc bài nhạc dựa trên Zen Narrative Arc + nhịp thở.

    - Không còn chỉ 4 giai đoạn (Grounding -> Immersion -> Awakening -> Integration),
      mà bây giờ mapping theo ZenArcMatrix 5 phase:
        1. grounding
        2. immersion
        3. breakdown
        4. awakening
        5. integration

    - Mỗi Segment biết:
        + chord_name (chuẩn hoá theo key + scale)
        + section_type (Intro/Verse/Chorus/Bridge/Outro/Zen)
        + energy_bias (SECTION_ENERGY * Zen Arc energy)
        + phase_name / phase_index / phase_energy
        + movement_hint / stillness_hint / is_breakdown
    """

    # Định nghĩa năng lượng cơ bản cho từng Section (0.0 -> 1.0)
    # Grounding: Nền móng (Thấp, Drone chủ đạo)
    # Immersion: Chìm sâu (Trung bình, Harm dày, Melody thưa)
    # Awakening: Tỉnh thức (Cao, Pulse rõ, Chime nhiều)
    # Integration: Hồi quy (Thấp dần, Fade out)
    SECTION_ENERGY: Dict[str, float] = {
        "Intro": 0.2,       # Grounding
        "Verse": 0.4,       # Immersion 1
        "Chorus": 0.65,     # Awakening
        "Bridge": 0.55,     # Immersion 2 / Transition
        "Outro": 0.15,      # Integration
        "Zen": 0.4,         # Neutral / Free-form
    }

    def __init__(
        self,
        key: str,
        scale: str,
        tempo_map: TempoMap,
        ppq: int,
        user_options: Dict[str, Any],
        zen_arc_matrix: Optional[ZenArcMatrix] = None,
    ):
        # PHASE 2: key đã là effective_key từ TuningCoreV3.new_key,
        # nhưng vẫn normalize thêm 1 lớp để an toàn.
        self.key = _normalize_key_name(key or "C")
        self.scale = (scale or "major").lower()
        self.tempo_map = tempo_map
        self.ppq = ppq
        self.user_options = user_options or {}

        # Zen Arc Matrix
        self.zen_arc: ZenArcMatrix = zen_arc_matrix or ZenArcMatrix(self.user_options)

        # Harmony mode để sau mở rộng (song_like / drone_like / zen_like / minimal...)
        self.harmony_mode = self.user_options.get("harmony_mode", "song_like")

        self.chord_map: Dict[str, str] = {}
        self._map_key_to_chords()

    # =========================
    # 1. CHORD MAPPING
    # =========================

    def _map_key_to_chords(self) -> None:
        """
        Map các bậc I, II, III... sang tên hợp âm cụ thể theo key + scale.
        Hỗ trợ đầy đủ Major family (major / ionian / mixolydian / lydian)
        và Minor family (minor / dorian / aeolian / phrygian...).
        """
        key_pc = NOTE_TO_PC.get(self.key, 0)

        def degree_note(interval_semitones: int) -> str:
            pc = (key_pc + interval_semitones) % 12
            return PC_TO_NOTE.get(pc, "C")

        # Major family
        if self.scale in ["major", "ionian", "mixolydian", "lydian"]:
            I = degree_note(0)
            II = degree_note(2)
            III = degree_note(4)
            IV = degree_note(5)
            V = degree_note(7)
            VI = degree_note(9)
            VII = degree_note(11)

            self.chord_map = {
                "Imaj7": f"{I}maj7",
                "Iadd9": f"{I}add9",
                "Isus2": f"{I}sus2",

                "IIm7": f"{II}m7",
                "IIIm7": f"{III}m7",

                "IVmaj7": f"{IV}maj7",
                "IVadd9": f"{IV}add9",
                "IVsus2": f"{IV}sus2",

                "V7": f"{V}dom7",
                "VIm7": f"{VI}m7",
                "VIIm7b5": f"{VII}m7b5",
            }
        else:
            # Minor family (minor, dorian, aeolian, phrygian...)
            I = degree_note(0)
            II = degree_note(2)
            III = degree_note(3)
            IV = degree_note(5)
            V = degree_note(7)
            VI = degree_note(8)
            VII = degree_note(10)

            self.chord_map = {
                "Im7": f"{I}m7",
                "Imadd9": f"{I}madd9",
                "Isus2": f"{I}sus2",

                "IIm7b5": f"{II}m7b5",
                "IIImaj7": f"{III}maj7",

                "IVm7": f"{IV}m7",
                "Vm7": f"{V}m7",

                "VImaj7": f"{VI}maj7",
                "VII7": f"{VII}dom7",
            }

    # =========================
    # 2. BUILD SEGMENTS
    # =========================

    def build_segments(self, total_seconds: int) -> List[Segment]:
        """
        Xây dựng danh sách Segment cho toàn bộ bài nhạc.

        - Đọc progression từ custom_chord_progression (nếu có).
          + Dùng parse_progression_string: hỗ trợ Roman / chord mix.
        - Nếu không, dùng progression fallback đơn giản theo scale.
        - Thời lượng mỗi hợp âm dựa trên số hơi thở (breaths_per_chord) và
          breath_cycle_bars của TempoMap.
        - Sau khi build xong:
          + Gắn Zen Arc phase cho từng Segment.
        """
        total_seconds = int(total_seconds or 0)
        total_ticks = self._seconds_to_ticks(total_seconds)
        if total_ticks <= 0:
            return []

        custom = self.user_options.get("custom_chord_progression")
        progression: Sequence[Union[str, Tuple[str, str]]] = []
        is_auto = False

        # 1. Thử parse kịch bản hợp âm custom
        if custom and str(custom).strip():
            try:
                progression = parse_progression_string(str(custom))
                is_auto = False
            except Exception as e:
                print(f"  [StructureBuilder] Parse progression lỗi: {e}")
                progression = []

        # 2. Nếu không có progression, dùng fallback
        if not progression:
            is_auto = True
            if self.scale in ["major", "ionian", "mixolydian", "lydian"]:
                # Major family fallback
                progression = [
                    ("Imaj7", "Verse"),
                    ("IVmaj7", "Verse"),
                ]
            else:
                # Minor family fallback
                progression = [
                    ("Im7", "Verse"),
                    ("IVm7", "Verse"),
                ]

        segments = self._build_from_progression(progression, total_ticks, is_auto)

        # 3. Áp dụng Zen Arc (Global Energy Curve + Phase Tagging)
        self._apply_zen_arc(segments, total_ticks)

        print(f"  > [StructureBuilder] Generated {len(segments)} segments with Zen Arc.")
        return segments

    def _build_from_progression(
        self,
        data: Sequence[Union[str, Tuple[str, str]]],
        total_ticks: int,
        is_auto: bool,
    ) -> List[Segment]:
        """
        Xây từng Segment từ progression:
        - Mỗi item: (ChordSymbol, SectionType) – ví dụ: ("Imaj7", "Verse").
        - Thời lượng: tính theo số hơi thở * breath_cycle_bars từ TempoMap.
        """
        segments: List[Segment] = []
        current_tick = 0

        # BIO-SYNC LOGIC: số hơi thở cho mỗi hợp âm
        # Auto progression: mặc định 4 breaths; Custom: mặc định 1 breath
        default_breaths = 4 if is_auto else 1

        raw_val = self.user_options.get(
            "breaths_per_chord",
            self.user_options.get("harmonic_pace_bars", default_breaths),
        )
        try:
            breaths = int(raw_val)
        except (TypeError, ValueError):
            breaths = default_breaths

        if breaths < 1:
            breaths = 1

        # TempoMap định nghĩa: 1 breath = cycle_bars bar (1 hoặc 2 bar)
        cycle_bars = float(getattr(self.tempo_map, "breath_cycle_bars", 1.0) or 1.0)

        # Số bar cho mỗi hợp âm
        bars_per_chord = float(breaths) * cycle_bars

        idx = 0
        data_len = len(data)
        if data_len == 0:
            return segments

        while current_tick < total_ticks:
            item = data[idx % data_len]

            # Hỗ trợ cả ("Imaj7","Verse") và "Cmaj7" thuần
            if isinstance(item, tuple):
                c_name, sec = item
            else:
                c_name, sec = item, "Verse"

            c_name = str(c_name).strip()
            if c_name in self.chord_map:
                c_name = self.chord_map[c_name]

            # Quy đổi bars -> ticks
            dur = self._bars_to_ticks(bars_per_chord)

            if current_tick + dur > total_ticks:
                dur = total_ticks - current_tick
            if dur <= 0:
                break

            base_energy = self.SECTION_ENERGY.get(sec, 0.5)

            segments.append(
                Segment(
                    start_tick=current_tick,
                    end_tick=current_tick + dur,
                    duration_ticks=dur,
                    chord_name=c_name,
                    label=f"{sec} {idx}",
                    section_type=sec,
                    energy_bias=base_energy,
                )
            )

            current_tick += dur
            idx += 1

        return segments

    # =========================
    # 3. ZEN ARC (GLOBAL ENERGY CURVE + PHASE TAGGING)
    # =========================

    def _apply_zen_arc(self, segments: List[Segment], total_ticks: int) -> None:
        """
        Gắn phase Zen Arc + cập nhật energy_bias cho từng segment.

        - Dùng center_tick của Segment để tính progress ratio 0..1.
        - Gọi ZenArcMatrix.get_phase_by_ratio(ratio) -> ZenPhaseDefinition.
        - Kết hợp:
            + SECTION_ENERGY (section_type)
            + phase_def.base_energy
          -> energy_bias cuối: trung bình có clamp 0..1.
        - Thiết lập:
            + seg.phase_name, seg.phase_index, seg.phase_energy
            + seg.movement_hint, seg.stillness_hint
            + seg.is_breakdown
        """
        if total_ticks <= 0 or not segments:
            return

        for seg in segments:
            center_tick = seg.start_tick + (seg.duration_ticks // 2)
            ratio = center_tick / float(total_ticks)
            ratio = max(0.0, min(1.0, ratio))

            # Lấy phase từ ZenArcMatrix
            phase_def: ZenPhaseDefinition = self.zen_arc.get_phase_by_ratio(ratio)

            seg.phase_name = phase_def.name
            seg.phase_index = phase_def.index
            seg.phase_energy = float(phase_def.base_energy)

            # Movement/stillness hint lấy từ phase.movement_bias
            mv = max(0.0, min(1.0, float(phase_def.movement_bias)))
            seg.movement_hint = mv
            seg.stillness_hint = max(0.0, min(1.0, 1.0 - mv))

            # Breakdown flag
            seg.is_breakdown = (phase_def.name == "breakdown")

            # Kết hợp energy:
            #   - base_section_energy: defines role (Intro/Verse/...)
            #   - phase_energy: defines global arc.
            base_section_energy = seg.energy_bias
            combined = 0.5 * base_section_energy + 0.5 * seg.phase_energy

            # Nhẹ nhàng boost chút khi Awakening, giảm nhẹ khi Breakdown nếu cần
            if phase_def.name == "awakening":
                combined *= 1.1
            elif phase_def.name == "breakdown":
                combined *= 0.7

            seg.energy_bias = max(0.1, min(1.0, combined))

    # =========================
    # 4. UTIL
    # =========================

    def _bars_to_ticks(self, bars: float) -> int:
        """
        Quy đổi số Bar (có thể là float) sang Tick.
        1 bar = 4 beat, 1 beat = ppq ticks.
        """
        return int(self.ppq * 4.0 * float(bars))

    def _seconds_to_ticks(self, seconds: int) -> int:
        """
        Quy đổi giây -> ticks, ưu tiên dùng TempoMap nếu có hàm hỗ trợ.
        """
        if seconds <= 0:
            return 0

        # Nếu TempoMap có method get_ticks_for_duration -> dùng luôn
        if hasattr(self.tempo_map, "get_ticks_for_duration"):
            try:
                return int(self.tempo_map.get_ticks_for_duration(seconds))  # type: ignore
            except Exception:
                pass

        # Fallback: tính tay từ tempo cơ bản
        bpm = float(getattr(self.tempo_map, "base_tempo", 60.0) or 60.0)
        # 1 phút = 60s, bpm = beat/phút -> seconds -> số beat
        beats = (seconds * bpm) / 60.0
        return int(beats * self.ppq)
