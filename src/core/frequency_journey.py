# Tệp: src/core/frequency_journey.py
# (FINAL V10.10.0) - FREQUENCY JOURNEY CORE (PERCENT-BASED, T_NORM + GLIDE)
#
# Mục tiêu:
# - Tách logic "Hành trình tần số" ra khỏi tick cụ thể.
# - Làm việc chính trên trục 0..1 (t_norm ~ % bài), để:
#     + Dùng chung cho mọi mode Tuning (pure_key / solf_root / solf_dual / key_plus_solf_drone).
#     + Dễ sync với Hành trình sóng não (Brainwave Journey).
# - Giữ tương thích ngược với cấu trúc cũ:
#     + user_options["frequency_journey"]["stages"][i]["duration_pct"] có thể:
#         * là 0.5 (50%)  -> fraction
#         * hoặc 50 / 50.0 (50%) -> percent
# - Vẫn hỗ trợ build theo total_ticks nếu cần (legacy),
#   nhưng nội bộ chuẩn hóa theo 0..1 timeline.
#
# PHASE 3 – Nâng cấp:
# - Thêm khả năng xác định cách chuyển giữa các stage:
#   frequency_journey:
#       enabled: true
#       transition_mode: "step" | "glide"      # mặc định: "step"
#       glide_ratio: 0.15                      # 0..0.5, tỉ lệ mỗi stage dùng để crossfade
#       stages:
#         - label: "Stage 1 (432Hz)"
#           duration_pct: 40.0
#           freq: 432.0
#         - label: "Stage 2 (528Hz)"
#           duration_pct: 30.0
#           freq: 528.0
#
# - "step": giữ hành vi cũ (mỗi stage 1 tần số cố định).
# - "glide": nội suy tần số mượt giữa các stage xung quanh biên (early/late phần trăm của stage).
#
# Sử dụng gợi ý:
#
#   from src.core.frequency_journey import build_frequency_journey
#
#   fj = build_frequency_journey(user_options, total_ticks=None)
#
#   # Lấy tần số dạng step (hành vi cũ):
#   f_step = fj.get_freq_for_t_norm(t_norm, default_freq=default_solf)
#
#   # Nếu muốn lấy tần số chuyển mượt:
#   f_glide = fj.get_freq_for_t_norm(t_norm, default_freq=default_solf, smooth=True)
#
# Nếu bạn vẫn muốn tick-based như bản cũ:
#   fj = build_frequency_journey(user_options, total_ticks=total_ticks)
#   stage = fj.get_stage_at_tick(current_tick)

from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
import math

@dataclass
class FrequencyStage:
    """Đại diện cho một giai đoạn tần số trong hành trình."""

    index: int
    label: str

    # Phần trăm nguyên bản do user nhập (0.0..1.0 hoặc 0..100)
    raw_percent: float

    # Phần trăm sau chuẩn hóa (tổng tất cả stage = 1.0)
    norm_percent: float

    # Miền thời gian chuẩn hóa (0..1) mà stage này chiếm
    # - start_norm = tổng norm_percent các stage trước
    # - end_norm   = start_norm + norm_percent
    start_norm: float
    end_norm: float

    # Tần số mục tiêu (Hz), dùng làm Solfeggio hoặc "healing tone"
    base_freq: float

    # Thuộc tính legacy để vẫn tương thích với code cũ
    start_tick: int = 0
    end_tick: int = 0
    shift_semitones: int = 0

    def calculate_shift(self, root_base_note: int = 60) -> int:
        """
        Tính toán số bán cung cần dịch chuyển (Legacy Shift Mode).

        root_base_note: nốt gốc trung tâm để neo (thường là C4 = 60).

        Lưu ý:
        - Đây là helper phục vụ các code cũ có thể vẫn dùng "shift_semitones".
        - Hệ thống Tuning V3 hiện tại ưu tiên dùng TuningCore thay vì shift tay.
        """
        if self.base_freq <= 0:
            return 0

        # Note MIDI float của tần số mục tiêu
        midi_float = 69 + 12 * math.log2(self.base_freq / 440.0)
        target_note = int(round(midi_float))

        # So sánh với nốt gốc trung tâm (thường là C4=60)
        octave_diff = int(round((target_note - root_base_note) / 12.0))
        return octave_diff * 12

    def contains_t_norm(self, t_norm: float) -> bool:
        """Kiểm tra t_norm (0..1) có thuộc stage này không."""
        if t_norm < 0.0 or t_norm > 1.0:
            return False
        # end_norm của stage cuối thường = 1.0, nên cho phép t_norm == end_norm cho stage cuối
        if self.index == 0:
            # cho phép t_norm == 0.0
            return self.start_norm <= t_norm < self.end_norm or (
                self.end_norm == 1.0 and t_norm == 1.0
            )
        return self.start_norm <= t_norm < self.end_norm or (
            self.end_norm == 1.0 and t_norm == 1.0
        )

