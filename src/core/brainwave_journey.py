from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

# =========================
# Mặc định mapping BAND -> BEAT_HZ
# =========================

BRAINWAVE_BAND_DEFAULTS: Dict[str, float] = {
    "delta": 2.0,      # Deep Sleep (0.5–4 Hz) -> chọn điểm giữa
    "theta": 6.0,      # Meditation / Nidra (4–8 Hz)
    "alpha": 10.0,     # Relaxed Focus (8–12 Hz)
    "beta": 14.0,      # Alert / Thinking (12–30 Hz) -> chọn ~14 Hz
    "gamma": 40.0,     # High Gamma (30–100 Hz) -> 40 Hz thường dùng
    "schumann": 7.83,  # Schumann Resonance
}

# =========================
# Data class: BrainwaveStage
# =========================

@dataclass
class BrainwaveStage:
    """Đại diện cho một giai đoạn sóng não trong hành trình."""

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

    # Band & Beat
    band: str          # "delta" / "theta" / "alpha" / ... / "custom"
    beat_hz: float     # Hz thực tế sẽ dùng cho BinauralEngine

    # Legacy: tick-based để tương thích code cũ (nếu cần)
    start_tick: int = 0
    end_tick: int = 0

    def contains_t_norm(self, t_norm: float) -> bool:
        """Kiểm tra t_norm (0..1) có thuộc stage này không."""
        if t_norm < 0.0 or t_norm > 1.0:
            return False
        # Cho phép t_norm == end_norm cho stage cuối (end_norm = 1.0)
        if self.index == 0:
            return self.start_norm <= t_norm < self.end_norm or (
                self.end_norm == 1.0 and t_norm == 1.0
            )
        return self.start_norm <= t_norm < self.end_norm or (
            self.end_norm == 1.0 and t_norm == 1.0
        )

# =========================
# Data class: BrainwaveJourney
# =========================

