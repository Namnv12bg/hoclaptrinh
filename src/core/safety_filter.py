# Tệp: src/core/safety_filter.py
# (BETA V10.11.1) - SAFETY FILTER CORE (MERGED IDEAS)
#
# Vai trò:
#   - "Lớp cảnh sát" cuối cùng trước khi note được ghi vào MIDI.
#   - Bảo vệ toàn hệ thống khỏi:
#       + Nốt phô / nốt ngoài quãng an toàn (RegisterSafety + PitchSafety).
#       + Vel spikes (VelocitySafety + ShockGuard).
#       + Density spike (DensitySafety).
#       + Layer xung đột / shock năng lượng (DensitySafety + ShockGuard + MixEnergyGuard).
#
#   - Không sinh note, không quyết định hòa âm.
#   - Chỉ **chuẩn hóa** và **chặn** những trường hợp quá nguy hiểm.
#
# Sử dụng trong Engine:
#
#   safe_pitch, safe_vel, allow, info = safety_filter.apply_note(
#       layer="melody",
#       pitch=raw_pitch,
#       velocity=raw_velocity,
#       tick=start_tick,
#       meta={
#           "segment_index": seg_idx,
#           "phase_name": segment.phase_name,
#           "section_type": segment.section_type,
#       },
#   )
#
#   if allow and safe_vel > 0:
#       writer.note_on(...)
#       writer.note_off(...)
#
# Ghi chú:
#   - SafetyFilter KHÔNG phụ thuộc ActivityMap (đạo diễn density/tính động),
#     nhưng DensitySafety vẫn giữ 1 lớp "phanh" riêng, dựa trên cửa sổ breath.

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple, List

try:  # pragma: no cover
    from src.core.tempo_breath import TempoMap  # type: ignore
except ImportError:  # pragma: no cover
    class TempoMap:  # type: ignore
        ppq: int = 480
        base_tempo: float = 60.0
        breath_cycle_bars: float = 2.0

try:  # pragma: no cover
    from src.core.register_manager import RegisterManager  # type: ignore
except ImportError:  # pragma: no cover
    class RegisterManager:  # type: ignore
        def get_layer_range(self, layer: str, tick: int) -> Tuple[int, int]:
            return 21, 108  # mặc định: A0..C8

# =========================
# 1. CONFIG DATA CLASSES
# =========================

@dataclass
class SafetyConfig:
    """
    Tham số cấu hình chung cho SafetyFilter.
    Có thể override qua user_options["safety_filter"].

    Merge từ 2 bản:
      - Bản mới: pitch_min/max, vel_min/max, density_window_breaths/soft/hard,
                 shock_vel_jump_threshold/time_window/damp_factor.
      - Bản cũ: velocity step limit (max_step_up/down),
                density_drop_excess_notes,
                mix-wide energy guard (energy_window_bars, max_energy, soften_ratio).
    """

    # Pitch
    pitch_min: int = 0
    pitch_max: int = 127

    # Velocity
    vel_min: int = 10
    vel_max: int = 120
    vel_soft_ceiling: int = 105  # trên mức này sẽ bị nén bớt
    vel_step_up_max: int = 35    # tối đa tăng giữa 2 nốt liên tiếp cùng layer
    vel_step_down_max: int = 80  # tối đa giảm giữa 2 nốt

    # Density (per layer, breath window)
    density_window_breaths: int = 2   # số hơi thở trong 1 cửa sổ density
    density_soft_limit: int = 16      # số note/ cửa sổ -> bắt đầu phanh
    density_hard_limit: int = 32      # quá mức này có thể chặn event
    density_drop_excess_notes: bool = True  # giống bản cũ: true -> drop, false -> chỉ giảm vel

    # Shock (per-layer, local jump)
    shock_vel_jump_threshold: int = 40    # nhảy velocity > ngưỡng này trong thời gian ngắn => shock
    shock_time_window_beats: float = 1.0  # trong bao nhiêu beat được coi là "ngắn"
    shock_damp_factor: float = 0.6        # scale velocity khi bị shock

    # Mix-wide Energy Guard (merge từ bản cũ)
    mix_energy_window_bars: float = 0.5   # chiều dài cửa sổ (bar) để đo tổng năng lượng
    mix_energy_max: float = 12.0          # tổng vel_norm trong cửa sổ cho phép
    mix_energy_soften_ratio: float = 0.65 # nếu vượt quá -> scale velocity

    # Global
    debug: bool = False

