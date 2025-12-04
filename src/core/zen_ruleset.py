from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple, TYPE_CHECKING

# Các core đã có trong hệ thống
from src.core.tempo_breath import TempoMap

# Import mềm – giúp tránh lỗi nếu chưa có Safe Harmony Engine
try:  # pragma: no cover
    from src.core.safe_harmony_engine import SafeHarmonyEngine  # type: ignore
except ImportError:  # pragma: no cover
    SafeHarmonyEngine = None  # type: ignore

if TYPE_CHECKING:  # Chỉ cho type-checker, runtime không bắt buộc
    from src.core.frequency_journey import FrequencyJourney
    from src.core.brainwave_journey import BrainwaveJourney
    from src.core.tuning_core import TuningPlan
    from src.core.zen_arc_matrix import ZenArcMatrix
    from src.core.breath_sync import BreathSyncManager
    from src.core.register_manager import RegisterManager
    from src.core.safety_filter import SafetyFilter
    from src.utils.activity_map import ActivityMap
    from src.core.structure_builder import Segment

# =========================
# 1. DATA CLASSES
# =========================

@dataclass
class PhaseContext:
    """
    Snapshot ngắn gọn về "ngữ cảnh Zen" tại một tick cụ thể.

    Engine có thể dùng để quyết định:
      - giảm density khuya,
      - tránh jump mạnh ở Integration,
      - xử lý đặc biệt breakdown, v.v.
    """

    tick: int
    phase_name: str
    section_type: str
    phase_energy: float
    breath_index: int
    breath_phase: str  # "in", "out", "hold", ...
    t_norm: float      # 0..1 vị trí tương đối trong toàn bài

    def as_meta(self) -> Dict[str, Any]:
        return {
            "tick": self.tick,
            "phase_name": self.phase_name,
            "section_type": self.section_type,
            "phase_energy": self.phase_energy,
            "breath_index": self.breath_index,
            "breath_phase": self.breath_phase,
            "t_norm": self.t_norm,
        }

@dataclass
class HarmonyContext:
    """
    Thông tin hòa âm "tối thiểu" mà mọi Engine có thể dùng chung.

    Sau này Safe Harmony Engine có thể enrich thêm:
      - allowed_tensions, avoid_tones, scale_family, mode_color...
    """

    key: str
    scale: str
    chord_name: str
    section_type: str
    phase_name: str

    def as_meta(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "scale": self.scale,
            "chord_name": self.chord_name,
            "section_type": self.section_type,
            "phase_name": self.phase_name,
        }

# =========================
# 2. ZEN RULESET CORE
# =========================

