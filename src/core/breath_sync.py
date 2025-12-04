from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional, Any

# Fallback mềm cho TempoMap, để import file này không bị lỗi nếu core chưa có
try:
    from src.core.tempo_breath import TempoMap  # type: ignore
except ImportError:  # pragma: no cover
    class TempoMap:  # type: ignore
        ppq: int = 480
        breath_cycle_bars: float = 2.0

# =========================
# 1. DATA CLASSES
# =========================


@dataclass
class BreathPhaseConfig:
    """
    Cấu hình các "pha" trong một chu kỳ thở (0..1):

        valley_center:      vùng đáy / bắt đầu thở
        peak_center:        vùng đỉnh / giữa thở
        end_center:         vùng cuối / exhale kết thúc
        width:              độ rộng "vùng chấp nhận" xung quanh center
        max_shift_ratio:    tối đa được phép dịch tick (so với 1 breath length),
                            để tránh phá vỡ vị trí gốc quá nhiều.
    """

    valley_center: float = 0.15
    peak_center: float = 0.50
    end_center: float = 0.85
    width: float = 0.30
    max_shift_ratio: float = 0.25  # <= 25% độ dài breath


@dataclass
class LayerBreathRule:
    """
    Quy tắc đồng bộ cho 1 layer:

        mode:
            - "valley" : ưu tiên valley
            - "peak"   : ưu tiên peak
            - "end"    : ưu tiên end-of-breath
            - "follow" : không dịch tick, chỉ báo phase (Air, Drone...)
            - "free"   : không làm gì (bỏ qua hoàn toàn)
    """

    mode: str  # "valley" / "peak" / "end" / "follow" / "free"


@dataclass
class BreathSyncConfig:
    """
    Cấu hình tổng cho Breath Sync Manager.

    - enabled: bật/tắt hệ thống đồng bộ.
    - phase_config: map các center / width / max_shift.
    - layer_rules: quy tắc cho từng layer.
    - default_rule: khi layer không có bản ghi riêng.
    - slot_division_per_breath: chia breath thành bao nhiêu "slot" nhỏ,
      dùng để bù trừ khi nhiều nốt cùng pha trong cùng breath.
    """

    enabled: bool = True
    # Dùng default_factory để tránh mutable default error (Python 3.11+)
    phase_config: BreathPhaseConfig = field(default_factory=BreathPhaseConfig)
    layer_rules: Dict[str, LayerBreathRule] = field(default_factory=dict)
    default_rule: LayerBreathRule = field(
        default_factory=lambda: LayerBreathRule(mode="free")
    )
    slot_division_per_breath: int = 64  # 1 slot ~ 1/64 breath length

# =========================
# 2. BREATH SYNC MANAGER
# =========================


