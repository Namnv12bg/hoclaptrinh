# Tệp: src/core/safe_harmony_engine.py
# (BETA V10.11.0) - SAFE HARMONY ENGINE (ZEN HARMONY RULES)
#
# Vai trò:
#   - "Tầng luật hòa âm" đứng giữa StructureBuilder và HarmEngine.
#   - Nhìn vào:
#       + key / scale
#       + dãy Segment (chord_name, phase_name, section_type, energy…)
#     rồi:
#       + Giữ/giảm độ căng (tension) của từng hợp âm theo Zen Arc (Grounding/Immersion/Awakening/Integration).
#       + Làm mềm bước nhảy root quá gắt giữa 2 hợp âm liên tiếp.
#       + Đơn giản hóa các chord quá "acid" (dim/aug/7alt…) về vùng Zen-safe.
#
#   - Không sinh progression mới, không phá logic Zen Arc.
#   - Chỉ "chuẩn hóa" progression đã có để HarmEngine + SafetyFilter làm việc an toàn hơn.
#
# Tích hợp:
#   from src.core.safe_harmony_engine import SafeHarmonyEngine
#
#   safe_eng = SafeHarmonyEngine(user_options)
#   segments, decisions = safe_eng.apply_to_segments(
#       segments,
#       key=effective_key,    # nên là plan.new_key của TuningPlan
#       scale=scale_type,     # "major", "minor", ...
#   )
#
#   # Sau đó HarmEngine đọc seg.chord_name như bình thường.
#   # SafetyFilter vẫn là tầng cuối cùng ở mức note.

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple

from src.core.music_theory import NOTE_TO_PC
from src.core.structure_builder import Segment


class TensionLevel(int, Enum):
    """Thang đo "độ căng" của hợp âm (0 = hiền nhất)."""

    PURE_TRIAD = 0        # Triad đơn giản (C, Am, F…)
    GENTLE_COLOR = 1      # maj7, m7, add9, sus2, sus4, 6…
    RICH_COLOR = 2        # 9, 11, 13, maj9, m9 (không altered ác)
    HIGH_TENSION = 3      # dim, aug, altered, b9/#9/#11/b13…


@dataclass
class SafeHarmonyConfig:
    """
    Cấu hình chính cho SafeHarmonyEngine.

    - max_tension_by_phase:
        giới hạn tension cho từng phase_name (Grounding, Immersion, Awakening, Integration).
    - max_root_jump_semitones:
        khoảng nhảy root tối đa giữa 2 hợp âm liên tiếp trước khi bị làm mềm.
    - simplify_dim_aug:
        nếu True, sẽ cố gắng đơn giản hoá hợp âm dim/aug về hợp âm diatonic hiền hơn.
    """

    max_tension_by_phase: Dict[str, TensionLevel]
    max_root_jump_semitones: int = 9
    simplify_dim_aug: bool = True

    @classmethod
    def from_user_options(
        cls, user_options: Optional[Dict[str, Any]] = None
    ) -> "SafeHarmonyConfig":
        """
        Đọc cấu hình từ user_options["safe_harmony"], nếu có.

        Ví dụ trong user_options.yaml:

        safe_harmony:
          max_tension_by_phase:
            grounding: 1
            immersion: 2
            awakening: 2
            integration: 1
            default: 2
          max_root_jump_semitones: 9
          simplify_dim_aug: true
          debug: true
        """
        uo = user_options or {}
        sh = uo.get("safe_harmony", {}) or {}

        def phase_level(name: str, default: TensionLevel) -> TensionLevel:
            raw = sh.get("max_tension_by_phase", {}).get(name, None)
            if raw is None:
                return default
            try:
                iv = int(raw)
                if iv < 0:
                    iv = 0
                if iv > 3:
                    iv = 3
                return TensionLevel(iv)
            except Exception:
                return default

        max_tension_by_phase = {
            # Grounding / Integration: rất hiền
            "grounding": phase_level("grounding", TensionLevel.GENTLE_COLOR),
            "integration": phase_level("integration", TensionLevel.GENTLE_COLOR),
            # Immersion: có thể giàu màu hơn
            "immersion": phase_level("immersion", TensionLevel.RICH_COLOR),
            # Awakening: cho phép nhiều màu nhất trong nhạc thiền (nhưng vẫn tránh độ căng quá ác)
            "awakening": phase_level("awakening", TensionLevel.RICH_COLOR),
        }

        # Cho phép fallback theo phase_name bất kỳ khác
        default_phase_level = phase_level("default", TensionLevel.RICH_COLOR)

        cfg = cls(
            max_tension_by_phase=max_tension_by_phase,
            max_root_jump_semitones=int(sh.get("max_root_jump_semitones", 9) or 9),
            simplify_dim_aug=bool(sh.get("simplify_dim_aug", True)),
        )
        # Lưu luôn default để dùng khi phase lạ
        cfg.max_tension_by_phase.setdefault("__default__", default_phase_level)
        return cfg