# =========================
# 2. MODULE CON
# =========================

class PitchSafety:
    """
    Lớp xử lý Pitch mức cơ bản:
      - Clamp pitch 0..127.
      - Chừa chỗ sau này cài scale-based filter (diatonic, pentatonic...).
    """

    def __init__(self, cfg: SafetyConfig):
        self.cfg = cfg

    def enforce_pitch(self, pitch: int) -> int:
        if pitch is None:
            return self.cfg.pitch_min
        p = int(pitch)
        if p < self.cfg.pitch_min:
            return self.cfg.pitch_min
        if p > self.cfg.pitch_max:
            return self.cfg.pitch_max
        return p

class VelocitySafety:
    """
    Lớp xử lý Velocity:
      - Clamp 0..127.
      - Giữ velocity trong khoảng "Zen-safe" (tránh fortissimo).
      - Phần compress mềm để tránh clip ở đỉnh.

    Ghi chú:
      - Giới hạn bước nhảy per-layer (max_step_up/down) được xử lý ở SafetyFilter,
        vì cần state last_vel theo layer.
    """

    def __init__(self, cfg: SafetyConfig):
        self.cfg = cfg

    def enforce_velocity(self, velocity: int) -> int:
        if velocity is None:
            return 0
        v = int(velocity)
        if v <= 0:
            return 0

        # clamp cứng 0..127
        if v < 1:
            v = 1
        if v > 127:
            v = 127

        # clamp vùng "Zen-safe"
        if v > self.cfg.vel_max:
            v = self.cfg.vel_max

        # compress nhẹ vùng soft_ceiling..vel_max
        if v > self.cfg.vel_soft_ceiling:
            over = v - self.cfg.vel_soft_ceiling
            span = max(1, self.cfg.vel_max - self.cfg.vel_soft_ceiling)
            ratio = over / span  # 0..1
            # nén lại: càng gần vel_max, càng bị kéo về soft_ceiling
            v = int(round(self.cfg.vel_soft_ceiling + over * (1.0 - 0.5 * ratio)))
        return max(0, min(127, v))

class DensitySafety:
    """
    Lớp kiểm soát mật độ "thô" theo breath-window:

      - Phân loại note theo layer.
      - Giữ danh sách tick của note trong cửa sổ (theo hơi thở).
      - Nếu số note trong cửa sổ > soft_limit -> giảm velocity.
      - Nếu quá hard_limit -> có thể chặn event.

    Đây chỉ là ** lớp phanh cuối **, density mượt mà vẫn do ActivityMap V2 điều khiển.
    """

    def __init__(self, cfg: SafetyConfig, tempo_map: TempoMap):
        self.cfg = cfg
        self.tempo_map = tempo_map

        # layer -> list[tick]
        self._events: Dict[str, List[int]] = {}

        # Tính kích thước cửa sổ theo ticks
        ppq = int(getattr(self.tempo_map, "ppq", 480) or 480)
        cycle_bars = float(getattr(self.tempo_map, "breath_cycle_bars", 2.0) or 2.0)

        # 1 bar = 4 beat
        beats_per_bar = 4.0
        # số bar trong 1 breath
        bars_per_breath = cycle_bars
        # ticks cho 1 breath
        self._ticks_per_breath = int(ppq * beats_per_bar * bars_per_breath)

        # tổng ticks trong cửa sổ density
        self._window_ticks = max(
            ppq, self._ticks_per_breath * max(1, self.cfg.density_window_breaths)
        )

    def reset(self) -> None:
        """Clear internal density tracking state."""
        self._events.clear()

    def _prune_old(self, layer: str, current_tick: int) -> None:
        """
        Xoá event quá cũ nằm ngoài window.
        """
        lst = self._events.get(layer)
        if not lst:
            return
        threshold = current_tick - self._window_ticks
        i = 0
        n = len(lst)
        # tìm index đầu tiên >= threshold
        while i < n and lst[i] < threshold:
            i += 1
        if i > 0:
            self._events[layer] = lst[i:]

    def register_event(self, layer: str, tick: int) -> None:
        """
        Ghi nhận 1 event đã diễn ra để cập nhật density.
        """
        if layer not in self._events:
            self._events[layer] = []
        self._events[layer].append(int(tick))

    def check_density(self, layer: str, tick: int) -> Tuple[bool, float, int]:
        """
        Kiểm tra mật độ hiện tại của layer trong window.

        Returns:
            (allow, velocity_scale, current_count)
        """
        tick = int(tick)
        self._prune_old(layer, tick)

        evts = self._events.get(layer, [])
        count = len(evts)

        # Nếu còn dưới soft_limit -> ok, không giảm
        if count <= self.cfg.density_soft_limit:
            return True, 1.0, count

        # Nếu vượt hard_limit -> có khả năng chặn
        if count >= self.cfg.density_hard_limit:
            # cho qua nhưng giảm mạnh (layer vẫn có cơ hội đánh note quan trọng)
            return False, 0.3, count

        # Zone giữa soft..hard: giảm velocity tương ứng
        span = max(1, self.cfg.density_hard_limit - self.cfg.density_soft_limit)
        over = count - self.cfg.density_soft_limit
        ratio = over / span  # 0..1
        vel_scale = max(0.4, 1.0 - 0.6 * ratio)
        return True, vel_scale, count