class BreathSyncManager:
    """
    BreathSyncManager:

    - Dựa trên TempoMap để tính:
        + breath_length_ticks
        + breath_index
        + phase (0..1) trong breath.

    - Cung cấp align_note(layer, start_tick...) cho Engine.
    """

    def __init__(
        self,
        tempo_map: TempoMap,
        user_options: Optional[Dict[str, Any]] = None,
        config: Optional[BreathSyncConfig] = None,
    ):
        self.tempo_map = tempo_map
        self.user_options = user_options or {}

        self.config = config or self._build_default_config()

        # Breath length (ticks) = breath_cycle_bars * 4 * ppq (giả định 4/4)
        self.ppq: int = getattr(self.tempo_map, "ppq", 480)
        self.breath_cycle_bars: float = float(
            getattr(self.tempo_map, "breath_cycle_bars", 2.0) or 2.0
        )
        self.breath_length_ticks: int = max(
            1, int(self.breath_cycle_bars * 4 * self.ppq)
        )

        # Breath Slot Allocator:
        #   key: (breath_index, phase_tag) -> count
        self._slots_used: Dict[Tuple[int, str], int] = {}

        # Debug flag
        bs_conf = self.user_options.get("breath_sync_manager", {})
        self.debug: bool = bool(bs_conf.get("debug", False))

    # ---------- CONFIG BUILDERS ----------

    def _build_default_config(self) -> BreathSyncConfig:
        """
        Default rules dựa trên scope đã thống nhất:

            Pulse  -> peak
            Melody -> valley
            Chime  -> end
            Air    -> follow (chỉ dùng phase)
            Drone  -> follow (hầu như không cần dịch)
            Harm   -> follow (đi theo harmony/Zen Arc là chính)
            Binaural -> follow (tương đối liên tục)
        """
        layer_rules = {
            "pulse": LayerBreathRule(mode="peak"),
            "melody": LayerBreathRule(mode="valley"),
            "chime": LayerBreathRule(mode="end"),
            "air": LayerBreathRule(mode="follow"),
            "drone": LayerBreathRule(mode="follow"),
            "harm": LayerBreathRule(mode="follow"),
            "binaural": LayerBreathRule(mode="follow"),
        }

        cfg = BreathSyncConfig(
            enabled=True,
            phase_config=BreathPhaseConfig(),
            layer_rules=layer_rules,
            default_rule=LayerBreathRule(mode="free"),
            slot_division_per_breath=64,
        )

        # Cho phép override từ user_options nếu muốn sau này
        # (Phase B: có thể mở rộng thêm, hiện tại giữ default sạch.)
        return cfg

    # ---------- PUBLIC API ----------

    def reset_state(self) -> None:
        """Xoá toàn bộ history slot (dùng khi bắt đầu track mới)."""
        self._slots_used.clear()

    def get_breath_position(self, tick: int) -> Tuple[int, float]:
        """
        Tính vị trí tick trong hệ "breath":

        Returns:
            breath_index: số nguyên (0, 1, 2, ...)
            phase:       0..1 (vị trí tương đối trong chu kỳ thở hiện tại)
        """
        bl = self.breath_length_ticks

        if bl <= 0:
            return 0, 0.0

        if tick < 0:
            tick = 0

        breath_index = tick // bl
        pos_in_breath = tick % bl
        phase = pos_in_breath / float(bl)

        return int(breath_index), float(phase)

    def get_phase_tag(self, phase: float) -> str:
        """
        Phân loại phase 0..1 thành "valley" / "peak" / "end" / "free"
        theo khoảng "near center".
        """
        pconf = self.config.phase_config
        w = pconf.width * 0.5  # width chia đôi cho khoảng ±

        def in_band(center: float) -> bool:
            return (center - w) <= phase <= (center + w)

        if in_band(pconf.valley_center):
            return "valley"
        if in_band(pconf.peak_center):
            return "peak"
        if in_band(pconf.end_center):
            return "end"
        return "free"

    def align_note(
        self,
        layer: str,
        start_tick: int,
        duration_ticks: Optional[int] = None,
        prefer_mode: Optional[str] = None,
    ) -> Tuple[int, str, int]:
        """
        Engine gọi hàm này để sync note với breath.

        Args:
            layer:        tên layer ("pulse", "melody", ...)
            start_tick:   tick gốc mà engine sinh ra.
            duration_ticks: không bắt buộc, để tương lai có thể phân bổ thêm.
            prefer_mode:  Nếu engine muốn override tạm thời rule cho layer này
                          ("valley" / "peak" / "end" / "follow" / "free").

        Returns:
            new_start_tick: tick sau khi đã align (hoặc giữ nguyên).
            phase_tag:      "valley" / "peak" / "end" / "free"
            breath_index:   int (0, 1, 2, ...)
        """
        # Nếu hệ thống tắt -> trả nguyên
        if not self.config.enabled:
            bi, phase = self.get_breath_position(start_tick)
            return start_tick, self.get_phase_tag(phase), bi

        rule = self._get_rule_for_layer(layer)

        # Nếu layer "free" -> không dịch tick, chỉ trả phase_tag
        if prefer_mode == "free":
            effective_mode = "free"
        elif prefer_mode is not None:
            effective_mode = prefer_mode
        else:
            effective_mode = rule.mode

        breath_index, phase = self.get_breath_position(start_tick)
        phase_tag = self.get_phase_tag(phase)

        if effective_mode in ("free", "follow"):
            # follow: không dịch, chỉ báo phase_tag để engine dùng envelope tự xử
            return start_tick, phase_tag, breath_index

        # Với "valley"/"peak"/"end": cố dịch tick đến gần mục tiêu
        target_phase = self._get_target_phase(effective_mode)
        new_tick = self._align_tick_within_breath(
            start_tick, breath_index, phase, target_phase, effective_mode
        )

        if self.debug and new_tick != start_tick:
            print(
                f"[BreathSync] layer={layer}, mode={effective_mode}, "
                f"tick {start_tick} -> {new_tick} "
                f"(breath={breath_index}, phase={phase:.3f} -> target={target_phase:.3f})"
            )

        # Sau khi align, phase_tag là mode mục tiêu (vì chúng ta cố kéo về đó)
        return new_tick, effective_mode, breath_index

    # ---------- INTERNAL HELPERS ----------

    def _get_rule_for_layer(self, layer: str) -> LayerBreathRule:
        rules = self.config.layer_rules or {}
        return rules.get(layer, self.config.default_rule)

    def _get_target_phase(self, mode: str) -> float:
        """
        Trả về center phase tương ứng mode.
        """
        pconf = self.config.phase_config
        if mode == "valley":
            return pconf.valley_center
        if mode == "peak":
            return pconf.peak_center
        if mode == "end":
            return pconf.end_center
        # "follow" / "free" dùng phase gốc; nhưng không nên gọi hàm này trong các mode đó
        return 0.0

    def _align_tick_within_breath(
        self,
        original_tick: int,
        breath_index: int,
        phase: float,
        target_phase: float,
        phase_tag: str,
    ) -> int:
        """
        Dịch tick trong cùng 1 breath sao cho gần target_phase.

        - Không dịch quá max_shift_ratio * breath_length.
        - Dùng Breath Slot Allocator để tránh nhiều nốt đè lên cùng 1 tick.
        """
        bl = self.breath_length_ticks
        pconf = self.config.phase_config
        max_shift_ticks = int(pconf.max_shift_ratio * bl)

        # tick tương ứng target_phase trong breath hiện tại
        target_pos_tick = int(target_phase * bl)
        base_tick = breath_index * bl + target_pos_tick

        # Chênh lệch nếu dịch thẳng từ original
        delta = base_tick - original_tick
        if abs(delta) > max_shift_ticks:
            # Nếu chênh lệch quá lớn -> clamp
            if delta > 0:
                base_tick = original_tick + max_shift_ticks
            else:
                base_tick = original_tick - max_shift_ticks

        # Áp dụng slot allocator để lệch nốt cùng pha
        slot_tick = self._allocate_slot(breath_index, phase_tag, base_tick)

        # Không để tick < 0
        if slot_tick < 0:
            slot_tick = 0

        return slot_tick

    def _allocate_slot(self, breath_index: int, phase_tag: str, base_tick: int) -> int:
        """
        Breath Slot Allocator:

        - key = (breath_index, phase_tag)
        - mỗi lần thêm 1 nốt trong key đó -> offset thêm slot_size_tick.

        slot_size_tick = breath_length / slot_division_per_breath
        """
        key = (breath_index, phase_tag)
        count = self._slots_used.get(key, 0)

        # Tính size của 1 slot
        div = max(1, self.config.slot_division_per_breath)
        slot_size = max(1, int(self.breath_length_ticks / div))

        offset = count * slot_size
        self._slots_used[key] = count + 1

        return base_tick + offset

    # ---------- DEBUG / INTROSPECTION ----------

    def describe(self) -> str:
        """
        Trả về chuỗi mô tả cấu hình hiện tại của BreathSyncManager.
        """
        lines = []
        lines.append(
            f"BreathSyncManager: enabled={self.config.enabled}, "
            f"breath_length_ticks={self.breath_length_ticks}"
        )
        pconf = self.config.phase_config
        lines.append(
            f"  Phases: valley={pconf.valley_center:.2f}, "
            f"peak={pconf.peak_center:.2f}, end={pconf.end_center:.2f}, "
            f"width={pconf.width:.2f}, max_shift_ratio={pconf.max_shift_ratio:.2f}"
        )
        rules = self.config.layer_rules or {}
        for layer, rule in rules.items():
            lines.append(f"  Rule[{layer}]: mode={rule.mode}")
        return "\n".join(lines)
