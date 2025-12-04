# Tệp: src/utils/activity_map.py
# (FINAL V11.0.0) - ACTIVITY MAP V2 (ZEN DIRECTOR)
#
# Vai trò:
# - Đóng vai “Zen Director” cho toàn bộ hệ thống:
#   + Theo dõi mật độ (density) theo thời gian (global + per-layer).
#   + Hiểu Zen Arc (Grounding / Immersion / Peak / Breakdown / Integration).
#   + Hiểu Breath cycle (breath_index, breath_phase).
#   + Giữ tỉ lệ Stillness vs Movement ≈ 80/20 theo phase + breath.
#   + Đưa ra gợi ý cho engine: có nên chơi (allow), giảm density/velocity, priority...
#
# API chính:
#   cfg = ActivityMapConfig(...)
#   act = ActivityMap(tempo_map, zen_arc_matrix, breath_sync, user_options, total_ticks, rng_seed=None, config=cfg)
#
#   decision = act.query_decision(
#       layer="melody",
#       start_tick=tick,
#       segment_index=seg_idx,
#       total_segments=total_seg,
#       base_velocity=0.9,
#       importance=1.0,
#   )
#
#   if decision.allow:
#       # engine tự scale velocity / mật độ nếu muốn
#       final_vel = int(base_vel * decision.velocity_mul)
#       ...
#       act.commit_event("melody", start_tick, duration_ticks, weight=1.0)
#
#   # API legacy (giữ để tương thích code cũ):
#   act.add_activity(start_tick, duration_ticks, weight=0.5, layer="BASS")
#   act.get_activity_at(tick)
#   act.get_track_energy("MELODY", tick)

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, Any, Optional, List


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# ============================================================
# 1. CONFIG & DECISION TYPES
# ============================================================


@dataclass
class ActivityMapConfig:
    """
    Cấu hình cho ActivityMap V2.

    Các giá trị mặc định được chọn sao cho:
    - base_movement_ratio ~ 0.2  → 20% movement khi movement_bias = 0.
    - movement_ratio_gain ~ 0.6  → movement_ratio max ~ 0.8 khi movement_bias = 1.
    - stillness_randomness       → độ "ngẫu nhiên" trong quyết định.
    - global/layer soft/hard limit → ngưỡng density tương đối (unit tuỳ theo weight).
    """

    # Độ phân giải theo tick: mỗi bin là một cửa sổ thời gian nhỏ
    bin_size_ticks: int = 120

    # Stillness vs Movement
    base_movement_ratio: float = 0.2
    movement_ratio_gain: float = 0.6
    stillness_randomness: float = 0.25
    movement_window_breaths: int = 4

    # Ngưỡng density tương đối (soft/hard) cho global và per-layer
    global_soft_limit: float = 0.75
    global_hard_limit: float = 1.15
    layer_soft_limit: float = 1.0
    layer_hard_limit: float = 1.5


@dataclass
class ActivityDecision:
    """
    Kết quả trả về cho mỗi query của engine.

    Engine có thể dùng:
    - allow: quyết định chơi hay không.
    - density_mul: scale xác suất sinh nốt / số lượng event.
    - velocity_mul: scale velocity.
    - priority: dùng khi nhiều event cạnh tranh nhau ở cùng tick.
    - phase_name, breath_phase, breath_index: thông tin context (debug / fine-tune).
    - reason: text gợi ý lý do (debug).
    """

    allow: bool
    density_mul: float = 1.0
    velocity_mul: float = 1.0
    priority: float = 0.5
    phase_name: str = ""
    breath_phase: str = ""
    breath_index: int = 0
    reason: str = ""


# ============================================================
# 2. ACTIVITY MAP V2
# ============================================================