@dataclass
class FrequencyJourney:
    """Chứa toàn bộ lộ trình thay đổi tần số (Solf Journey)."""

    enabled: bool
    stages: List[FrequencyStage]

    # PHASE 3: cách chuyển giữa các stage
    transition_mode: str = "step"   # "step" | "glide"
    glide_ratio: float = 0.0        # 0..0.5 – tỉ lệ mỗi stage dùng để crossfade ở đầu/cuối

    # =========================
    # Helpers: t_norm-based API
    # =========================

    def is_enabled(self) -> bool:
        return self.enabled and bool(self.stages)

    def get_stage_for_t_norm(self, t_norm: float) -> Optional[FrequencyStage]:
        """
        Tìm stage tương ứng với vị trí t_norm (0..1) trong bài.

        - Nếu Journey tắt hoặc không có stage -> None.
        - Nếu t_norm < 0 -> coi như 0.
        - Nếu t_norm > 1 -> coi như 1.
        - Nếu ngoài các stage -> stage cuối.
        """
        if not self.is_enabled():
            return None

        t = min(max(t_norm, 0.0), 1.0)

        for stage in self.stages:
            if stage.contains_t_norm(t):
                return stage

        # Nếu không match (do rounding), trả về stage cuối
        return self.stages[-1]

    def _get_neighbor_indices(self, idx: int) -> Tuple[Optional[int], Optional[int]]:
        """Trả về index stage trước và sau (nếu có)."""
        prev_idx = idx - 1 if idx > 0 else None
        next_idx = idx + 1 if idx < len(self.stages) - 1 else None
        return prev_idx, next_idx

    def get_freq_for_t_norm(
        self,
        t_norm: float,
        default_freq: Optional[float] = None,
        smooth: bool = False,
    ) -> Optional[float]:
        """
        Trả về tần số tại t_norm.

        - Nếu smooth=False hoặc transition_mode="step":
            → Hành vi cũ: trả về base_freq của stage chứa t_norm.
        - Nếu smooth=True và transition_mode="glide":
            → Nội suy mượt giữa các stage xung quanh biên, dựa trên glide_ratio.
        """
        stage = self.get_stage_for_t_norm(t_norm)
        if stage is None:
            return default_freq

        base = stage.base_freq if stage.base_freq > 0 else default_freq

        # Nếu không bật glide hoặc thiếu dữ liệu → dùng base như cũ
        if (
            not smooth
            or self.transition_mode != "glide"
            or len(self.stages) <= 1
            or self.glide_ratio <= 0.0
        ):
            return base

        t = min(max(t_norm, 0.0), 1.0)
        span = max(stage.end_norm - stage.start_norm, 1e-6)

        # Tỉ lệ stage dùng để crossfade mỗi bên (0..0.5)
        g = max(0.0, min(float(self.glide_ratio), 0.5))
        if g <= 0.0:
            return base

        # Miền crossfade ở đầu & cuối stage
        left_window_end = stage.start_norm + span * g
        right_window_start = stage.end_norm - span * g

        idx = stage.index
        prev_idx, next_idx = self._get_neighbor_indices(idx)

        # LEFT CROSSFADE: từ stage trước -> stage hiện tại
        if prev_idx is not None and stage.start_norm <= t < left_window_end:
            prev_stage = self.stages[prev_idx]
            f1 = prev_stage.base_freq if prev_stage.base_freq > 0 else default_freq
            f2 = stage.base_freq if stage.base_freq > 0 else default_freq
            if f1 is None or f2 is None:
                return base
            # pos: 0 tại start_norm, 1 tại left_window_end
            pos = (t - stage.start_norm) / max(left_window_end - stage.start_norm, 1e-6)
            return f1 + (f2 - f1) * pos

        # RIGHT CROSSFADE: từ stage hiện tại -> stage sau
        if next_idx is not None and right_window_start <= t <= stage.end_norm:
            next_stage = self.stages[next_idx]
            f1 = stage.base_freq if stage.base_freq > 0 else default_freq
            f2 = next_stage.base_freq if next_stage.base_freq > 0 else default_freq
            if f1 is None or f2 is None:
                return base
            # pos: 0 tại right_window_start, 1 tại end_norm
            pos = (t - right_window_start) / max(stage.end_norm - right_window_start, 1e-6)
            return f1 + (f2 - f1) * pos

        # Khu vực "giữa" stage: giữ tần số stage
        return base

    # Helper thuận tiện: luôn trả về dạng glide nếu đang ở mode "glide"
    def get_smooth_freq_for_t_norm(
        self,
        t_norm: float,
        default_freq: Optional[float] = None,
    ) -> Optional[float]:
        """
        Helper: nếu transition_mode="glide" thì dùng nội suy,
        nếu không thì hành vi y chang get_freq_for_t_norm(step).
        """
        smooth = self.transition_mode == "glide"
        return self.get_freq_for_t_norm(t_norm, default_freq=default_freq, smooth=smooth)

    # =========================
    # Helpers: tick-based API (legacy)
    # =========================

    def get_stage_at_tick(self, tick: int) -> Optional[FrequencyStage]:
        """
        Tìm stage tương ứng với thời điểm tick (legacy).

        Lưu ý:
        - Chỉ hoạt động đúng nếu build_frequency_journey(...) được gọi với total_ticks != None.
        - Nếu không gán start_tick/end_tick, giá trị này sẽ là 0, nên chỉ dùng trong code cũ.
        """
        if not self.is_enabled():
            return None
        for stage in self.stages:
            if stage.start_tick <= tick < stage.end_tick:
                return stage
        # Nếu quá cuối cùng thì giữ stage cuối
        return self.stages[-1] if self.stages else None