@dataclass
class BrainwaveJourney:
    """Chứa toàn bộ lộ trình thay đổi sóng não (Binaural Beat Journey)."""

    enabled: bool
    lock_to_frequency: bool
    stages: List[BrainwaveStage]

    # PHASE 3: cách chuyển giữa các stage
    transition_mode: str = "step"   # "step" | "glide"
    glide_ratio: float = 0.0        # 0..0.5 – tỉ lệ mỗi stage dùng để crossfade ở đầu/cuối

    # --------- t_norm-based API ---------

    def is_enabled(self) -> bool:
        return self.enabled and bool(self.stages)

    def get_stage_for_t_norm(self, t_norm: float) -> Optional[BrainwaveStage]:
        """
        Tìm stage tương ứng với vị trí t_norm (0..1) trong bài.

        - Nếu Journey tắt hoặc không có stage -> None.
        - Nếu t_norm < 0 -> coi như 0.
        - Nếu t_norm > 1 -> coi như 1.
        """
        if not self.is_enabled():
            return None

        t = min(max(t_norm, 0.0), 1.0)

        for stage in self.stages:
            if stage.contains_t_norm(t):
                return stage

        # Nếu không match (do rounding), trả về stage cuối
        return self.stages[-1] if self.stages else None

    def _get_neighbor_indices(self, idx: int) -> Tuple[Optional[int], Optional[int]]:
        """Trả về index stage trước và sau (nếu có)."""
        prev_idx = idx - 1 if idx > 0 else None
        next_idx = idx + 1 if idx < len(self.stages) - 1 else None
        return prev_idx, next_idx

    def get_beat_hz_for_t_norm(
        self,
        t_norm: float,
        default_beat_hz: Optional[float] = None,
        smooth: bool = False,
    ) -> Optional[float]:
        """
        Trả về beat_hz tại t_norm.

        - Nếu smooth=False hoặc transition_mode="step":
            → Hành vi cũ: trả về beat_hz của stage chứa t_norm.
        - Nếu smooth=True và transition_mode="glide":
            → Nội suy mượt giữa các stage xung quanh biên, dựa trên glide_ratio.
        """
        stage = self.get_stage_for_t_norm(t_norm)
        if stage is None:
            return default_beat_hz

        base = stage.beat_hz if stage.beat_hz > 0 else default_beat_hz

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
            f1 = prev_stage.beat_hz if prev_stage.beat_hz > 0 else default_beat_hz
            f2 = stage.beat_hz if stage.beat_hz > 0 else default_beat_hz
            if f1 is None or f2 is None:
                return base
            # pos: 0 tại start_norm, 1 tại left_window_end
            pos = (t - stage.start_norm) / max(left_window_end - stage.start_norm, 1e-6)
            return f1 + (f2 - f1) * pos

        # RIGHT CROSSFADE: từ stage hiện tại -> stage sau
        if next_idx is not None and right_window_start <= t <= stage.end_norm:
            next_stage = self.stages[next_idx]
            f1 = stage.beat_hz if stage.beat_hz > 0 else default_beat_hz
            f2 = next_stage.beat_hz if next_stage.beat_hz > 0 else default_beat_hz
            if f1 is None or f2 is None:
                return base
            # pos: 0 tại right_window_start, 1 tại end_norm
            pos = (t - right_window_start) / max(stage.end_norm - right_window_start, 1e-6)
            return f1 + (f2 - f1) * pos

        # Khu vực "giữa" stage: giữ beat_hz stage
        return base

    def get_smooth_beat_hz_for_t_norm(
        self,
        t_norm: float,
        default_beat_hz: Optional[float] = None,
    ) -> Optional[float]:
        """
        Helper: nếu transition_mode="glide" thì dùng nội suy,
        nếu không thì hành vi y chang get_beat_hz_for_t_norm(step).
        """
        smooth = self.transition_mode == "glide"
        return self.get_beat_hz_for_t_norm(
            t_norm, default_beat_hz=default_beat_hz, smooth=smooth
        )

    # --------- tick-based API (legacy) ---------

    def get_stage_at_tick(self, tick: int) -> Optional[BrainwaveStage]:
        """
        Tìm stage tương ứng với thời điểm tick (legacy).

        Lưu ý:
        - Chỉ hoạt động đúng nếu build_brainwave_journey(...) được gọi với total_ticks != None.
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
# Helpers
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

def _resolve_stage_beat_hz(
    stage_cfg: Dict[str, Any],
    global_band: Optional[str],
    global_custom_hz: Optional[float],
) -> float:
    """
    Xác định beat_hz cho một stage:

    Ưu tiên:
    1) stage_cfg["beat_hz"] nếu > 0
    2) band (stage_cfg["band"] hoặc global_band) map qua BRAINWAVE_BAND_DEFAULTS
    3) global_custom_hz (binaural_beat_hz từ user_options nếu > 0)
    4) Alpha mặc định (10.0 Hz)
    """
    band = (stage_cfg.get("band") or global_band or "alpha").lower()
    beat_hz = stage_cfg.get("beat_hz")

    # Ưu tiên custom beat_hz
    if beat_hz is not None:
        try:
            bh = float(beat_hz)
            if bh > 0:
                return bh
        except (ValueError, TypeError):
            pass

    # Nếu có band hợp lệ -> dùng default map
    if band in BRAINWAVE_BAND_DEFAULTS:
        return BRAINWAVE_BAND_DEFAULTS[band]

    # Nếu có global_custom_hz (binaural_beat_hz) -> dùng
    if global_custom_hz is not None and global_custom_hz > 0:
        return float(global_custom_hz)

    # Fallback: alpha
    return BRAINWAVE_BAND_DEFAULTS.get("alpha", 10.0)

# =========================
# Builder chính
# =========================

def build_brainwave_journey(
    user_options: Dict[str, Any],
    total_ticks: Optional[int] = None,
) -> BrainwaveJourney:
    """
    Parser chính: Đọc cấu hình từ user_options và xây dựng BrainwaveJourney.

    user_options["brainwave_journey"] format:
    {
        "enabled": true/false,
        "lock_to_frequency": true/false,
        "transition_mode": "step" | "glide",
        "glide_ratio": 0.15,
        "stages": [
            {
                "label": "Stage 1 - Deep Delta",
                "duration_pct": 40.0,   # hoặc 0.4
                "band": "delta",        # optional
                "beat_hz": 2.0          # optional
            },
            ...
        ]
    }

    Legacy support:
    - Nếu không có brainwave_journey.stages nhưng có:
        + brainwave_enable = True
        + brainwave_band / binaural_beat_hz
      -> tạo 1 stage static cho toàn bài.
    """
    raw_bw = user_options.get("brainwave_journey", {})
    global_enable = bool(user_options.get("brainwave_enable", False))

    enabled = bool(raw_bw.get("enabled", False)) and global_enable
    lock_to_frequency = bool(raw_bw.get("lock_to_frequency", False))

    # PHASE 3: đọc mode & glide_ratio (option)
    raw_mode = str(raw_bw.get("transition_mode", "step") or "step").strip().lower()
    if raw_mode not in ("step", "glide"):
        raw_mode = "step"

    try:
        raw_glide = float(raw_bw.get("glide_ratio", 0.0))
    except (TypeError, ValueError):
        raw_glide = 0.0
    # Clamp 0..0.5 (tối đa 50% mỗi stage dành cho crossfade)
    if raw_glide < 0.0:
        raw_glide = 0.0
    if raw_glide > 0.5:
        raw_glide = 0.5

    # Nếu không bật -> trả object tắt, vẫn giữ lock_to_frequency để Zen Core biết config
    if not enabled:
        return BrainwaveJourney(
            enabled=False,
            lock_to_frequency=lock_to_frequency,
            stages=[],
            transition_mode=raw_mode,
            glide_ratio=raw_glide,
        )

    raw_stages = raw_bw.get("stages", [])

    # =========================
    # Case 1: Không có stage -> tạo 1 stage static theo band/hz global
    # =========================
    if not raw_stages:
        global_band = user_options.get("brainwave_band", "alpha")
        global_hz_val = user_options.get("binaural_beat_hz", None)
        try:
            global_hz = float(global_hz_val) if global_hz_val is not None else None
        except (ValueError, TypeError):
            global_hz = None

        beat_hz = _resolve_stage_beat_hz({}, global_band, global_hz)

        default_stage = BrainwaveStage(
            index=0,
            label="Brainwave (Static)",
            raw_percent=1.0,
            norm_percent=1.0,
            start_norm=0.0,
            end_norm=1.0,
            band=str(global_band),
            beat_hz=float(beat_hz),
        )

        if total_ticks is not None and total_ticks > 0:
            default_stage.start_tick = 0
            default_stage.end_tick = int(total_ticks)

        return BrainwaveJourney(
            enabled=True,
            lock_to_frequency=lock_to_frequency,
            stages=[default_stage],
            transition_mode=raw_mode,
            glide_ratio=raw_glide,
        )

    # =========================
    # Case 2: Có nhiều stage -> normalize percent
    # =========================

    parsed_percents: List[float] = []
    for s_cfg in raw_stages:
        raw_pct = s_cfg.get("duration_pct", 0.0)
        parsed_percents.append(_parse_duration_percent(raw_pct))

    # Nếu tất cả = 0 -> phân chia đều
    if all(p <= 0.0 for p in parsed_percents):
        n = len(raw_stages)
        if n == 0:
            return BrainwaveJourney(
                enabled=False,
                lock_to_frequency=lock_to_frequency,
                stages=[],
                transition_mode=raw_mode,
                glide_ratio=raw_glide,
            )
        parsed_percents = [1.0 / n for _ in range(n)]

    # Chuẩn hóa để tổng = 1.0
    sum_pct = sum(parsed_percents)
    if sum_pct <= 0.0:
        sum_pct = 1.0
    norm_percents = [p / sum_pct for p in parsed_percents]

    # Thông tin global
    global_band = user_options.get("brainwave_band", "alpha")
    global_hz_val = user_options.get("binaural_beat_hz", None)
    try:
        global_hz = float(global_hz_val) if global_hz_val is not None else None
    except (ValueError, TypeError):
        global_hz = None

    stages: List[BrainwaveStage] = []
    current_norm = 0.0
    n_stages = len(raw_stages)

    for idx, s_cfg in enumerate(raw_stages):
        label = s_cfg.get("label", f"Brainwave Stage {idx + 1}")
        raw_pct = parsed_percents[idx]
        norm_pct = norm_percents[idx]

        # Stage cuối bù đủ 1.0 (tránh lỗi do rounding)
        if idx == n_stages - 1:
            start_norm = current_norm
            end_norm = 1.0
        else:
            start_norm = current_norm
            end_norm = current_norm + norm_pct

        beat = _resolve_stage_beat_hz(s_cfg, global_band, global_hz)
        band = (s_cfg.get("band") or global_band or "alpha")

        stage = BrainwaveStage(
            index=idx,
            label=label,
            raw_percent=raw_pct,
            norm_percent=norm_pct,
            start_norm=start_norm,
            end_norm=end_norm,
            band=str(band),
            beat_hz=float(beat),
        )

        stages.append(stage)
        current_norm = end_norm

    # Map sang tick (legacy) nếu cần
    if total_ticks is not None and total_ticks > 0:
        last_end_tick = 0
        for idx, stage in enumerate(stages):
            start_tick = int(round(stage.start_norm * total_ticks))
            if idx == len(stages) - 1:
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

    return BrainwaveJourney(
        enabled=True,
        lock_to_frequency=lock_to_frequency,
        stages=stages,
        transition_mode=raw_mode,
        glide_ratio=raw_glide,
    )