class ActivityMap:
    """
    ActivityMap V2 – Zen Director.

    - Theo dõi activity dạng bin (global + per-layer).
    - Phase-aware (Zen Arc) + Breath-aware.
    - Đưa ra quyết định allow/deny + gợi ý density/velocity.
    - Giữ tương thích API cũ: add_activity, get_activity_at, get_track_energy.
    """

    def __init__(
        self,
        tempo_map: Any,
        zen_arc_matrix: Any,
        breath_sync: Any,
        user_options: Optional[Dict[str, Any]],
        total_ticks: int,
        rng_seed: Optional[int] = None,
        config: Optional[ActivityMapConfig] = None,
    ):
        self.tempo_map = tempo_map
        self.zen_arc_matrix = zen_arc_matrix
        self.breath_sync = breath_sync
        self.user_options = user_options or {}
        self.total_ticks = int(max(0, total_ticks))

        # RNG – tái lập được bằng seed nếu cần
        if rng_seed is None:
            rng_seed = random.randint(0, 2**31 - 1)
        self.rng = random.Random(int(rng_seed))

        # Build config từ user_options + override
        self.config = self._build_config(self.user_options.get("activity_map", {}), config)

        # Energy weights cho từng layer – dùng để đo độ "nặng" của layer
        # Cho phép override qua user_options["activity_energy_weights"].
        default_energy_weights = {
            "MELODY": 1.2,
            "HARM": 1.0,
            "PULSE": 1.0,
            "AIR": 0.6,
            "CHIME": 0.8,
            # Các layer mới / ngoại biên:
            "NATURE": 0.5,
            "VOCAL": 1.1,
            "HANDPAN": 1.2,
            "BASS": 0.9,
            "BINAURAL": 0.3,
            "DRONE": 0.7,
        }
        user_weights = self.user_options.get("activity_energy_weights", {}) or {}
        # Chuẩn hoá key → upper
        user_weights_norm = {
            str(k).upper(): float(v) for k, v in user_weights.items()
        }
        self.energy_weights: Dict[str, float] = {**default_energy_weights, **user_weights_norm}

        # Khởi tạo bins
        self.bin_size = int(max(1, self.config.bin_size_ticks))
        if self.total_ticks <= 0:
            self.num_bins = 1
        else:
            self.num_bins = max(1, int(math.ceil(self.total_ticks / self.bin_size)))

        # Global activity (không phân layer)
        self.global_bins: List[float] = [0.0 for _ in range(self.num_bins)]
        # Per-layer activity
        self.layer_bins: Dict[str, List[float]] = {}

    # --------------------------------------------------------
    # CONFIG
    # --------------------------------------------------------

    def _build_config(
        self,
        cfg_dict: Dict[str, Any],
        override: Optional[ActivityMapConfig],
    ) -> ActivityMapConfig:
        if override is not None:
            base = override
        else:
            base = ActivityMapConfig()

        # Cho phép override từng field từ cfg_dict
        for field_name in [
            "bin_size_ticks",
            "base_movement_ratio",
            "movement_ratio_gain",
            "stillness_randomness",
            "movement_window_breaths",
            "global_soft_limit",
            "global_hard_limit",
            "layer_soft_limit",
            "layer_hard_limit",
        ]:
            if field_name in cfg_dict:
                try:
                    val = cfg_dict[field_name]
                    if isinstance(getattr(base, field_name), int):
                        val = int(val)
                    else:
                        val = float(val)
                    setattr(base, field_name, val)
                except Exception:
                    pass
        # Đảm bảo bin_size_ticks > 0
        if base.bin_size_ticks <= 0:
            base.bin_size_ticks = 120
        return base

    # --------------------------------------------------------
    # BIN / DENSITY UTILITIES
    # --------------------------------------------------------

    def _tick_to_bin(self, tick: int) -> int:
        if self.num_bins <= 1:
            return 0
        idx = int(tick // self.bin_size)
        if idx < 0:
            idx = 0
        if idx >= self.num_bins:
            idx = self.num_bins - 1
        return idx

    def _ensure_layer_bins(self, layer: str) -> List[float]:
        key = str(layer).upper()
        if key not in self.layer_bins:
            self.layer_bins[key] = [0.0 for _ in range(self.num_bins)]
        return self.layer_bins[key]

    # ============================================================
    # 3. PUBLIC API (LEGACY + NEW)
    # ============================================================

    # ---------- LEGACY: add_activity / get_activity_at / get_track_energy ----------

    def add_activity(
        self,
        start_tick: int,
        duration_ticks: int,
        weight: float = 1.0,
        layer: str = "GLOBAL",
    ) -> None:
        """
        API legacy: engine báo "có hoạt động" trong khoảng thời gian, không cần query/decision.

        Thực chất chính là commit_event với layer và weight.
        """
        self.commit_event(layer=layer, start_tick=start_tick, duration_ticks=duration_ticks, weight=weight)

    def get_activity_at(self, tick: int) -> float:
        """
        Trả về mức activity global (đã cộng tất cả layer) tại tick.
        Dùng cho engine V10 cũ.
        """
        idx = self._tick_to_bin(tick)
        return float(self.global_bins[idx]) if 0 <= idx < self.num_bins else 0.0

    def get_track_energy(self, layer: str, tick: int) -> float:
        """
        Trả về mức activity của một layer riêng tại tick.
        Dùng cho code cũ (fallback trong một số engine).
        """
        key = str(layer).upper()
        if key not in self.layer_bins:
            return 0.0
        idx = self._tick_to_bin(tick)
        bins = self.layer_bins[key]
        return float(bins[idx]) if 0 <= idx < len(bins) else 0.0

    # ---------- NEW: commit_event / query_decision ----------

    def commit_event(
        self,
        layer: str,
        start_tick: int,
        duration_ticks: int,
        weight: float = 1.0,
    ) -> None:
        """
        Sau khi engine QUYẾT ĐỊNH chơi một event (note/chord), gọi hàm này để ghi nhận activity.

        - layer: tên layer (MELODY/HARM/DRONE/...)
        - start_tick, duration_ticks: khoảng thời gian event chiếm.
        - weight: “độ nặng” của event (VD: chord dày → weight cao).
        """
        if self.num_bins <= 0 or duration_ticks <= 0:
            return

        key = str(layer).upper()
        layer_bins = self._ensure_layer_bins(key)

        start = int(max(0, start_tick))
        end = int(max(start, start_tick + duration_ticks))

        start_bin = self._tick_to_bin(start)
        end_bin = self._tick_to_bin(end - 1)  # end là exclusive

        if end_bin < start_bin:
            end_bin = start_bin

        # Chia đều weight cho các bin nằm trong khoảng
        span_bins = max(1, end_bin - start_bin + 1)
        per_bin = float(weight) / float(span_bins)

        for idx in range(start_bin, end_bin + 1):
            if 0 <= idx < self.num_bins:
                self.global_bins[idx] += per_bin
                layer_bins[idx] += per_bin

    def query_decision(
        self,
        layer: str,
        start_tick: int,
        segment_index: int = 0,
        total_segments: int = 1,
        base_velocity: float = 1.0,
        importance: float = 1.0,
    ) -> ActivityDecision:
        """
        Engine hỏi: "Ở tick này, layer này có nên chơi thêm event không?"

        Trả về ActivityDecision:
        - allow: True/False
        - density_mul: gợi ý scale số event (1.0 = giữ nguyên).
        - velocity_mul: gợi ý scale velocity.
        - priority: score 0..1 (có thể dùng khi nhiều event cạnh tranh).
        """

        layer_key = str(layer).upper()
        base_velocity = float(_clamp(base_velocity, 0.0, 2.0))
        importance = float(_clamp(importance, 0.0, 2.0))

        # Lấy thông tin phase / breath
        phase_name, movement_bias = self._get_phase_info(start_tick)
        breath_index, breath_phase = self._get_breath_info(start_tick)

        # Tính movement_ratio ~ [0..1]
        movement_ratio = (
            self.config.base_movement_ratio
            + self.config.movement_ratio_gain * movement_bias
        )
        movement_ratio = float(_clamp(movement_ratio, 0.0, 1.0))

        # Lấy density hiện tại
        global_density, layer_density = self._get_density(layer_key, start_tick)

        # Scale layer density theo energy weight (layer "nặng" đóng góp nhiều hơn)
        energy_weight = self.energy_weights.get(layer_key, 1.0)
        effective_layer_density = layer_density * energy_weight

        # Bắt đầu với giả định "cho phép"
        allow = True
        density_mul = 1.0
        velocity_mul = 1.0
        reason = "ok"

        # ----------------------------------------------------
        # 1) Áp dụng hard limit – nếu vượt, chặn luôn
        # ----------------------------------------------------
        if global_density > self.config.global_hard_limit:
            allow = False
            reason = "global_over_hard_limit"
        elif effective_layer_density > self.config.layer_hard_limit:
            allow = False
            reason = "layer_over_hard_limit"

        # ----------------------------------------------------
        # 2) Nếu chưa chặn, áp dụng soft limit & stillness logic
        # ----------------------------------------------------
        if allow:
            # Soft limit: giảm velocity / density
            if global_density > self.config.global_soft_limit:
                # Giảm nhẹ velocity và density
                alpha = float(
                    _clamp(
                        (self.config.global_hard_limit - global_density)
                        / max(1e-6, (self.config.global_hard_limit - self.config.global_soft_limit)),
                        0.0,
                        1.0,
                    )
                )
                density_mul *= 0.5 + 0.5 * alpha
                velocity_mul *= 0.7 + 0.3 * alpha
                reason = "global_over_soft_limit"

            if effective_layer_density > self.config.layer_soft_limit:
                beta = float(
                    _clamp(
                        (self.config.layer_hard_limit - effective_layer_density)
                        / max(1e-6, (self.config.layer_hard_limit - self.config.layer_soft_limit)),
                        0.0,
                        1.0,
                    )
                )
                density_mul *= 0.5 + 0.5 * beta
                velocity_mul *= 0.8 + 0.2 * beta
                if reason == "ok":
                    reason = "layer_over_soft_limit"

            # ------------------------------------------------
            # 3) Stillness vs Movement theo phase & breath
            # ------------------------------------------------

            # 3.1 Random gate: giữ tỉ lệ movement theo movement_ratio
            gate_rand = self.rng.random()
            # break-down & integration → ưu tiên stillness hơn
            phase_lower = (phase_name or "").lower()
            breath_lower = (breath_phase or "").lower()

            # Điều chỉnh movement_ratio theo phase
            if phase_lower in ("grounding", "intro"):
                movement_ratio *= 0.6
            elif phase_lower == "breakdown":
                movement_ratio *= 0.3
            elif phase_lower == "integration" or phase_lower == "outro":
                movement_ratio *= 0.5
            elif phase_lower == "peak":
                movement_ratio *= 1.1
            # clamp lại
            movement_ratio = float(_clamp(movement_ratio, 0.0, 1.0))

            # Breath valley → ưu tiên stillness hơn
            if breath_lower in ("valley", "end"):
                movement_ratio *= 0.7

            # Giảm movement khi density đã cao, trước cả soft-limit
            global_pressure = _clamp(
                global_density / max(1e-6, self.config.global_hard_limit), 0.0, 1.0
            )
            layer_pressure = _clamp(
                effective_layer_density / max(1e-6, self.config.layer_hard_limit), 0.0, 1.0
            )
            density_pressure = max(global_pressure, layer_pressure)
            if density_pressure > 0:
                # Giữ stillness cao hơn khi gần ngưỡng; 0.5 → giảm 50% movement_ratio
                movement_ratio *= 1.0 - 0.5 * density_pressure
                reason = reason if reason != "ok" else "density_pressure"

            # Thêm randomness
            effective_gate = movement_ratio * (
                1.0 - self.config.stillness_randomness
            ) + self.config.stillness_randomness * self.rng.random()
            effective_gate = float(_clamp(effective_gate, 0.0, 1.0))

            if gate_rand > effective_gate:
                # Bị gate bởi stillness logic
                allow = False
                if reason == "ok":
                    reason = "stillness_gate"

        # ----------------------------------------------------
        # 4) Priority – dùng importance + movement_bias + density
        # ----------------------------------------------------
        # Ưu tiên cao khi:
        # - importance cao
        # - movement_bias cao (Immersion/Peak)
        # - global_density chưa quá nặng
        inv_density = math.exp(-0.7 * max(0.0, global_density))  # giảm dần khi quá dày
        priority = float(
            _clamp(
                importance * (0.4 + 0.6 * movement_bias) * inv_density,
                0.0,
                1.0,
            )
        )

        # ----------------------------------------------------
        # 5) Final decision
        # ----------------------------------------------------
        # Nếu không allow thì coi như density_mul/velocity_mul không dùng,
        # nhưng vẫn trả về để debug.
        decision = ActivityDecision(
            allow=allow,
            density_mul=float(_clamp(density_mul, 0.0, 2.0)),
            velocity_mul=float(_clamp(velocity_mul * base_velocity, 0.0, 2.0)),
            priority=priority,
            phase_name=phase_name or "",
            breath_phase=breath_phase or "",
            breath_index=breath_index,
            reason=reason,
        )
        return decision

    # ============================================================
    # 4. INTERNAL HELPERS (PHASE / BREATH / DENSITY)
    # ============================================================

    def _get_phase_info(self, tick: int) -> (str, float):
        """
        Lấy phase_name + movement_bias từ ZenArcMatrix.
        Nếu thiếu API hoặc lỗi → fallback: ("", 0.5).
        """
        phase_name = ""
        movement_bias = 0.5
        try:
            # API ưu tiên: get_phase_at_tick(tick) → dict
            if hasattr(self.zen_arc_matrix, "get_phase_at_tick"):
                info = self.zen_arc_matrix.get_phase_at_tick(tick)
                if isinstance(info, dict):
                    phase_name = str(info.get("name", "") or "")
                    mb = info.get("movement_bias", None)
                    if mb is not None:
                        movement_bias = float(_clamp(float(mb), 0.0, 1.0))
            else:
                # Fallback: thử get_phase_name_at_tick & get_movement_bias_at_tick
                if hasattr(self.zen_arc_matrix, "get_phase_name_at_tick"):
                    phase_name = str(self.zen_arc_matrix.get_phase_name_at_tick(tick) or "")
                if hasattr(self.zen_arc_matrix, "get_movement_bias_at_tick"):
                    mb = self.zen_arc_matrix.get_movement_bias_at_tick(tick)
                    movement_bias = float(_clamp(float(mb), 0.0, 1.0))
        except Exception:
            pass
        return phase_name, movement_bias

    def _get_breath_info(self, tick: int) -> (int, str):
        """
        Lấy (breath_index, breath_phase) từ BreathSyncManager.
        Nếu thiếu API → fallback: (0, "free").
        """
        breath_index = 0
        breath_phase = "free"
        try:
            if self.breath_sync is None:
                return breath_index, breath_phase
            # API ưu tiên: get_breath_info_at_tick(tick) → dict
            if hasattr(self.breath_sync, "get_breath_info_at_tick"):
                info = self.breath_sync.get_breath_info_at_tick(tick)
                if isinstance(info, dict):
                    idx = info.get("breath_index", None)
                    phase = info.get("phase", None) or info.get("breath_phase", None)
                    if idx is not None:
                        breath_index = int(idx)
                    if phase:
                        breath_phase = str(phase)
            else:
                # Fallback: tách riêng phase / index nếu có
                if hasattr(self.breath_sync, "get_breath_phase_at_tick"):
                    p = self.breath_sync.get_breath_phase_at_tick(tick)
                    if p:
                        breath_phase = str(p)
                if hasattr(self.breath_sync, "get_breath_index_at_tick"):
                    i = self.breath_sync.get_breath_index_at_tick(tick)
                    breath_index = int(i)
        except Exception:
            pass
        return breath_index, breath_phase

    def _get_density(self, layer: str, tick: int) -> (float, float):
        """
        Trả về (global_density, layer_density) tại tick,
        có smoothing nhẹ quanh bin hiện tại.
        """
        if self.num_bins <= 0:
            return 0.0, 0.0

        idx = self._tick_to_bin(tick)
        if idx < 0 or idx >= self.num_bins:
            return 0.0, 0.0

        # Smoothing window ±1 bin
        lo = max(0, idx - 1)
        hi = min(self.num_bins - 1, idx + 1)
        span = max(1, hi - lo + 1)

        # Global
        g_sum = 0.0
        for i in range(lo, hi + 1):
            g_sum += self.global_bins[i]
        global_density = g_sum / float(span)

        # Layer
        key = str(layer).upper()
        if key not in self.layer_bins:
            layer_density = 0.0
        else:
            bins = self.layer_bins[key]
            l_sum = 0.0
            for i in range(lo, hi + 1):
                if 0 <= i < len(bins):
                    l_sum += bins[i]
            layer_density = l_sum / float(span)

        return float(global_density), float(layer_density)
