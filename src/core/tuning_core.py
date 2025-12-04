from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

# =========================
# 1. MUSIC THEORY HELPERS
# =========================

try:  # pragma: no cover
    from src.core.music_theory import NOTE_TO_PC, midi_to_hz, note_number
except Exception:  # pragma: no cover
    # Fallback mềm để file có thể import độc lập (ví dụ khi chạy test đơn lẻ)
    NOTE_TO_PC = {
        "C": 0,
        "C#": 1,
        "Db": 1,
        "D": 2,
        "D#": 3,
        "Eb": 3,
        "E": 4,
        "F": 5,
        "F#": 6,
        "Gb": 6,
        "G": 7,
        "G#": 8,
        "Ab": 8,
        "A": 9,
        "A#": 10,
        "Bb": 10,
        "B": 11,
    }

    def midi_to_hz(midi: int, a4_hz: float = 440.0) -> float:
        return float(a4_hz) * (2.0 ** ((int(midi) - 69) / 12.0))

    def note_number(pc: int, octave: int) -> int:
        return int(pc + 12 * octave)

# =========================
# 2. DATA CLASS: TuningPlan
# =========================


@dataclass
class TuningPlan:
    """
    Gói toàn bộ thông tin tuning cho một track / bản nhạc.

    - mode:
        "pure_key" / "solf_root" / "solf_dual" / "key_plus_solf_drone"
    - base_key:
        Key do user chọn (C, D, ...).
    - new_key:
        V11: bằng base_key (KHÔNG đổi). Sau này có thể khác trong phase audio.
    - scale:
        "major", "dorian", ...

    Tần số tham chiếu:
        - ref_a_hz: A4 reference (thường 440.0).
        - primary_solf_hz / secondary_solf_hz: tần số Solf nếu có.

    Drone:
        - primary_drone_midi  : nốt MIDI anchor cho drone chính.
        - secondary_drone_midi: nốt MIDI anchor cho drone phụ (nếu solf_dual).

    Global tuning (CHỈ KẾ HOẠCH, KHÔNG ÁP DỤNG MIDI V11):
        - global_ratio_planned:
              ratio dự kiến để audio renderer nhân.
        - global_semitone_shift_planned:
              số semitone tương đương với ratio.
        - register_shift:
              gợi ý dịch register cho RegisterManager (thường 0).

    meta:
        Thông tin bổ sung, để QA dễ debug.
    """

    mode: str
    base_key: str
    new_key: str
    scale: str

    ref_a_hz: float = 440.0

    primary_solf_hz: Optional[float] = None
    secondary_solf_hz: Optional[float] = None

    primary_drone_midi: Optional[int] = None
    secondary_drone_midi: Optional[int] = None

    global_ratio_planned: float = 1.0
    global_semitone_shift_planned: float = 0.0

    register_shift: int = 0

    meta: Dict[str, Any] = field(default_factory=dict)

    # --- API cho RegisterManager (đã xuất hiện trong stub trong tài liệu) ---
    def register_shift_semitones(self) -> int:
        """
        Trả về số semitone gợi ý để dịch register.

        V11 (Phase 1): thường = 0 để không phá behavior cũ.
        Sau này nếu bật global shift, có thể dùng để kéo register xuống khi pitch lên, v.v.
        """
        return int(self.register_shift)

# =========================
# 3. TuningCoreV3
# =========================


