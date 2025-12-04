from __future__ import annotations

import random
from typing import Any, List, Optional

# CC Expression tiêu chuẩn (thường dùng cho "hơi thở")
CC_EXPRESSION = 11

# --- Fallback import an toàn để tránh vòng lặp / lỗi môi trường ---

try:
    from src.core.tempo_breath import TempoMap  # type: ignore
except Exception:  # pragma: no cover
    class TempoMap:  # type: ignore
        # Fallback tối thiểu để beat_stress không crash
        ticks_per_beat: int = 480
        pass

try:
    from src.utils.midi_writer import MidiTrack  # type: ignore
except Exception:  # pragma: no cover
    class MidiTrack:  # type: ignore
        def add_cc(self, *args, **kwargs):
            pass

# Kiến trúc mới: ActivityMap nằm trong src/utils/activity
try:
    from src.utils.activity_map import ActivityMap  # type: ignore
except Exception:  # pragma: no cover
    class ActivityMap:  # type: ignore
        pass

__all__ = [
    "CC_EXPRESSION",
    "clamp_velocity",
    "apply_beat_stress_to_velocity",
    "apply_beat_stress_to_note",
    "write_breath_arc",
    "is_ghost_note",
    "clamp_ghost_velocity",
    "apply_pulse_activity_trim",
    "is_sustained_wind_instrument",
    "enhance_melody_note",
]

# =========================
# 1. Helper chung
# =========================

def clamp_velocity(v: int) -> int:
    """
    Kẹp velocity vào dải an toàn 1..127.
    """
    if v < 1:
        return 1
    if v > 127:
        return 127
    return int(v)

# =========================
# 2. Beat Stress + Humanize
# =========================