class RegisterSafety:
    """
    Lớp xử lý quãng an toàn cho từng layer, dựa trên RegisterManager.

    - Hỏi RegisterManager để lấy (low, high) của layer tại tick.
    - Clamp pitch vào khoảng đó.
    """

    def __init__(self, register_manager: RegisterManager):
        self.rm = register_manager

    def enforce_register(self, layer: str, pitch: int, tick: int) -> Tuple[int, Tuple[int, int]]:
        low, high = self.rm.get_layer_range(layer, tick)
        if low > high:
            low, high = min(low, high), max(low, high)
        p = int(pitch)
        if p < low:
            p = low
        if p > high:
            p = high
        return p, (low, high)

class TimbreSafety:
    """
    Các luật liên quan đến "màu" (timbre) theo layer + phase:

      - Ví dụ:
        + Giảm bớt layer "air" ở Peak nếu phase_energy quá cao.
        + Làm mềm "chime" trong breakdown để tránh gắt.

    Packet meta có thể chứa:
        - "section_type"
        - "phase_name"
        - "phase_energy"
        - "movement_hint" ...
    """

    def __init__(self, cfg: SafetyConfig):
        self.cfg = cfg

    def adjust(
        self,
        layer: str,
        pitch: int,
        velocity: int,
        tick: int,
        meta: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Điều chỉnh nhẹ velocity theo layer + phase để tránh dải quá gắt.

        - Giảm bớt "air" ở peak nếu phase_energy cao.
        - Giảm "chime" ở breakdown.
        """
        if velocity is None:
            return 0

        v = int(velocity)
        if meta is None:
            # Không có context → chỉ cần clamp mềm theo cfg.
            return max(self.cfg.vel_min, min(self.cfg.vel_max, v))

        phase_energy = float(meta.get("phase_energy", 0.5))
        section_type = str(meta.get("section_type", "") or "").lower()

        # Rule 1: Air quá gắt ở Peak → giảm nhẹ
        if layer == "air" and phase_energy > 0.8:
            v = int(v * 0.8)

        # Rule 2: Chime trong breakdown → mềm lại
        if layer == "chime" and section_type in ("breakdown", "silent_breakdown", "bridge"):
            v = int(v * 0.7)

        # Clamp cuối cùng theo ngưỡng SafetyConfig
        v = max(self.cfg.vel_min, min(self.cfg.vel_max, v))
        return v

class ShockGuard:
    """
    Bảo vệ khỏi "shock" năng lượng (nhảy velocity lớn trong thời gian rất ngắn).

    - Với mỗi layer, lưu thông tin note lần trước:
        + last_tick
        + last_velocity

    - Nếu:
        + |vel_now - vel_prev| > vel_jump_threshold
        + |tick_now - tick_prev| < time_window (theo beat)
      => coi là shock, giảm velocity theo shock_damp_factor.
    """

    def __init__(self, cfg: SafetyConfig, tempo_map: TempoMap):
        self.cfg = cfg
        self.tempo_map = tempo_map

        # layer -> (last_tick, last_velocity)
        self._last: Dict[str, Tuple[int, int]] = {}

        # tính time_window_ticks
        ppq = int(getattr(self.tempo_map, "ppq", 480) or 480)
        beats = float(self.cfg.shock_time_window_beats)
        self._time_window_ticks = int(ppq * beats)

    def reset(self) -> None:
        """Clear stored shock history."""
        self._last.clear()

    def enforce(
        self,
        layer: str,
        pitch: int,
        velocity: int,
        tick: int,
    ) -> Tuple[int, bool]:
        """
        Returns:
            (safe_velocity, is_shock)
        """
        tick = int(tick)
        v = int(velocity)

        last = self._last.get(layer)
        is_shock = False

        if last is not None:
            last_tick, last_vel = last
            dt = abs(tick - last_tick)
            dv = abs(v - last_vel)

            if dt <= self._time_window_ticks and dv >= self.cfg.shock_vel_jump_threshold:
                # Shock: giảm velocity
                is_shock = True
                v = int(round(v * self.cfg.shock_damp_factor))

        # update state
        self._last[layer] = (tick, max(0, min(127, v)))

        return max(0, min(127, v)), is_shock

class MixEnergyGuard:
    """
    Mix-wide Energy Guard (ý từ bản cũ):

      - Giữ 1 cửa sổ time (theo bar) và tính tổng "năng lượng" vel_norm.
      - Nếu projected_energy > max_energy -> soften velocity hiện tại.

    Điều này giúp tránh trường hợp cả nhiều layer cùng tăng mạnh một lúc.
    """

    def __init__(self, cfg: SafetyConfig, tempo_map: TempoMap):
        self.cfg = cfg
        self.tempo_map = tempo_map
        self._events: List[Tuple[int, float]] = []

        ppq = int(getattr(self.tempo_map, "ppq", 480) or 480)
        self._window_ticks = int(self.cfg.mix_energy_window_bars * 4.0 * ppq)  # 4/4

    def reset(self) -> None:
        """Clear accumulated energy window."""
        self._events.clear()

    def enforce(self, velocity: int, tick: int) -> Tuple[int, bool]:
        """
        Returns:
            (safe_velocity, softened)
        """
        if self.cfg.mix_energy_window_bars <= 0 or self.cfg.mix_energy_max <= 0:
            return velocity, False

        tick = int(tick)

        # prune
        cutoff = tick - self._window_ticks
        while self._events and self._events[0][0] < cutoff:
            self._events.pop(0)

        current_energy = sum(e for _, e in self._events)

        v = int(velocity)
        energy_norm = max(0.0, min(1.0, v / 127.0))
        projected = current_energy + energy_norm

        softened = False
        if projected > self.cfg.mix_energy_max:
            v = max(8, int(round(v * self.cfg.mix_energy_soften_ratio)))
            energy_norm = max(0.0, min(1.0, v / 127.0))
            softened = True

        self._events.append((tick, energy_norm))
        return v, softened

# =========================
# 3. SAFETY FILTER WRAPPER
# =========================

class SafetyFilter:
    """
    SafetyFilter – API chính mà các Engine sẽ sử dụng.

    Ý tưởng:
        - ActivityMap quyết định: "Ở tick này layer có nói không?"
        - SafetyFilter quyết định: "Nếu nói, nói nhỏ lại / đổi quãng / chặn nếu nguy hiểm."

    Gọi đơn giản:

        safe_pitch, safe_vel, allow, info = safety_filter.apply_note(
            layer="melody",
            pitch=raw_pitch,
            velocity=raw_velocity,
            tick=start_tick,
            meta={"phase_name": segment.phase_name},
        )
    """

    def __init__(
        self,
        user_options: Optional[Dict[str, Any]] = None,
        register_manager: Optional[RegisterManager] = None,
        tempo_map: Optional[TempoMap] = None,
    ):
        self.user_options = user_options or {}
        self.tempo_map = tempo_map or TempoMap()
        self.register_manager = register_manager or RegisterManager(
            self.user_options if isinstance(self.user_options, dict) else {},  # type: ignore
            self.tempo_map,
            None,  # type: ignore
        )

        # Load config từ user_options nếu có
        self.cfg = self._build_config(self.user_options)
        self.debug = self.cfg.debug

        # Module con
        self.pitch_safety = PitchSafety(self.cfg)
        self.velocity_safety = VelocitySafety(self.cfg)
        self.density_safety = DensitySafety(self.cfg, self.tempo_map)
        self.register_safety = RegisterSafety(self.register_manager)
        self.timbre_safety = TimbreSafety(self.cfg)
        self.shock_guard = ShockGuard(self.cfg, self.tempo_map)
        self.mix_guard = MixEnergyGuard(self.cfg, self.tempo_map)

        # State per-layer cho velocity step limit (ý từ bản cũ)
        self._last_velocity: Dict[str, int] = {}

    def reset_state(self) -> None:
        """Reset cached guard state so a new session can start cleanly."""
        self._last_velocity.clear()
        self.density_safety.reset()
        self.shock_guard.reset()
        self.mix_guard.reset()

    # ---------- CONFIG ----------

    def _build_config(self, user_options: Dict[str, Any]) -> SafetyConfig:
        sf = user_options.get("safety_filter", {}) or {}
        cfg = SafetyConfig()

        def get_int(name: str, default: int) -> int:
            val = sf.get(name, default)
            try:
                return int(val)
            except (TypeError, ValueError):
                return default

        def get_float(name: str, default: float) -> float:
            val = sf.get(name, default)
            try:
                return float(val)
            except (TypeError, ValueError):
                return default

        cfg.pitch_min = get_int("pitch_min", cfg.pitch_min)
        cfg.pitch_max = get_int("pitch_max", cfg.pitch_max)

        cfg.vel_min = get_int("vel_min", cfg.vel_min)
        cfg.vel_max = get_int("vel_max", cfg.vel_max)
        cfg.vel_soft_ceiling = get_int("vel_soft_ceiling", cfg.vel_soft_ceiling)
        cfg.vel_step_up_max = get_int("vel_step_up_max", cfg.vel_step_up_max)
        cfg.vel_step_down_max = get_int("vel_step_down_max", cfg.vel_step_down_max)

        cfg.density_window_breaths = get_int("density_window_breaths", cfg.density_window_breaths)
        cfg.density_soft_limit = get_int("density_soft_limit", cfg.density_soft_limit)
        cfg.density_hard_limit = get_int("density_hard_limit", cfg.density_hard_limit)
        cfg.density_drop_excess_notes = bool(
            sf.get("density_drop_excess_notes", cfg.density_drop_excess_notes)
        )

        cfg.shock_vel_jump_threshold = get_int("shock_vel_jump_threshold", cfg.shock_vel_jump_threshold)
        cfg.shock_time_window_beats = get_float("shock_time_window_beats", cfg.shock_time_window_beats)
        cfg.shock_damp_factor = get_float("shock_damp_factor", cfg.shock_damp_factor)

        cfg.mix_energy_window_bars = get_float("mix_energy_window_bars", cfg.mix_energy_window_bars)
        cfg.mix_energy_max = get_float("mix_energy_max", cfg.mix_energy_max)
        cfg.mix_energy_soften_ratio = get_float(
            "mix_energy_soften_ratio", cfg.mix_energy_soften_ratio
        )

        # Hỗ trợ cả key mới "debug" và legacy "debug_safety_filter"
        cfg.debug = bool(sf.get("debug", user_options.get("debug_safety_filter", False)))

        return cfg

    # ---------- PUBLIC API ----------

    def apply_note(
        self,
        layer: str,
        pitch: int,
        velocity: int,
        tick: int,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, int, bool, Dict[str, Any]]:
        """
        Áp dụng toàn bộ Safety pipeline cho 1 note.

        Args:
            layer: tên layer ("melody", "harm", "drone", "air", "chime", "pulse", "binaural"...)
            pitch: midi pitch (0..127)
            velocity: midi velocity (0..127)
            tick: thời điểm bắt đầu note
            meta: thông tin phụ (phase_name, section_type, segment_index, ...)

        Returns:
            safe_pitch, safe_velocity, allow, info

            - allow: nếu False -> Engine có thể bỏ qua note này.
            - info: dict nhỏ để debug/log (shock, density, register_range...).
        """
        info: Dict[str, Any] = {
            "layer": layer,
            "tick": int(tick),
            "meta": meta or {},
        }

        # 1. Pitch clamp 0..127
        p0 = self.pitch_safety.enforce_pitch(pitch)

        # 2. Register clamp theo layer
        p1, reg_range = self.register_safety.enforce_register(layer, p0, tick)
        info["register_range"] = {"low": reg_range[0], "high": reg_range[1]}
        info["pitch_before_register"] = p0
        info["pitch_after_register"] = p1

        # 3. Velocity clamp (Zen-safe range)
        v0 = self.velocity_safety.enforce_velocity(velocity)

        # 3b. Velocity step limit per-layer (ý từ bản cũ)
        last_v = self._last_velocity.get(layer)
        if last_v is not None:
            delta = v0 - last_v
            if delta > self.cfg.vel_step_up_max:
                v0 = last_v + self.cfg.vel_step_up_max
            elif delta < -self.cfg.vel_step_down_max:
                v0 = max(self.cfg.vel_min, last_v - self.cfg.vel_step_down_max)
        info["velocity_after_step_limit"] = v0

        # 4. ShockGuard – tránh nhảy vel quá mạnh trong time window
        v1, is_shock = self.shock_guard.enforce(layer, p1, v0, tick)
        info["shock"] = is_shock
        info["velocity_before_shock"] = v0
        info["velocity_after_shock"] = v1

        # 5. DensitySafety – kiểm soát mật độ layer
        allow_density, vel_scale_density, density_count = self.density_safety.check_density(
            layer, tick
        )
        info["density_allow"] = allow_density
        info["density_scale"] = vel_scale_density
        info["density_count_window"] = density_count

        v2 = int(round(v1 * vel_scale_density))

        # 6. TimbreSafety – tinh chỉnh theo layer + phase
        v3 = self.timbre_safety.adjust(layer, p1, v2, tick, meta)
        info["velocity_after_timbre"] = v3

        # 7. MixEnergyGuard – mix-wide energy window
        v4, softened_mix = self.mix_guard.enforce(v3, tick)
        info["velocity_after_mix_guard"] = v4
        info["mix_softened"] = softened_mix

        # 8. Quyết định allow cuối
        allow = True
        final_vel = v4

        # Nếu velocity sau tất cả xử lý <= 0 -> bỏ
        if final_vel <= 0:
            allow = False

        # Nếu DensitySafety báo "cửa sổ quá dày"
        if not allow_density:
            if self.cfg.density_drop_excess_notes:
                # giống bản cũ: drop thẳng nếu vượt ngưỡng
                allow = False
            else:
                # chế độ mềm: vẫn cho pass nhưng nếu quá nhỏ thì bỏ
                if final_vel < self.cfg.vel_min:
                    allow = False

        # Đảm bảo velocity không dưới vel_min nếu vẫn allow
        if allow and final_vel < self.cfg.vel_min:
            final_vel = self.cfg.vel_min

        # Cập nhật density & last_velocity nếu note được phép xảy ra
        if allow:
            self.density_safety.register_event(layer, tick)
            self._last_velocity[layer] = final_vel

        if self.debug:
            print(
                f"[SafetyFilter] layer={layer}, tick={tick}, allow={allow}, "
                f"pitch_in={pitch}->out={p1}, vel_in={velocity}->out={final_vel}, "
                f"shock={is_shock}, density_count={density_count}, mix_softened={softened_mix}"
            )

        return p1, max(0, min(127, final_vel)), allow, info

    # API phụ nếu Engine muốn tự quản lý:
    def register_activity(self, layer: str, tick: int) -> None:
        """
        Cho phép engine tự báo activity vào DensitySafety (ví dụ: chord, cluster note).
        """
        self.density_safety.register_event(layer, tick)