class ZenRuleSet:
    """
    ZenRuleSet – điểm truy cập duy nhất của Engine tới:
        - Breath / Phase / Zen Arc
        - Activity (should_layer_play)
        - Safety (SafetyFilter)
        - Register (RegisterManager)
        - Harmony (SafeHarmonyEngine – nếu có)
        - Journey (Frequency / Brainwave – context)

    Mục tiêu:
        - Engine không phải biết chi tiết từng core module.
        - Mọi nâng cấp luật global chỉ cần chạm vào đây.
    """

    def __init__(
        self,
        user_options: Dict[str, Any],
        tempo_map: TempoMap,
        zen_arc_matrix: "ZenArcMatrix",
        breath_sync: "BreathSyncManager",
        activity_map: "ActivityMap",
        register_manager: "RegisterManager",
        safety_filter: "SafetyFilter",
        tuning_plan: Optional["TuningPlan"] = None,
        frequency_journey: Optional["FrequencyJourney"] = None,
        brainwave_journey: Optional["BrainwaveJourney"] = None,
    ) -> None:
        self.user_options = user_options or {}
        self.tempo_map = tempo_map
        self.zen_arc = zen_arc_matrix
        self.breath_sync = breath_sync
        self.activity_map = activity_map
        self.register_manager = register_manager
        self.safety_filter = safety_filter
        self.tuning_plan = tuning_plan
        self.frequency_journey = frequency_journey
        self.brainwave_journey = brainwave_journey

        rm_conf = self.user_options.get("zen_ruleset", {}) or {}
        self.debug: bool = bool(rm_conf.get("debug", False))

        # Khởi tạo Safe Harmony Engine nếu có
        self.safe_harmony = None
        if SafeHarmonyEngine is not None:
            try:
                self.safe_harmony = SafeHarmonyEngine(
                    user_options=self.user_options,
                    tuning_plan=self.tuning_plan,
                )
            except Exception:
                # Nếu SafeHarmonyEngine chưa ổn, Ruleset vẫn hoạt động bình thường
                self.safe_harmony = None

    # =========================
    # 3. CONTEXT HELPERS
    # =========================

    def _compute_t_norm(self, tick: int, total_ticks: Optional[int]) -> float:
        if not total_ticks or total_ticks <= 0:
            return 0.0
        return max(0.0, min(1.0, float(tick) / float(total_ticks)))

    def get_phase_context(
        self,
        tick: int,
        segment: Optional["Segment"] = None,
        total_ticks: Optional[int] = None,
    ) -> PhaseContext:
        """
        Truy xuất snapshot phase/breath tại 1 tick.

        - phase_name / phase_energy / section_type: từ ZenArcMatrix + Segment.
        - breath_index / breath_phase: từ BreathSyncManager.
        - t_norm: 0..1 (vị trí trong bài) – dùng để sync với Journey.

        Luôn trả về PhaseContext hợp lệ, với default an toàn nếu thiếu dữ liệu.
        """
        t = int(tick)

        # --- Zen Arc / Section ---
        phase_name = "unknown"
        phase_energy = 0.5
        section_type = "unknown"

        # Ưu tiên lấy từ Segment nếu có
        if segment is not None:
            phase_name = getattr(segment, "phase_name", phase_name)
            section_type = getattr(segment, "section_type", section_type)

        # Cố gắng hỏi thêm từ ZenArcMatrix nếu có API
        try:
            # Giả định: zen_arc_matrix có method get_phase_info(tick) -> dict
            info = getattr(self.zen_arc, "get_phase_info", None)
            if callable(info):
                arc_info = info(t)
                phase_energy = float(arc_info.get("energy", phase_energy))
                # phase_name/section_type có thể được override
                phase_name = arc_info.get("phase_name", phase_name)
                section_type = arc_info.get("section_type", section_type)
        except Exception:
            pass

        # --- Breath Sync ---
        breath_index = 0
        breath_phase = "unknown"
        try:
            b_info = self.breath_sync.get_breath_info_at_tick(t)
            # Kỳ vọng b_info là dict hoặc dataclass có attr
            if isinstance(b_info, dict):
                breath_index = int(b_info.get("breath_index", 0))
                breath_phase = str(b_info.get("breath_phase", "unknown"))
            else:
                breath_index = int(getattr(b_info, "breath_index", 0))
                breath_phase = str(getattr(b_info, "breath_phase", "unknown"))
        except Exception:
            pass

        # --- t_norm ---
        t_norm = self._compute_t_norm(t, total_ticks)

        return PhaseContext(
            tick=t,
            phase_name=phase_name,
            section_type=section_type,
            phase_energy=phase_energy,
            breath_index=breath_index,
            breath_phase=breath_phase,
            t_norm=t_norm,
        )

    def get_harmony_context(
        self,
        segment: Optional["Segment"],
        effective_key: str,
        scale: str,
    ) -> HarmonyContext:
        """
        Đưa về thông tin hòa âm cơ bản mà mọi Engine dùng được.

        - key / scale      : từ Zen Core (effective_key / composition_scale).
        - chord_name       : từ Segment (vd "Imaj7", "IV", "V/vi"...).
        - section_type     : grounded / immersion / breakdown / ...
        - phase_name       : "Grounding", "Immersion", ...
        """
        key = effective_key or "C"
        sc = scale or "major"
        chord_name = "I"
        section_type = "unknown"
        phase_name = "unknown"

        if segment is not None:
            chord_name = getattr(segment, "chord_name", chord_name) or chord_name
            section_type = getattr(segment, "section_type", section_type)
            phase_name = getattr(segment, "phase_name", phase_name)

        return HarmonyContext(
            key=key,
            scale=sc,
            chord_name=chord_name,
            section_type=section_type,
            phase_name=phase_name,
        )

    # =========================
    # 4. ACTIVITY & REGISTER API
    # =========================

    def should_layer_play(
        self,
        layer: str,
        tick: int,
        segment: Optional["Segment"] = None,
    ) -> bool:
        """
        Wrapper mỏng quanh ActivityMap:
            - Hỏi: "Ở tick này, layer có nên nói không?"

        Lợi ích:
            - Engine không cần biết chi tiết ActivityMap API.
            - Sau này nếu thêm luật phase/breath/harmony để tắt/mở lớp,
              chỉ cần sửa ở đây.
        """
        t = int(tick)
        try:
            # Kỳ vọng ActivityMap có method:
            #   is_active(layer, tick, segment=None) -> bool
            fn = getattr(self.activity_map, "is_active", None)
            if callable(fn):
                return bool(fn(layer, t, segment))
        except Exception:
            pass
        # Fallback: luôn cho phép nếu ActivityMap không rõ
        return True

    def get_register_band(self, layer: str) -> Tuple[int, int]:
        """
        Trả về (low, high) MIDI register cho layer, dựa trên RegisterManager.
        """
        band = self.register_manager.get_band(layer)
        return band.min_pitch, band.max_pitch

    # =========================
    # 5. MAIN NOTE FILTER PIPELINE
    # =========================

    def filter_note(
        self,
        layer: str,
        pitch: int,
        velocity: int,
        tick: int,
        segment: Optional["Segment"] = None,
        role: Optional[str] = None,
        total_ticks: Optional[int] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, int, bool, Dict[str, Any]]:
        """
        Áp dụng toàn bộ luật "cứng" cho một note, theo thứ tự:

            1) Build PhaseContext + HarmonyContext.
            2) (Phase B) Có thể gọi Safe Harmony Engine (per-note) nếu muốn.
            3) Gọi SafetyFilter.apply_note(...) với meta đầy đủ:
                 - phase_name / section_type / phase_energy
                 - breath_index / breath_phase
                 - chord_name / key / scale
                 - t_norm (0..1)
                 - layer / role
                 - journey index (tùy chọn)
            4) Trả về:
                 safe_pitch, safe_velocity, allow, info

        Đây là API chính mà các Engine nên dùng cho mọi note-out.
        """
        t = int(tick)
        raw_pitch = int(pitch)
        raw_velocity = int(velocity)

        # 1) Context
        phase_ctx = self.get_phase_context(
            tick=t,
            segment=segment,
            total_ticks=total_ticks,
        )
        harm_ctx = self.get_harmony_context(
            segment=segment,
            effective_key=self._get_effective_key(),
            scale=self._get_effective_scale(),
        )

        # 2) Journey context (tùy chọn, để meta cho Binaural/Drone/Harm tham khảo)
        freq_stage_label = None
        brain_stage_label = None

        if self.frequency_journey is not None:
            try:
                s = self.frequency_journey.get_stage_at_tick(t)
                if s is not None:
                    freq_stage_label = getattr(s, "label", None)
            except Exception:
                pass

        if self.brainwave_journey is not None:
            try:
                s = self.brainwave_journey.get_stage_at_tick(t)
                if s is not None:
                    brain_stage_label = getattr(s, "label", None)
            except Exception:
                pass

        # 3) Build meta cho SafetyFilter
        meta: Dict[str, Any] = {
            "layer": layer,
            "role": role,
            "phase": phase_ctx.as_meta(),
            "harmony": harm_ctx.as_meta(),
            "freq_stage_label": freq_stage_label,
            "brain_stage_label": brain_stage_label,
        }
        if segment is not None:
            meta["segment_index"] = getattr(segment, "index", None)
            meta["segment_id"] = getattr(segment, "id", None)

        if extra_meta:
            meta.update(extra_meta)

        # 4) Phase B: hook Safe Harmony per-note (chưa can thiệp pitch, chỉ enrich info)
        #    Sau này có thể mở rộng:
        #        adjusted_pitch, harmony_info = self.safe_harmony.filter_note(...)
        #    Hiện tại: giữ nguyên để không phá các engine đang chạy ổn.
        harmony_info: Dict[str, Any] = {}
        if self.safe_harmony is not None:
            try:
                # Kỳ vọng SafeHarmonyEngine có method:
                #   inspect_note(layer, pitch, velocity, phase_ctx, harm_ctx) -> dict
                inspect = getattr(self.safe_harmony, "inspect_note", None)
                if callable(inspect):
                    harmony_info = inspect(
                        layer=layer,
                        pitch=raw_pitch,
                        velocity=raw_velocity,
                        phase_ctx=phase_ctx,
                        harmony_ctx=harm_ctx,
                    ) or {}
            except Exception:
                harmony_info = {}

        # 5) Gọi SafetyFilter – đây là nơi quyết định clamp/chặn note
        safe_pitch, safe_vel, allow, info = self.safety_filter.apply_note(
            layer=layer,
            pitch=raw_pitch,
            velocity=raw_velocity,
            tick=t,
            meta=meta,
        )

        # Gắn thêm harmony_info + context vào info để log/debug
        info = dict(info or {})
        info["harmony_info"] = harmony_info
        info["phase"] = phase_ctx.as_meta()
        info["harmony"] = harm_ctx.as_meta()
        info["freq_stage_label"] = freq_stage_label
        info["brain_stage_label"] = brain_stage_label
        info["layer_role"] = role

        if self.debug:
            print(
                f"[ZenRuleSet] layer={layer}, tick={t}, "
                f"pitch_in={raw_pitch}->out={safe_pitch}, "
                f"vel_in={raw_velocity}->out={safe_vel}, allow={allow}, "
                f"phase={phase_ctx.phase_name}, chord={harm_ctx.chord_name}"
            )

        return safe_pitch, safe_vel, allow, info

    # =========================
    # 6. INTERNAL HELPERS
    # =========================

    def _get_effective_key(self) -> str:
        """
        Lấy key hiệu lực cho HarmonyContext:
            - Ưu tiên TuningPlan.new_key nếu có.
            - Fallback: user_options["key"] hoặc "C".
        """
        if self.tuning_plan is not None:
            key = getattr(self.tuning_plan, "new_key", None)
            if key:
                return str(key)
        key_opt = self.user_options.get("key", "C")
        return str(key_opt)

    def _get_effective_scale(self) -> str:
        """
        Lấy scale hiệu lực:
            - Hiện tại giữ nguyên user_options["scale"] (vd "major", "minor").
            - Sau này có thể suy ra từ TuningCore/StructureBuilder nếu cần.
        """
        sc = self.user_options.get("scale", "major")
        return str(sc)