@dataclass
class HarmonyDecision:
    """
    Kết quả đánh giá cho 1 Segment.

    - original_chord: chord ban đầu từ StructureBuilder.
    - safe_chord: chord sau khi SafeHarmonyEngine chỉnh (có thể giống original).
    - tension_level: mức độ căng ước lượng sau khi chỉnh.
    - softened_root_jump: có làm mềm bước nhảy root so với chord trước không.
    - simplified_quality: có đơn giản hóa chất lượng hợp âm (dim/aug/altered) không.
    """

    original_chord: str
    safe_chord: str
    tension_level: TensionLevel
    softened_root_jump: bool
    simplified_quality: bool


class SafeHarmonyEngine:
    """
    Safe Harmony Engine – tầng luật hòa âm thông minh (chỉ "làm hiền", không phá cấu trúc).

    Sử dụng:

        safe_eng = SafeHarmonyEngine(user_options)
        segments_safe, decisions = safe_eng.apply_to_segments(
            segments,
            key=effective_key,    # nên là plan.new_key của TuningPlan
            scale=scale_type,     # "major", "minor", ...
        )

    - Nếu in_place=True (mặc định):
        segment.chord_name sẽ bị cập nhật trực tiếp.
    - decisions: list HarmonyDecision để log / debug / phân tích thêm.
    """

    def __init__(self, user_options: Optional[Dict[str, Any]] = None):
        self.user_options = user_options or {}
        self.config = SafeHarmonyConfig.from_user_options(self.user_options)

        sh_conf = self.user_options.get("safe_harmony", {}) or {}
        self.debug = bool(sh_conf.get("debug", False))

    # ---------- PUBLIC API ----------

    def apply_to_segments(
        self,
        segments: List[Segment],
        key: str,
        scale: str,
        in_place: bool = True,
    ) -> Tuple[List[Segment], List[HarmonyDecision]]:
        """
        Áp dụng Safe Harmony lên list Segment.

        Args:
            segments: list Segment từ StructureBuilder.
            key: key hiệu lực (đã có thể là effective_key từ TuningPlan).
            scale: scale_type ("major", "minor", ionian, ...).
            in_place:
                True  -> sửa trực tiếp segment.chord_name.
                False -> dùng list copy (shallow).

        Returns:
            (segments_out, decisions)
        """
        if in_place:
            seg_out = segments
        else:
            seg_out = list(segments)

        decisions: List[HarmonyDecision] = []

        prev_chord_root_pc: Optional[int] = None

        for seg in seg_out:
            original = getattr(seg, "chord_name", None) or ""
            phase_name = (getattr(seg, "phase_name", "") or "").lower()
            section_type = (getattr(seg, "section_type", "") or "").lower()

            safe, decision = self._process_single_segment(
                original_chord=original,
                phase_name=phase_name,
                section_type=section_type,
                key=key,
                scale=scale,
                prev_root_pc=prev_chord_root_pc,
            )

            # Ghi lại vào segment nếu có thay đổi
            if safe != original and hasattr(seg, "chord_name"):
                seg.chord_name = safe

            # Cập nhật root pc cho segment này
            root_pc = self._guess_root_pc(safe) or self._guess_root_pc(original)
            if root_pc is not None:
                prev_chord_root_pc = root_pc

            decisions.append(decision)

        if self.debug:
            print(f"[SafeHarmony] Applied to {len(seg_out)} segments.")
            for i, d in enumerate(decisions):
                if (
                    d.original_chord != d.safe_chord
                    or d.softened_root_jump
                    or d.simplified_quality
                ):
                    print(
                        f"  Seg#{i:02d}: "
                        f"{d.original_chord} -> {d.safe_chord}, "
                        f"tension={d.tension_level}, "
                        f"soft_root_jump={d.softened_root_jump}, "
                        f"simplified={d.simplified_quality}"
                    )

        return seg_out, decisions

    # ---------- INTERNAL: SINGLE SEGMENT ----------

    def _process_single_segment(
        self,
        original_chord: str,
        phase_name: str,
        section_type: str,
        key: str,
        scale: str,
        prev_root_pc: Optional[int],
    ) -> Tuple[str, HarmonyDecision]:
        """
        Xử lý 1 chord (1 Segment).
        """
        chord = original_chord.strip() if original_chord else ""
        if not chord:
            decision = HarmonyDecision(
                original_chord=original_chord,
                safe_chord=original_chord,
                tension_level=TensionLevel.PURE_TRIAD,
                softened_root_jump=False,
                simplified_quality=False,
            )
            return original_chord, decision

        phase_key = phase_name or section_type or "__default__"
        level = self._get_max_tension_for_phase(phase_key)

        # 1) Ước lượng tension hiện tại
        current_level = self._estimate_tension_level(chord)

        simplified_quality = False
        safe_chord = chord

        # 2) Nếu chord đang quá căng so với phase -> simplify
        if current_level > level:
            safe_chord = self._simplify_chord_quality(chord, target_level=level)
            simplified_quality = safe_chord != chord
            current_level = self._estimate_tension_level(safe_chord)

        softened_root_jump = False
        # 3) Kiểm tra bước nhảy root
        root_pc = self._guess_root_pc(safe_chord)
        if prev_root_pc is not None and root_pc is not None:
            if self._is_root_jump_harsh(prev_root_pc, root_pc):
                # Nếu nhảy quá gắt và phase đang hiền -> cố gắng kéo về I/IV/V hoặc vi
                softened_root_jump = True
                safe_chord = self._soften_root_jump(
                    chord=safe_chord,
                    key=key,
                    scale=scale,
                    target_level=level,
                )
                current_level = self._estimate_tension_level(safe_chord)

        decision = HarmonyDecision(
            original_chord=original_chord,
            safe_chord=safe_chord,
            tension_level=current_level,
            softened_root_jump=softened_root_jump,
            simplified_quality=simplified_quality,
        )
        return safe_chord, decision

    # ---------- HELPERS: PHASE / TENSION ----------

    def _get_max_tension_for_phase(self, phase_name: str) -> TensionLevel:
        """
        Lấy mức tension tối đa cho phase.

        Mapping đơn giản:
        - chứa "ground"  -> grounding
        - chứa "integrat"-> integration
        - chứa "immersion" -> immersion
        - chứa "awaken"  -> awakening
        - khác -> "__default__"
        """
        p = (phase_name or "").lower().strip()
        if not p:
            return self.config.max_tension_by_phase.get(
                "__default__", TensionLevel.RICH_COLOR
            )

        if "ground" in p:
            k = "grounding"
        elif "integrat" in p:
            k = "integration"
        elif "immersion" in p:
            k = "immersion"
        elif "awaken" in p:
            k = "awakening"
        else:
            k = "__default__"

        return self.config.max_tension_by_phase.get(k, TensionLevel.RICH_COLOR)

    def _estimate_tension_level(self, chord_name: str) -> TensionLevel:
        """
        Heuristic đơn giản để đo "độ căng" từ chuỗi chord_name.

        - PURE_TRIAD: triad cơ bản (C, Cm, F, Gm, Am...)
        - GENTLE_COLOR: maj7, m7, 6, add9, sus2, sus4
        - RICH_COLOR: 9, 11, 13, maj9, m9 (không có b9/#9/#11/b13)
        - HIGH_TENSION: dim, aug, 7alt, có b9/#9/#11/b13...
        """
        s = chord_name.lower().replace(" ", "")

        # Dim / Aug / Altered → căng nhất
        altered_tokens = [
            "dim",
            "ø",
            "m7b5",
            "aug",
            "+",
            "7alt",
            "7#9",
            "7b9",
            "7#11",
            "7b13",
        ]
        if any(tok in s for tok in altered_tokens):
            return TensionLevel.HIGH_TENSION

        # Có b9/#9/#11/b13 trực tiếp
        very_tense = ["b9", "#9", "#11", "b13"]
        if any(tok in s for tok in very_tense):
            return TensionLevel.HIGH_TENSION

        # 9/11/13 "đẹp"
        rich_tokens = ["9", "11", "13"]
        if any(tok in s for tok in rich_tokens):
            return TensionLevel.RICH_COLOR

        # maj7, m7, 6, add9, sus2, sus4
        gentle_tokens = ["maj7", "m7", "6", "add9", "sus2", "sus4"]
        if any(tok in s for tok in gentle_tokens):
            return TensionLevel.GENTLE_COLOR

        # Nếu chỉ là triad, hoặc không nhận diện được -> coi là PURE_TRIAD
        return TensionLevel.PURE_TRIAD

    # ---------- HELPERS: QUALITY SIMPLIFIER ----------

    def _simplify_chord_quality(self, chord_name: str, target_level: TensionLevel) -> str:
        """
        Đơn giản hóa chord_name để không vượt quá target_level.

        Chiến lược:
        - Dim/Aug trước:
            + dim / m7b5 / ø -> m
            + aug / +        -> major
        - Nếu cần kéo xuống GENTLE_COLOR:
            + Bỏ bớt 9/11/13, giữ lại maj7/m7/add9 nếu có.
        - Nếu cần kéo xuống PURE_TRIAD:
            + Bỏ hết extension, giữ triad (C, Cm, G, Am...).
        """
        s = chord_name.strip()
        low = s.lower().replace(" ", "")

        # 1) Xử lý dim/aug trước nếu bật
        if self.config.simplify_dim_aug:
            if "dim" in low or "m7b5" in low or "ø" in low:
                # Cdim -> Cm
                root = self._extract_root_token(s)
                if root:
                    s = root + "m"
                    low = s.lower().replace(" ", "")
            elif "aug" in low or "+" in low:
                # Caug -> C
                root = self._extract_root_token(s)
                if root:
                    s = root
                    low = s.lower().replace(" ", "")

        # Nếu target là HIGH_TENSION hoặc hiện đã <= target -> không cần giảm
        current = self._estimate_tension_level(s)
        if current <= target_level or target_level == TensionLevel.HIGH_TENSION:
            return s

        # Hàm nhỏ để xiết xuống 1 level
        def drop_one_level(ch: str, lvl: TensionLevel) -> str:
            c = ch
            c_low = c.lower().replace(" ", "")

            # Nếu lvl <= GENTLE_COLOR -> bỏ các "màu" giàu trước
            if lvl <= TensionLevel.GENTLE_COLOR:
                # Bỏ 9/11/13
                for tok in ["13", "11", "9"]:
                    c_low = c_low.replace(tok, "")
                # Bỏ b9/#9/#11/b13 nếu vẫn còn
                for tok in ["b9", "#9", "#11", "b13"]:
                    c_low = c_low.replace(tok, "")
                c = c_low  # làm thô, vẫn chấp nhận

            # Nếu lvl <= PURE_TRIAD -> chỉ giữ root + (m) nếu có
            if lvl <= TensionLevel.PURE_TRIAD:
                root = self._extract_root_token(c)
                if not root:
                    return c  # không parse được thì thôi
                # Giữ "m" nếu ban đầu là minor
                is_minor = "m" in c_low and "maj" not in c_low
                return root + ("m" if is_minor else "")

            return c

        # Kéo dần xuống từng nấc
        out = s
        lvl = current
        while lvl > target_level:
            out = drop_one_level(out, lvl)
            lvl = self._estimate_tension_level(out)
            # safety break
            if lvl == current:
                break
            current = lvl

        return out

    # ---------- HELPERS: ROOT & ROOT JUMP ----------

    def _extract_root_token(self, chord_name: str) -> Optional[str]:
        """
        Tách root từ chuỗi chord_name đơn giản:
        - Lấy ký tự đầu [A-G], kèm theo #/b nếu có.
        - Ví dụ: "Cmaj7", "F#m7", "Eb9" -> "C", "F#", "Eb".
        """
        if not chord_name:
            return None
        s = chord_name.strip()
        if not s:
            return None
        first = s[0].upper()
        if first < "A" or first > "G":
            return None
        if len(s) >= 2 and s[1] in ("#", "b", "♯", "♭"):
            return first + s[1]
        return first

    def _guess_root_pc(self, chord_name: str) -> Optional[int]:
        root = self._extract_root_token(chord_name)
        if not root:
            return None
        # Chuẩn hóa root đôi chút
        r = root.upper().replace("♯", "#").replace("♭", "b")
        # NOTE_TO_PC thường không có "Db"/"Eb"... nếu vậy, map qua enharmonic đơn giản
        if r not in NOTE_TO_PC:
            if r == "DB":
                r = "C#"
            elif r == "EB":
                r = "D#"
            elif r == "GB":
                r = "F#"
            elif r == "AB":
                r = "G#"
            elif r == "BB":
                r = "A#"
        return NOTE_TO_PC.get(r)

    def _is_root_jump_harsh(self, prev_pc: int, curr_pc: int) -> bool:
        """
        Xác định xem bước nhảy root giữa 2 chord có "gắt" không.

        - Tính khoảng cách ngắn nhất trên vòng 12.
        - Nếu > max_root_jump_semitones -> coi là gắt.
        """
        d = abs(curr_pc - prev_pc) % 12
        if d > 6:
            d = 12 - d
        return d > self.config.max_root_jump_semitones

    def _soften_root_jump(
        self,
        chord: str,
        key: str,
        scale: str,
        target_level: TensionLevel,
    ) -> str:
        """
        Làm mềm bước nhảy root bằng cách kéo chord về một trong
        các "trụ" chính của key: I, IV, V, vi (đối với major), hoặc i, iv, v, VI (minor).

        Đây vẫn là tầng SAFE (không "ldo" quá mạnh):
        - Ưu tiên map về tonic (I / i) hoặc subdominant (IV / iv).
        - Nếu chord ban đầu có minor chất, có thể kéo về vi (ở major).
        """
        root = self._extract_root_token(chord)
        if not root:
            return self._simplify_chord_quality(chord, target_level)

        # Sử dụng bảng PC từ key gốc
        key_up = (key or "C").upper()
        if key_up not in NOTE_TO_PC:
            key_up = "C"
        tonic_pc = NOTE_TO_PC[key_up]

        # I, IV, V, vi (major) hoặc i, iv, v, VI (minor)
        diatonic_targets = self._build_simple_target_roots(tonic_pc, scale=scale)

        # Chọn target gần root hiện tại nhất
        current_pc = self._guess_root_pc(chord)
        if current_pc is None:
            return self._simplify_chord_quality(chord, target_level)

        best_root_pc = current_pc
        best_dist = 128
        for pc in diatonic_targets:
            d = abs(pc - current_pc) % 12
            if d > 6:
                d = 12 - d
            if d < best_dist:
                best_dist = d
                best_root_pc = pc

        # Map pitch class -> tên nốt đơn giản (C, D, E...)
        name = self._pc_to_simple_name(best_root_pc)

        if not name:
            return self._simplify_chord_quality(chord, target_level)

        # Nếu chord ban đầu có "m" và target cho phép, giữ minor flavor
        low = chord.lower().replace(" ", "")
        is_minor = ("m" in low) and ("maj" not in low)

        if target_level <= TensionLevel.PURE_TRIAD:
            # Triad thôi
            return name + ("m" if is_minor else "")

        # GENTLE_COLOR: cho phép maj7/m7
        if is_minor:
            return name + "m7"
        else:
            return name + "maj7"

    def _build_simple_target_roots(self, tonic_pc: int, scale: str) -> List[int]:
        """
        Trụ hòa âm đơn giản:
        - Major: I, IV, V, vi.
        - Minor: i, iv, v, VI (tạm map từ major song song).
        """
        scale_low = (scale or "major").lower()
        if "minor" in scale_low or "aeolian" in scale_low:
            # i, iv, v, VI (song song major)
            i = tonic_pc
            iv = (tonic_pc + 5) % 12
            v = (tonic_pc + 7) % 12
            VI = (tonic_pc + 8) % 12
            return [i, iv, v, VI]
        else:
            # Major: I, IV, V, vi
            I = tonic_pc
            IV = (tonic_pc + 5) % 12
            V = (tonic_pc + 7) % 12
            vi = (tonic_pc + 9) % 12
            return [I, IV, V, vi]

    def _pc_to_simple_name(self, pc: int) -> Optional[str]:
        """
        Map pitch class -> tên nốt đơn giản (ưu tiên không dấu nếu có thể).
        """
        # ưu tiên chữ đơn (C, D, E, F, G, A, B)
        for name, v in NOTE_TO_PC.items():
            if v == pc and len(name) == 1:
                return name
        # nếu không có, lấy bất kỳ tên nào khớp pc
        for name, v in NOTE_TO_PC.items():
            if v == pc:
                return name
        return None