# =========================
# Builder chính
# =========================

def _parse_duration_percent(raw_val: float) -> float:
    """
    Chuẩn hóa giá trị duration_pct do user nhập.

    - Nếu raw_val <= 0 -> 0.
    - Nếu 0 < raw_val <= 1.0: coi là fraction (0.4 = 40%).
    - Nếu raw_val  > 1.0: coi là percent (40.0 = 40%) -> chia 100.
    """
    try:
        v = float(raw_val)
    except (ValueError, TypeError):
        return 0.0
    if v <= 0.0:
        return 0.0
    if v <= 1.0:
        return v
    return v / 100.0

def build_frequency_journey(
    user_options: Dict[str, Any],
    total_ticks: Optional[int] = None,
) -> FrequencyJourney:
    """
    Parser chính: Đọc cấu hình từ user_options và xây dựng object FrequencyJourney.

    user_options["frequency_journey"] format:
    {
        "enabled": true/false,
        "transition_mode": "step" | "glide",
        "glide_ratio": 0.15,
        "stages": [
            {
                "label": "Stage 1 (432Hz)",
                "duration_pct": 0.5  # hoặc 50 / 50.0, đều hiểu là 50%
                "freq": 432.0
            },
            ...
        ]
    }

    - Nội bộ chuẩn hóa:
        + Chuyển duration_pct -> raw_percent (0..1).
        + Chuẩn hóa thành norm_percent sao cho tổng = 1.0.
        + Tính start_norm/end_norm cho từng stage.
        + Stage cuối luôn bù phần còn lại để đảm bảo end_norm == 1.0.
    - Nếu total_ticks != None:
        + Gán start_tick/end_tick dựa trên norm_percent, để tương thích code cũ.
    """
    raw_data = user_options.get("frequency_journey", {})

    # 1. Check Enabled
    if not raw_data or not raw_data.get("enabled", False):
        return FrequencyJourney(enabled=False, stages=[])

    raw_stages = raw_data.get("stages", [])
    if not raw_stages:
        return FrequencyJourney(enabled=False, stages=[])

    # PHASE 3: đọc mode & glide_ratio (option)
    raw_mode = str(raw_data.get("transition_mode", "step") or "step").strip().lower()
    if raw_mode not in ("step", "glide"):
        raw_mode = "step"

    try:
        raw_glide = float(raw_data.get("glide_ratio", 0.0))
    except (TypeError, ValueError):
        raw_glide = 0.0
    # Clamp 0..0.5 (tối đa 50% mỗi stage dành cho crossfade)
    if raw_glide < 0.0:
        raw_glide = 0.0
    if raw_glide > 0.5:
        raw_glide = 0.5

    # 2. Parse percent (0..1) từ duration_pct
    parsed_percents: List[float] = []
    for s_data in raw_stages:
        raw_pct = s_data.get("duration_pct", 0.0)
        parsed_percents.append(_parse_duration_percent(raw_pct))

    # Nếu tất cả = 0 -> phân chia đều
    if all(p <= 0.0 for p in parsed_percents):
        n = len(raw_stages)
        if n == 0:
            return FrequencyJourney(enabled=False, stages=[])
        parsed_percents = [1.0 / n for _ in range(n)]

    # 3. Chuẩn hóa để tổng = 1.0
    sum_pct = sum(parsed_percents)
    if sum_pct <= 0.0:
        sum_pct = 1.0
    norm_percents = [p / sum_pct for p in parsed_percents]

    # 4. Build stages với start_norm/end_norm
    final_stages: List[FrequencyStage] = []

    current_norm = 0.0
    n_stages = len(raw_stages)
    for idx, s_data in enumerate(raw_stages):
        label = s_data.get("label", f"Stage {idx + 1}")
        freq = float(s_data.get("freq", 432.0))

        raw_pct = parsed_percents[idx]
        norm_pct = norm_percents[idx]

        # Stage cuối bù đủ 1.0 (tránh lỗi do rounding)
        if idx == n_stages - 1:
            start_norm = current_norm
            end_norm = 1.0
        else:
            start_norm = current_norm
            end_norm = current_norm + norm_pct

        stage = FrequencyStage(
            index=idx,
            label=label,
            raw_percent=raw_pct,
            norm_percent=norm_pct,
            start_norm=start_norm,
            end_norm=end_norm,
            base_freq=freq,
        )

        final_stages.append(stage)
        current_norm = end_norm

    # 5. Nếu cần tick-based (legacy): map theo total_ticks
    if total_ticks is not None and total_ticks > 0:
        last_end_tick = 0
        for idx, stage in enumerate(final_stages):
            start_tick = int(round(stage.start_norm * total_ticks))
            if idx == len(final_stages) - 1:
                end_tick = total_ticks
            else:
                end_tick = int(round(stage.end_norm * total_ticks))

            # Đảm bảo không lùi thời gian
            if start_tick < last_end_tick:
                start_tick = last_end_tick
            if end_tick < start_tick:
                end_tick = start_tick

            stage.start_tick = start_tick
            stage.end_tick = end_tick
            last_end_tick = end_tick

            # Pre-compute shift (Dựa trên mốc C4=60) – Legacy
            stage.shift_semitones = stage.calculate_shift(root_base_note=60)

    return FrequencyJourney(
        enabled=True,
        stages=final_stages,
        transition_mode=raw_mode,
        glide_ratio=raw_glide,
    )