def apply_beat_stress_to_velocity(
    velocity: int,
    start_tick: int,
    tempo_map: Optional[TempoMap] = None,
    ppq: int = 480,
    enable_beat_stress: bool = True,
    humanize_range: int = 0,
) -> int:
    """
    Áp dụng Beat Stress + Humanize đơn giản dựa trên vị trí phách.

    Logic (4/4):
    - Phách 1 (0.0–0.25): boost mạnh.
    - Phách 2 (0.25–0.5): giảm nhẹ.
    - Phách 3 (0.5–0.75): boost vừa.
    - Phách 4 (0.75–1.0): giảm nhẹ.

    humanize_range: biên độ random +/- cho velocity.
    """
    v = int(velocity)

    # Nếu tắt beat stress + không cần humanize → trả về luôn cho nhanh
    if not enable_beat_stress and humanize_range <= 0:
        return clamp_velocity(v)

    # Tính vị trí phách (beat_pos: 0.0..1.0 trong ô nhịp 4/4)
    beat_pos = 0.0

    try:
        if tempo_map is not None and hasattr(tempo_map, "ticks_per_beat"):
            ticks_per_beat = getattr(tempo_map, "ticks_per_beat", 0) or (ppq or 480)
        else:
            ticks_per_beat = ppq or 480

        if ticks_per_beat <= 0:
            ticks_per_beat = 480

        beat_index = (start_tick // ticks_per_beat) % 4
        beat_pos = beat_index / 4.0
    except Exception:
        beat_pos = 0.0

    # Beat stress cơ bản
    if enable_beat_stress:
        strong_boost = 10
        weak_cut = 5

        if beat_pos < 0.25:
            # Phách 1
            v += strong_boost
        elif 0.25 <= beat_pos < 0.5:
            # Phách 2
            v -= weak_cut
        elif 0.5 <= beat_pos < 0.75:
            # Phách 3
            v += int(strong_boost * 0.6)
        else:
            # Phách 4
            v -= int(weak_cut * 0.5)

    # Humanize velocity một chút
    if humanize_range > 0:
        v += random.randint(-humanize_range, humanize_range)

    return clamp_velocity(v)

def apply_beat_stress_to_note(
    note: Any,
    tempo_map: Optional[TempoMap],
    ppq: int,
    enable_beat_stress: bool = True,
    humanize_range: int = 0,
) -> Any:
    """
    Áp dụng Beat Stress + Humanize lên một object note (MelodyNote / PulseNote).

    Yêu cầu note có:
    - .start_tick
    - .velocity
    """
    if not hasattr(note, "velocity") or not hasattr(note, "start_tick"):
        return note

    try:
        v = int(getattr(note, "velocity", 80))
        start_tick = int(getattr(note, "start_tick", 0))
    except Exception:
        return note

    new_v = apply_beat_stress_to_velocity(
        velocity=v,
        start_tick=start_tick,
        tempo_map=tempo_map,
        ppq=ppq,
        enable_beat_stress=enable_beat_stress,
        humanize_range=humanize_range,
    )
    note.velocity = new_v
    return note

# =========================
# 3. Breath Arc (CC11)
# =========================

def write_breath_arc(
    track: MidiTrack,
    start_tick: int,
    duration_ticks: int,
    master_intensity: float = 0.7,
    steps: int = 4,
    cc: int = CC_EXPRESSION,
    pattern: Optional[str] = None,
) -> None:
    """
    Vẽ "hơi thở" bằng CC11 trên track:

    - pattern="inhale_exhale": lên rồi xuống (mặc định, mềm).
    - pattern="swell": swell lên mạnh rồi giữ.
    - pattern="fade": từ to → nhỏ dần.

    Chỉ dùng cho nốt đủ dài (duration_ticks > steps).
    """
    try:
        start_tick = int(start_tick)
        duration_ticks = int(duration_ticks)
    except Exception:
        return

    if duration_ticks <= steps or steps <= 1:
        return

    # Base range CC
    master_intensity = max(0.0, min(1.0, float(master_intensity)))
    min_cc = 40
    max_cc = int(40 + (60 * master_intensity))  # tối đa ~100

    # Số tick giữa các điểm CC
    ticks_per_step = max(1, duration_ticks // steps)

    # Chọn pattern
    pattern = pattern or "inhale_exhale"
    values: List[int] = []

    if pattern == "swell":
        # 0 → 1 → 1 → 1 ...
        for i in range(steps):
            t = i / (steps - 1)
            if t < 0.3:
                k = t / 0.3
            else:
                k = 1.0
            val = int(min_cc + (max_cc - min_cc) * k)
            values.append(val)
    elif pattern == "fade":
        # 1 → 0
        for i in range(steps):
            t = i / (steps - 1)
            k = 1.0 - t
            val = int(min_cc + (max_cc - min_cc) * k)
            values.append(val)
    else:
        # inhale_exhale: 0 → 1 → 0 (mềm)
        for i in range(steps):
            t = i / (steps - 1)
            if t <= 0.5:
                # lên
                k = t / 0.5
            else:
                # xuống
                k = (1.0 - t) / 0.5
            k = max(0.0, min(1.0, k))
            val = int(min_cc + (max_cc - min_cc) * k)
            values.append(val)

    # Ghi CC
    for idx, val in enumerate(values):
        tick = start_tick + idx * ticks_per_step
        track.add_cc(tick=tick, control=cc, value=val)

# =========================
# 4. Ghost Notes
# =========================

def is_ghost_note(note: Any) -> bool:
    """
    Xác định nốt có phải Ghost Note không.

    Quy ước:
    - Nếu note.kind == "ghost" → Ghost.
    - Nếu không có attribute kind → coi là nốt thường.
    """
    kind = getattr(note, "kind", "main")
    return str(kind).lower() == "ghost"

def clamp_ghost_velocity(
    note: Any,
    ghost_ratio: float = 0.6,
    min_velocity: int = 20,
) -> Any:
    """
    Giảm velocity cho Ghost Note:

    - ghost_ratio: tỉ lệ so với velocity gốc (mặc định 60%).
    - min_velocity: sàn tối thiểu để Ghost vẫn nghe được.
    """
    if not hasattr(note, "velocity"):
        return note

    try:
        v = int(note.velocity)
    except Exception:
        return note

    ghost_ratio = max(0.0, min(1.0, float(ghost_ratio)))
    new_v = int(v * ghost_ratio)
    if new_v < min_velocity:
        new_v = min_velocity

    note.velocity = clamp_velocity(new_v)
    return note

# =========================
# 5. Pulse Awareness (ActivityMap)
# =========================

def apply_pulse_activity_trim(
    pulse_notes: List[Any],
    activity_map: Optional[ActivityMap],
    pulse_activity_threshold: float = 0.7,
    pulse_reduction_ratio: float = 0.6,
    melody_track_name: str = "MELODY",
) -> List[Any]:
    """
    Pulse nhường nhịn Melody: giảm velocity Pulse khi Melody đang hoạt động mạnh.

    Thiết kế "an toàn":
    - Nếu không có ActivityMap hoặc không tìm thấy API phù hợp → trả về nguyên list.
    - Nếu có, sẽ cố gắng gọi activity_map.get_energy_at_tick(track_name, tick).
      + Nếu energy >= threshold → giảm velocity theo pulse_reduction_ratio.

    Điều này giữ đúng tinh thần "Pulse Awareness" nhưng không gây lỗi nếu API đổi.
    """
    if not pulse_notes or activity_map is None:
        return pulse_notes

    # Tìm hàm energy phù hợp trên ActivityMap (tên API có thể thay đổi).
    get_energy = None
    if hasattr(activity_map, "get_energy_at_tick"):
        get_energy = getattr(activity_map, "get_energy_at_tick")
    elif hasattr(activity_map, "get_track_energy"):
        get_energy = getattr(activity_map, "get_track_energy")
    elif hasattr(activity_map, "get_activity_at_tick"):
        get_energy = getattr(activity_map, "get_activity_at_tick")

    if not callable(get_energy):
        # Không có API rõ ràng → không đụng
        return pulse_notes

    pulse_reduction_ratio = max(0.0, min(1.0, float(pulse_reduction_ratio)))
    threshold = max(0.0, min(1.0, float(pulse_activity_threshold)))

    for n in pulse_notes:
        if not hasattr(n, "start_tick") or not hasattr(n, "velocity"):
            continue

        try:
            tick = int(getattr(n, "start_tick", 0))
            energy = float(get_energy(melody_track_name, tick))
        except Exception:
            continue

        if energy >= threshold:
            # Melody đang "nói to" → Pulse nhún lại
            v = int(getattr(n, "velocity", 80))
            new_v = int(v * (1.0 - pulse_reduction_ratio))
            n.velocity = clamp_velocity(new_v)

    return pulse_notes

# =========================
# 6. Melody Performance Layer
# =========================

def is_sustained_wind_instrument(profile: Any) -> bool:
    """
    Heuristic đơn giản để nhận diện nhạc cụ hơi / sustain:

    - Dựa trên profile.name hoặc các persona quen thuộc (flute, shakuhachi, oboe...).
    """
    if profile is None:
        return False

    name = str(getattr(profile, "name", "")).lower()
    persona = str(getattr(profile, "persona", "")).lower()

    text = name + " " + persona
    wind_keywords = [
        "flute",
        "shaku",
        "shakuhachi",
        "oboe",
        "clarinet",
        "sax",
        "pan",
        "whistle",
    ]

    return any(k in text for k in wind_keywords)

def enhance_melody_note(
    note: Any,
    tempo_map: Optional[TempoMap],
    ppq: int,
    activity_map: Optional[ActivityMap] = None,
    enable_beat_stress: bool = True,
    treat_ghost: bool = True,
    humanize_range: int = 3,
) -> Any:
    """
    Performance Layer cho từng Melody Note:

    1. Beat Stress + Humanize (apply_beat_stress_to_note).
    2. Ghost Note: nếu note.kind == "ghost" → giảm velocity.
    3. ActivityMap: API giữ chỗ (chưa can thiệp trực tiếp để tránh crash).
    """
    # 1. Beat Stress + Humanize
    apply_beat_stress_to_note(
        note=note,
        tempo_map=tempo_map,
        ppq=ppq,
        enable_beat_stress=enable_beat_stress,
        humanize_range=humanize_range,
    )

    # 2. Ghost Note
    if treat_ghost and is_ghost_note(note):
        clamp_ghost_velocity(note)

    # 3. ActivityMap hook (nếu muốn sau này tinh chỉnh thêm)
    # Hiện tại chưa sửa velocity theo ActivityMap để đảm bảo an toàn.

    return note