class TuningCoreV3:
    """
    TuningCoreV3: xây dựng TuningPlan từ user_options + preset.

    Expectation về dữ liệu:

        user_options (dict) & preset (dict) có thể chứa:
            - "key"                 : "C", "D", ...
            - "scale"               : "major", "ionian", ...
            - "drone_mode"          : "pure_key" / "solf_root" / "solf_dual" /
                                      "key_plus_solf_drone"
            - "solf_profile"        : float (vd 528.0) hoặc list[float] [396.0, 528.0]
            - "ref_a_hz"            : 440.0 (nếu không set mặc định 440.0)

        Có thể thêm block nested:

            user_options["tuning_core"] = {
                "drone_mode": ...,
                "solf_profile": ...,
                "ref_a_hz": 432.0,
                "register_shift_override": 0,
                "enable_global_shift": False,
            }

    Quy tắc ưu tiên:
        1) user_options["tuning_core"][field] nếu có.
        2) user_options[field] (flat).
        3) preset[field].
        4) default.

    V11:
        - build_plan() KHÔNG áp dụng global pitch.
        - Chỉ tính toán và ghi chú planned_ratio, planned_semitone_shift.
    """

    def __init__(self, user_options: Optional[Dict[str, Any]] = None,
                 preset: Optional[Dict[str, Any]] = None) -> None:
        self.user_options: Dict[str, Any] = user_options or {}
        self.preset: Dict[str, Any] = preset or {}

        self._tc_cfg: Dict[str, Any] = self.user_options.get("tuning_core", {}) or {}

    # -----------------------
    # Helper: lấy giá trị với ưu tiên
    # -----------------------
    def _get_cfg(self, key: str, default: Any = None) -> Any:
        if key in self._tc_cfg:
            return self._tc_cfg.get(key, default)
        if key in self.user_options:
            return self.user_options.get(key, default)
        if key in self.preset:
            return self.preset.get(key, default)
        return default

    # -----------------------
    # Helper: chuẩn hóa mode
    # -----------------------
    @staticmethod
    def _normalize_mode(mode: Any) -> str:
        if not mode:
            return "pure_key"
        m = str(mode).strip().lower()
        if m in ("pure", "key", "pure-key", "pure_key"):
            return "pure_key"
        if m in ("solf", "solf_root", "solf-root", "follow_solf"):
            return "solf_root"
        if m in ("solf_dual", "dual_solf", "solf-dual"):
            return "solf_dual"
        if m in ("key_plus_solf_drone", "key+solf_drone", "key_solf_drone"):
            return "key_plus_solf_drone"
        # fallback an toàn
        return "pure_key"

    # -----------------------
    # Helper: chuẩn hóa key
    # -----------------------
    @staticmethod
    def _normalize_key(key: Any) -> str:
        if not key:
            return "C"
        k = str(key).strip().upper()
        # Chỉ cho phép các key hợp lệ
        valid = ["C", "C#", "DB", "D", "D#", "EB", "E", "F", "F#", "GB",
                 "G", "G#", "AB", "A", "A#", "BB", "B"]
        if k not in valid:
            return "C"
        # Chuẩn hoá enharmonic về dạng có sẵn trong NOTE_TO_PC nếu cần
        if k == "DB":
            return "C#"
        if k == "EB":
            return "D#"
        if k == "GB":
            return "F#"
        if k == "AB":
            return "G#"
        if k == "BB":
            return "A#"
        return k

    # -----------------------
    # Helper: chuẩn hóa scale
    # -----------------------
    @staticmethod
    def _normalize_scale(scale: Any) -> str:
        if not scale:
            return "major"
        s = str(scale).strip().lower()
        # Một số alias
        if s in ("ionian", "maj", "major"):
            return "major"
        return s

    # -----------------------
    # Helper: parse solf_profile
    # -----------------------
    @staticmethod
    def _parse_solf_profile(raw: Any) -> Tuple[Optional[float], Optional[float]]:
        """
        Chuyển solf_profile về (primary, secondary).

        raw có thể là:
            - float/int: 528.0
            - list/tuple: [396.0, 528.0]
            - dict: {"primary": 396.0, "secondary": 528.0}
        """
        if raw is None:
            return None, None

        # Đơn float
        if isinstance(raw, (int, float)):
            val = float(raw)
            return (val if val > 0 else None), None

        # list/tuple
        if isinstance(raw, (list, tuple)) and raw:
            vals = [float(v) for v in raw if isinstance(v, (int, float))]
            if not vals:
                return None, None
            if len(vals) == 1:
                return (vals[0] if vals[0] > 0 else None), None
            return (
                vals[0] if vals[0] > 0 else None,
                vals[1] if vals[1] > 0 else None,
            )

        # dict
        if isinstance(raw, dict):
            p = raw.get("primary")
            s = raw.get("secondary")
            p_f = float(p) if isinstance(p, (int, float)) and p > 0 else None
            s_f = float(s) if isinstance(s, (int, float)) and s > 0 else None
            return p_f, s_f

        # fallback
        return None, None

    # -----------------------
    # Helper: nearest MIDI cho 1 tần số
    # -----------------------
    @staticmethod
    def _nearest_midi_from_freq(freq_hz: float, ref_a_hz: float) -> int:
        """
        Tìm nốt MIDI gần nhất với freq_hz, dựa vào A4 = ref_a_hz.

        Công thức:
            n = 69 + 12 * log2(freq / ref_a_hz)
        """
        if freq_hz <= 0:
            return 69  # fallback A4
        n = 69 + 12.0 * math.log2(freq_hz / float(ref_a_hz))
        midi = int(round(n))
        return max(0, min(127, midi))

    # -----------------------
    # Helper: key -> pitch class
    # -----------------------
    @staticmethod
    def _pc_from_key(key: str) -> int:
        k = TuningCoreV3._normalize_key(key)
        return int(NOTE_TO_PC.get(k, 0))

    # -----------------------
    # Helper: tạo drone MIDI từ Solf (gợi ý C2/B2 quanh đó)
    # -----------------------
    def _suggest_drone_midi_from_solf(self, solf_hz: float,
                                      ref_a_hz: float) -> int:
        """
        Đưa ra gợi ý nốt MIDI cho drone dựa trên solf_hz.

        Chiến lược:
            - Tìm MIDI gần nhất với solf_hz.
            - Nếu nốt đó quá cao (> C5), cố gắng trừ 12 semitone xuống.
            - Mục tiêu: C2–C4: vùng hợp lý cho drone nền.
        """
        base_m = self._nearest_midi_from_freq(solf_hz, ref_a_hz)
        # Nếu quá cao, hạ xuống 1–2 octave
        while base_m > 72:  # > C5
            base_m -= 12
        # Nếu quá thấp, nâng lên octave
        while base_m < 36:  # < C2
            base_m += 12
        return max(0, min(127, base_m))

    # -----------------------
    # Helper: tính ratio dự kiến
    # -----------------------
    @staticmethod
    def _compute_planned_ratio(target_hz: float,
                               midi_anchor: int,
                               ref_a_hz: float) -> Tuple[float, float]:
        """
        Tính ratio dự kiến & semitone shift tương ứng nếu muốn
        kéo nốt midi_anchor (equal temperament) về target_hz.

        V11: CHỈ LƯU TRONG PLAN, KHÔNG ÁP DỤNG MIDI.

        Trả về:
            (ratio, semitone_shift)
        """
        if target_hz <= 0:
            return 1.0, 0.0
        equal = midi_to_hz(midi_anchor, ref_a_hz)
        if equal <= 0:
            return 1.0, 0.0
        ratio = float(target_hz) / float(equal)
        # 12 * log2(ratio) = số semitone
        semis = 12.0 * math.log2(ratio)
        return ratio, semis

    # =========================
    # 4. BUILD PLAN
    # =========================

    def build_plan(self) -> TuningPlan:
        """
        Tạo TuningPlan từ user_options + preset.

        V11 (Phase 1):
            - new_key = base_key (KHÔNG đổi).
            - register_shift = 0 (trừ khi có override).
            - global_ratio_planned / semitone_shift_planned chỉ để DEBUG/AUDIO.
        """
        # --- Base key & scale ---
        base_key_raw = self._get_cfg("key", "C")
        base_key = self._normalize_key(base_key_raw)

        scale_raw = self._get_cfg("scale", "major")
        scale = self._normalize_scale(scale_raw)

        # --- Mode & Solf profile ---
        mode_raw = self._get_cfg("drone_mode", "pure_key")
        mode = self._normalize_mode(mode_raw)

        solf_raw = self._get_cfg("solf_profile", None)
        primary_solf, secondary_solf = self._parse_solf_profile(solf_raw)

        # --- Ref A4 ---
        ref_a = float(self._get_cfg("ref_a_hz", 440.0) or 440.0)

        # --- Register shift override ---
        reg_shift_override = self._get_cfg("register_shift_override", None)
        if isinstance(reg_shift_override, (int, float)):
            register_shift = int(reg_shift_override)
        else:
            register_shift = 0  # Phase 1: không tự dịch

        # --- Global shift flag (Phase 1: tắt mặc định) ---
        enable_global_shift = bool(self._get_cfg("enable_global_shift", False))

        # --- base/new key: V11 giữ nguyên ---
        new_key = base_key

        # --- Tạo plan rỗng trước ---
        plan = TuningPlan(
            mode=mode,
            base_key=base_key,
            new_key=new_key,
            scale=scale,
            ref_a_hz=ref_a,
            primary_solf_hz=None,
            secondary_solf_hz=None,
            primary_drone_midi=None,
            secondary_drone_midi=None,
            global_ratio_planned=1.0,
            global_semitone_shift_planned=0.0,
            register_shift=register_shift,
            meta={},
        )

        # ---------- MODE 1: PURE KEY ----------
        if mode == "pure_key":
            # Không dùng Solf, nhạc chạy theo key/scale chuẩn.
            plan.meta["description"] = (
                "PURE KEY: không dùng Solf, không global pitch; "
                "mọi engine chạy theo key/scale chuẩn."
            )
            return plan

        # ---------- MODE 2: SOLF ROOT ----------
        if mode == "solf_root":
            plan.primary_solf_hz = primary_solf
            plan.secondary_solf_hz = None

            if primary_solf and primary_solf > 0:
                drone_midi = self._suggest_drone_midi_from_solf(primary_solf, ref_a)
                plan.primary_drone_midi = drone_midi

                ratio, semis = self._compute_planned_ratio(primary_solf,
                                                           drone_midi,
                                                           ref_a)
                plan.global_ratio_planned = ratio
                plan.global_semitone_shift_planned = semis

                plan.meta["description"] = (
                    "SOLF ROOT: dùng một tần số Solf làm drone chính; "
                    "V11 KHÔNG áp dụng global pitch – ratio/semis chỉ để audio renderer dùng sau."
                )
            else:
                plan.meta["description"] = (
                    "SOLF ROOT: không tìm thấy primary_solf_hz hợp lệ; "
                    "fallback như PURE KEY."
                )

            if not enable_global_shift:
                # Phase 1: đảm bảo pipeline MIDI không bị ảnh hưởng
                plan.global_ratio_planned = 1.0
                plan.global_semitone_shift_planned = 0.0
                plan.meta["global_shift_applied"] = False
            else:
                plan.meta["global_shift_applied"] = True

            return plan

        # ---------- MODE 3: SOLF DUAL ----------
        if mode == "solf_dual":
            plan.primary_solf_hz = primary_solf
            plan.secondary_solf_hz = secondary_solf

            if primary_solf and primary_solf > 0:
                d1 = self._suggest_drone_midi_from_solf(primary_solf, ref_a)
                plan.primary_drone_midi = d1
                ratio1, semis1 = self._compute_planned_ratio(primary_solf,
                                                             d1,
                                                             ref_a)
            else:
                d1, ratio1, semis1 = None, 1.0, 0.0

            if secondary_solf and secondary_solf > 0:
                d2 = self._suggest_drone_midi_from_solf(secondary_solf, ref_a)
                plan.secondary_drone_midi = d2
                ratio2, semis2 = self._compute_planned_ratio(secondary_solf,
                                                             d2,
                                                             ref_a)
            else:
                d2, ratio2, semis2 = None, 1.0, 0.0

            # Gợi ý: dùng ratio của primary làm global (nếu bật).
            plan.global_ratio_planned = ratio1
            plan.global_semitone_shift_planned = semis1

            plan.meta["description"] = (
                "SOLF DUAL: hai tần số Solf (primary/secondary) dùng cho drone/texture; "
                "V11 KHÔNG áp dụng global pitch – ratio chỉ để tham khảo."
            )
            plan.meta["secondary_ratio_planned"] = ratio2
            plan.meta["secondary_semitone_shift_planned"] = semis2

            if not enable_global_shift:
                plan.global_ratio_planned = 1.0
                plan.global_semitone_shift_planned = 0.0
                plan.meta["global_shift_applied"] = False
            else:
                plan.meta["global_shift_applied"] = True

            return plan

        # ---------- MODE 4: KEY + SOLF DRONE ----------
        if mode == "key_plus_solf_drone":
            plan.primary_solf_hz = primary_solf
            plan.secondary_solf_hz = None

            if primary_solf and primary_solf > 0:
                d = self._suggest_drone_midi_from_solf(primary_solf, ref_a)
                plan.primary_drone_midi = d
                r, s = self._compute_planned_ratio(primary_solf, d, ref_a)
                plan.global_ratio_planned = r
                plan.global_semitone_shift_planned = s
                plan.meta["description"] = (
                    "KEY + SOLF DRONE: nhạc chạy theo key chuẩn, Solf dùng như drone độc lập; "
                    "V11 không pitch toàn bài."
                )
            else:
                plan.meta["description"] = (
                    "KEY + SOLF DRONE: thiếu primary_solf_hz; "
                    "hành vi gần như PURE KEY."
                )

            if not enable_global_shift:
                plan.global_ratio_planned = 1.0
                plan.global_semitone_shift_planned = 0.0
                plan.meta["global_shift_applied"] = False
            else:
                plan.meta["global_shift_applied"] = True

            return plan

        # ---------- FALLBACK: mode không hợp lệ ----------
        plan.meta["description"] = (
            f"Unknown drone_mode='{mode_raw}', fallback về PURE KEY behavior."
        )
        return plan

# =========================
# 5. Convenience API
# =========================


def build_tuning_plan(user_options: Optional[Dict[str, Any]] = None,
                      preset: Optional[Dict[str, Any]] = None) -> TuningPlan:
    """
    Helper nhanh cho Zen Core:

        from src.core.tuning_core import build_tuning_plan

        plan = build_tuning_plan(user_options, preset)
    """
    core = TuningCoreV3(user_options, preset)
    return core.build_plan()
