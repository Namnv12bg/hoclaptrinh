# Tệp: src/utils/math_utils.py
# (FINAL V10.1.0) - AUDIO MATH UTILITIES (UNIFIED)
# Gộp:
#   - frequency_utils.py (VÁ V9.7)  - Pitch Bend cho Solfeggio/Binaural
#   - solfeggio_utils.py (CỐT LÕI V8) - Neo Solfeggio Anchor
#
# Mục tiêu:
# - Gom toàn bộ toán học về tần số, pitch bend, neo solfeggio vào 1 nơi.
# - Các hàm & class giữ nguyên tên để không phá vỡ code hiện tại.

import math

# ============================================================
# 1. HẰNG SỐ & HÀM TỪ frequency_utils.py (VÁ V9.7)
# ============================================================

A4_FREQ = 440.0
A4_MIDI_NOTE = 69

# Dải Pitch Bend mặc định của Synths/MidiWriter (+/- 2 semitones = 200 cents)
PITCH_BEND_RANGE_CENTS = 200.0
MIDI_BEND_CENTER = 8192
MIDI_BEND_MAX = 16383
MIDI_BEND_MIN = 0
MIDI_BEND_RANGE_SEMI_DIR = (MIDI_BEND_MAX - MIDI_BEND_MIN) / 2.0  # ≈8191.5


def freq_to_midi_pitch_bend(
    frequency: float,
    return_cents: bool = False,
    pitch_bend_range_cents: float | None = None,
):
    """
    (V9.7) Chuyển đổi Hz sang nốt MIDI và Pitch Bend.

    - return_cents = True:
        Trả về (midi_note:int, cents_deviation:float) dùng cho Micro-Drift.
    - return_cents = False:
        Trả về (midi_note:int, pitch_bend_value:int 0..16383) dùng cho MIDI Writer.

    - pitch_bend_range_cents:
        Cho phép override dải bend (mặc định 200 cents = ±2 semitone).
        Nếu None → dùng PITCH_BEND_RANGE_CENTS.
    """
    # Fallback an toàn nếu tần số không hợp lệ
    if frequency <= 0:
        if return_cents:
            return 60, 0.0
        return 60, MIDI_BEND_CENTER  # center

    try:
        # 1. Tính toán "nốt MIDI float" (nốt lý tưởng)
        midi_note_float = A4_MIDI_NOTE + 12.0 * math.log2(frequency / A4_FREQ)
    except ValueError:
        if return_cents:
            return 60, 0.0
        return 60, MIDI_BEND_CENTER

    # 2. Làm tròn đến nốt MIDI (int) gần nhất
    midi_note_int = int(round(midi_note_float))
    midi_note_int = max(0, min(127, midi_note_int))

    # 3. Tính toán độ lệch (deviation) bằng "cents"
    deviation_semitones = midi_note_float - midi_note_int
    deviation_cents = deviation_semitones * 100.0

    # Trả về cents thô nếu Engine yêu cầu (cho micro-drift logic cộng dồn)
    if return_cents:
        return midi_note_int, deviation_cents

    # ---- PHẦN DƯỚI: TÍNH PITCH BEND 14-bit ----

    # Cho phép override dải bend; nếu không, dùng hằng số global
    pb_range = (
        float(pitch_bend_range_cents)
        if pitch_bend_range_cents is not None
        else PITCH_BEND_RANGE_CENTS
    )
    if pb_range <= 0:
        pb_range = PITCH_BEND_RANGE_CENTS or 200.0

    # Nếu lệch quá dải bend, ép vào biên
    if abs(deviation_cents) > pb_range:
        deviation_cents = max(-pb_range, min(pb_range, deviation_cents))

    bend_fraction = deviation_cents / pb_range if pb_range != 0 else 0.0

    bend_value_offset = bend_fraction * MIDI_BEND_RANGE_SEMI_DIR
    bend_value = MIDI_BEND_CENTER + int(bend_value_offset)
    bend_value = max(MIDI_BEND_MIN, min(MIDI_BEND_MAX, bend_value))

    return midi_note_int, bend_value


# ============================================================
# 2. CLASS TỪ solfeggio_utils.py (CỐT LÕI V8)
# ============================================================


class SolfeggioAnchor:
    """
    (V8) Class tính toán logic "Neo Solfeggio".
    Nó nhận tần số mục tiêu (Target) và tần số gốc (Base),
    sau đó tính toán tần số mới gần nhất theo quãng 8.

    Logic quan trọng: DRONE = HARM / 2
    (Lưu ý: V9.x đã đơn giản hóa logic này,
    nhưng class này vẫn hữu ích nếu cần dùng lại).
    """

    def __init__(self, f_target: float, f_harm_base: float):
        if not f_target or f_target <= 0:
            raise ValueError(f"Tan so muc tieu (F_target) khong hop le: {f_target}")
        if not f_harm_base or f_harm_base <= 0:
            raise ValueError(f"Tan so goc (F_harm_base) khong hop le: {f_harm_base}")

        self.f_target = float(f_target)
        self.f_harm_base = float(f_harm_base)

        self.n_oct_shift = self._calculate_octave_shift()
        self.f_harm_new = self.f_harm_base * (2.0 ** self.n_oct_shift)

        # DRONE = HARM / 2
        self.f_drone_new = self.f_harm_new / 2.0

    def _calculate_octave_shift(self) -> int:
        """
        Tính toán số quãng 8 (n_oct) cần dịch chuyển
        để f_harm_base * 2^n gần với f_target nhất.
        """
        ratio = self.f_target / self.f_harm_base

        try:
            distance_real = math.log2(ratio)
        except ValueError:
            raise ValueError(f"Loi tinh log2 cho ratio {ratio}")

        # Làm tròn đến số nguyên gần nhất
        n_oct_shift = round(distance_real)
        return int(n_oct_shift)
