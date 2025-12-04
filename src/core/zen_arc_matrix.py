# Tệp: src/core/zen_arc_matrix.py
# (BETA V10.11.0) - ZEN ARC MATRIX (5-PHASE ENERGY MAP)
#
# Vai trò:
#   - Định nghĩa "Ma trận Zen Arc" 5 pha cho cả bài:
#       1. Grounding    (Ổn định, đặt nền, năng lượng thấp)
#       2. Immersion    (Thả mình, từ từ dày hơn)
#       3. Breakdown    (Tan chảy / lặng, năng lượng giảm nhưng không "tắt")
#       4. Awakening    (Nâng dần, sáng hơn nhưng vẫn Zen-safe)
#       5. Integration  (Hạ an toàn, đưa người nghe về trạng thái cân bằng)
#
#   - Là **nguồn sự thật** về pha cho:
#       + StructureBuilder (gán phase_tag cho Segment).
#       + ActivityMapV2 (chọn density/movement hợp lý theo pha).
#       + Engines (Melody/Harm/Drone/Air/Chime/Pulse/Binaural) nếu cần.
#       + FrequencyJourney / BrainwaveJourney (đồng bộ phase).
#
#   - API chính:
#       zen_arc = ZenArcMatrix(user_options)
#
#       # 1) Lấy phase theo thời gian tương đối 0..1
#       phase_def = zen_arc.get_phase_by_ratio(progress_ratio)
#
#       # 2) Lấy phase theo index segment
#       phase_def = zen_arc.get_phase_for_segment(seg_index, total_segments)
#
#       # 3) Lấy profile cho 1 layer trong 1 phase
#       prof = zen_arc.get_layer_profile(phase_def.name, layer="melody")
#         -> dict { "density_mul": float, "velocity_mul": float,
#                   "movement_bias": float, "register_bias": float }
#
# Lưu ý:
#   - File này không sinh nốt, không đụng vào MIDI.
#   - Chỉ là "bản đồ" để các bộ máy khác đọc.
#   - Phase ratio có thể override qua user_options["zen_arc"]["timeline"].

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Any

# =========================
# 1. DATA CLASSES
# =========================

@dataclass
class ZenPhaseDefinition:
    """
    Định nghĩa 1 pha trong Zen Arc.

    name:         tên pha ("grounding", "immersion", ...)
    display_name: label dễ đọc (Grounding/Immersion/...)
    index:        1..5
    start_ratio:  điểm bắt đầu trong timeline (0..1)
    end_ratio:    điểm kết thúc (0..1)

    base_energy:      0..1 (cảm giác "to/nhỏ" chung)
    movement_bias:    0..1 (0 = tĩnh, 1 = di chuyển mạnh)
    brightness_bias:  0..1 (0 = trầm/tối, 1 = sáng/cao)
    tension_bias:     0..1 (0 = consonant, 1 = tension nhiều)
    """

    name: str
    display_name: str
    index: int
    start_ratio: float
    end_ratio: float
    base_energy: float
    movement_bias: float
    brightness_bias: float
    tension_bias: float

    def contains_ratio(self, r: float) -> bool:
        return self.start_ratio <= r < self.end_ratio

    def clamp_ratio(self, r: float) -> float:
        """Clamp 0..1 cho an toàn."""
        return max(self.start_ratio, min(self.end_ratio, r))

# =========================
# 2. ZEN ARC MATRIX
# =========================

class ZenArcMatrix:
    """
    ZenArcMatrix: quản lý ma trận 5 pha + profile của từng layer.

    Thiết kế:
        - init(user_options)
        - 5 pha cố định theo thứ tự:
            1. grounding
            2. immersion
            3. breakdown
            4. awakening
            5. integration
        - Cho phép override tỉ lệ timeline qua user_options nếu cần.

    user_options (đề xuất):

        zen_arc:
          timeline:
            grounding:   [0.0, 0.18]
            immersion:   [0.18, 0.40]
            breakdown:   [0.40, 0.60]
            awakening:   [0.60, 0.82]
            integration: [0.82, 1.0]

          layer_profile:
            melody:
              grounding:   {density_mul: 0.4, velocity_mul: 0.6, movement_bias: 0.3}
              immersion:   {density_mul: 0.7, ...}
              ...

    Nếu không khai báo -> dùng default trong file.
    """

    PHASE_ORDER = ["grounding", "immersion", "breakdown", "awakening", "integration"]

    def __init__(self, user_options: Optional[Dict[str, Any]] = None):
        self.user_options: Dict[str, Any] = user_options or {}

        # Debug flag
        za_conf = self.user_options.get("zen_arc", {})
        self.debug: bool = bool(za_conf.get("debug", False))

        self.phases: List[ZenPhaseDefinition] = self._build_default_phases()
        self._apply_timeline_overrides()

        # Layer profile matrix: {layer: {phase_name: profile_dict}}
        self.layer_profiles: Dict[str, Dict[str, Dict[str, float]]] = (
            self._build_default_layer_profiles()
        )
        self._apply_layer_profile_overrides()

    # ---------- BUILD DEFAULT PHASES ----------

    def _build_default_phases(self) -> List[ZenPhaseDefinition]:
        """
        Tạo 5 pha với timeline mặc định (theo tỉ lệ 0..1).

        Default timeline (có thể chỉnh bằng user_options):
            Grounding:   0.00 - 0.18
            Immersion:   0.18 - 0.42
            Breakdown:   0.42 - 0.58
            Awakening:   0.58 - 0.82
            Integration: 0.82 - 1.00
        """
        defaults = [
            ("grounding", "Grounding", 1, 0.00, 0.18, 0.25, 0.15, 0.20, 0.05),
            ("immersion", "Immersion", 2, 0.18, 0.42, 0.55, 0.40, 0.40, 0.20),
            ("breakdown", "Breakdown", 3, 0.42, 0.58, 0.20, 0.10, 0.25, 0.10),
            ("awakening", "Awakening", 4, 0.58, 0.82, 0.60, 0.55, 0.55, 0.25),
            ("integration", "Integration", 5, 0.82, 1.00, 0.30, 0.20, 0.30, 0.10),
        ]

        phases: List[ZenPhaseDefinition] = []
        for (
            name,
            dname,
            idx,
            s,
            e,
            energy,
            move,
            bright,
            tension,
        ) in defaults:
            phases.append(
                ZenPhaseDefinition(
                    name=name,
                    display_name=dname,
                    index=idx,
                    start_ratio=s,
                    end_ratio=e,
                    base_energy=energy,
                    movement_bias=move,
                    brightness_bias=bright,
                    tension_bias=tension,
                )
            )
        return phases

    def _apply_timeline_overrides(self) -> None:
        """
        Cho phép override start/end ratio từng pha qua user_options["zen_arc"]["timeline"].

        Dạng:
            zen_arc:
              timeline:
                grounding:   [0.0, 0.20]
                immersion:   [0.20, 0.40]
                ...

        Nếu input không hợp lệ -> bỏ qua entry đó.
        """
        za_conf = self.user_options.get("zen_arc", {})
        tl_conf = za_conf.get("timeline", {})

        if not isinstance(tl_conf, dict):
            return

        name_to_phase: Dict[str, ZenPhaseDefinition] = {
            p.name: p for p in self.phases
        }

        for phase_name, pair in tl_conf.items():
            if phase_name not in name_to_phase:
                continue
            try:
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    continue
                s = float(pair[0])
                e = float(pair[1])
                s = max(0.0, min(1.0, s))
                e = max(0.0, min(1.0, e))
                if e <= s:
                    continue
                p = name_to_phase[phase_name]
                p.start_ratio = s
                p.end_ratio = e
                if self.debug:
                    print(
                        f"[ZenArc] Override timeline for phase={phase_name}: {s:.3f}-{e:.3f}"
                    )
            except Exception:
                continue

        # Optional: sort phases theo start_ratio nếu override làm đảo thứ tự
        self.phases.sort(key=lambda ph: ph.start_ratio)

    # ---------- BUILD DEFAULT LAYER PROFILES ----------

    def _build_default_layer_profiles(self) -> Dict[str, Dict[str, Dict[str, float]]]:
        """
        Tạo ma trận "profile" cho mỗi layer x mỗi phase.

        Ý nghĩa các tham số (0..1):
            density_mul:   hệ số nhân density (số nốt / mức hoạt động).
            velocity_mul:  hệ số nhân velocity (âm lượng tương đối).
            movement_bias: độ "chuyển động" (0 = ít thay đổi, 1 = liên tục).
            register_bias: xu hướng dịch register lên/xuống (0 = trầm, 1 = cao).

        Đây chỉ là "gợi ý" để ActivityMap / Engine dùng, không bắt buộc.
        """

        phases = self.PHASE_ORDER

        # Helper: tạo dict cho 1 layer
        def layer_matrix(per_phase: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, float]]:
            # Đảm bảo tất cả phases đều có entry, nếu thiếu thì fill trung bình
            default_profile = {"density_mul": 1.0, "velocity_mul": 1.0,
                               "movement_bias": 0.5, "register_bias": 0.5}
            out: Dict[str, Dict[str, float]] = {}
            for ph in phases:
                out[ph] = {**default_profile, **per_phase.get(ph, {})}
            return out

        # DRONE: chủ yếu tạo nền, ít movement, giữ khá đều
        drone = layer_matrix(
            {
                "grounding":   {"density_mul": 0.7, "velocity_mul": 0.7, "movement_bias": 0.1, "register_bias": 0.2},
                "immersion":   {"density_mul": 0.8, "velocity_mul": 0.8, "movement_bias": 0.2, "register_bias": 0.3},
                "breakdown":   {"density_mul": 0.6, "velocity_mul": 0.6, "movement_bias": 0.1, "register_bias": 0.2},
                "awakening":   {"density_mul": 0.8, "velocity_mul": 0.9, "movement_bias": 0.2, "register_bias": 0.3},
                "integration": {"density_mul": 0.6, "velocity_mul": 0.6, "movement_bias": 0.1, "register_bias": 0.2},
            }
        )

        # HARM: theo progression/Zen Arc, hơi tăng brightness ở Awakening
        harm = layer_matrix(
            {
                "grounding":   {"density_mul": 0.6, "velocity_mul": 0.6, "movement_bias": 0.3, "register_bias": 0.4},
                "immersion":   {"density_mul": 0.8, "velocity_mul": 0.7, "movement_bias": 0.4, "register_bias": 0.4},
                "breakdown":   {"density_mul": 0.4, "velocity_mul": 0.5, "movement_bias": 0.2, "register_bias": 0.3},
                "awakening":   {"density_mul": 0.9, "velocity_mul": 0.9, "movement_bias": 0.5, "register_bias": 0.5},
                "integration": {"density_mul": 0.5, "velocity_mul": 0.6, "movement_bias": 0.3, "register_bias": 0.4},
            }
        )

        # MELODY: quan trọng nhất cho "story-like", nổi ở Immersion/Awakening, dịu ở Breakdown
        melody = layer_matrix(
            {
                "grounding":   {"density_mul": 0.3, "velocity_mul": 0.5, "movement_bias": 0.3, "register_bias": 0.4},
                "immersion":   {"density_mul": 0.8, "velocity_mul": 0.8, "movement_bias": 0.6, "register_bias": 0.5},
                "breakdown":   {"density_mul": 0.2, "velocity_mul": 0.4, "movement_bias": 0.2, "register_bias": 0.4},
                "awakening":   {"density_mul": 0.9, "velocity_mul": 0.9, "movement_bias": 0.7, "register_bias": 0.6},
                "integration": {"density_mul": 0.4, "velocity_mul": 0.5, "movement_bias": 0.3, "register_bias": 0.4},
            }
        )

        # CHIME: dùng ít nhưng có điểm nhấn ở Awakening/Integration (như "ánh sáng")
        chime = layer_matrix(
            {
                "grounding":   {"density_mul": 0.1, "velocity_mul": 0.4, "movement_bias": 0.1, "register_bias": 0.7},
                "immersion":   {"density_mul": 0.3, "velocity_mul": 0.5, "movement_bias": 0.3, "register_bias": 0.8},
                "breakdown":   {"density_mul": 0.2, "velocity_mul": 0.4, "movement_bias": 0.2, "register_bias": 0.7},
                "awakening":   {"density_mul": 0.6, "velocity_mul": 0.8, "movement_bias": 0.5, "register_bias": 0.9},
                "integration": {"density_mul": 0.5, "velocity_mul": 0.7, "movement_bias": 0.4, "register_bias": 0.8},
            }
        )

        # AIR: pad/texture mềm, liên tục, hơi tăng ở Immersion, Breakdown siêu mềm
        air = layer_matrix(
            {
                "grounding":   {"density_mul": 0.5, "velocity_mul": 0.5, "movement_bias": 0.2, "register_bias": 0.7},
                "immersion":   {"density_mul": 0.8, "velocity_mul": 0.7, "movement_bias": 0.3, "register_bias": 0.7},
                "breakdown":   {"density_mul": 0.7, "velocity_mul": 0.5, "movement_bias": 0.2, "register_bias": 0.6},
                "awakening":   {"density_mul": 0.8, "velocity_mul": 0.7, "movement_bias": 0.3, "register_bias": 0.7},
                "integration": {"density_mul": 0.6, "velocity_mul": 0.5, "movement_bias": 0.2, "register_bias": 0.6},
            }
        )

        # PULSE: liên quan nhiều đến Breath Sync, mạnh ở peak (Immersion/Awakening)
        pulse = layer_matrix(
            {
                "grounding":   {"density_mul": 0.3, "velocity_mul": 0.5, "movement_bias": 0.4, "register_bias": 0.3},
                "immersion":   {"density_mul": 0.7, "velocity_mul": 0.7, "movement_bias": 0.6, "register_bias": 0.3},
                "breakdown":   {"density_mul": 0.2, "velocity_mul": 0.4, "movement_bias": 0.2, "register_bias": 0.2},
                "awakening":   {"density_mul": 0.8, "velocity_mul": 0.8, "movement_bias": 0.7, "register_bias": 0.3},
                "integration": {"density_mul": 0.3, "velocity_mul": 0.5, "movement_bias": 0.3, "register_bias": 0.2},
            }
        )

        # BINAURAL: khá đều, hơi giảm ở Breakdown, tránh quá mạnh ở Awakening
        binaural = layer_matrix(
            {
                "grounding":   {"density_mul": 1.0, "velocity_mul": 0.8, "movement_bias": 0.1, "register_bias": 0.1},
                "immersion":   {"density_mul": 1.0, "velocity_mul": 0.9, "movement_bias": 0.2, "register_bias": 0.1},
                "breakdown":   {"density_mul": 0.8, "velocity_mul": 0.7, "movement_bias": 0.1, "register_bias": 0.1},
                "awakening":   {"density_mul": 1.0, "velocity_mul": 0.9, "movement_bias": 0.2, "register_bias": 0.1},
                "integration": {"density_mul": 0.9, "velocity_mul": 0.8, "movement_bias": 0.1, "register_bias": 0.1},
            }
        )

        return {
            "drone": drone,
            "harm": harm,
            "melody": melody,
            "chime": chime,
            "air": air,
            "pulse": pulse,
            "binaural": binaural,
        }

    def _apply_layer_profile_overrides(self) -> None:
        """
        Cho phép override layer_profile qua user_options["zen_arc"]["layer_profile"].

        Ví dụ:

            zen_arc:
              layer_profile:
                melody:
                  grounding:
                    density_mul: 0.5
                    velocity_mul: 0.7
                  awakening:
                    density_mul: 1.0
                    movement_bias: 0.8
        """
        za_conf = self.user_options.get("zen_arc", {})
        lp_conf = za_conf.get("layer_profile", {})

        if not isinstance(lp_conf, dict):
            return

        for layer, per_phase in lp_conf.items():
            if not isinstance(per_phase, dict):
                continue
            # đảm bảo layer tồn tại
            if layer not in self.layer_profiles:
                self.layer_profiles[layer] = {}
            layer_matrix = self.layer_profiles[layer]

            for phase_name, overrides in per_phase.items():
                if phase_name not in self.PHASE_ORDER:
                    continue
                if phase_name not in layer_matrix:
                    layer_matrix[phase_name] = {}
                prof = layer_matrix[phase_name]
                if isinstance(overrides, dict):
                    for k, v in overrides.items():
                        try:
                            prof[k] = float(v)
                        except Exception:
                            continue
                if self.debug:
                    print(
                        f"[ZenArc] Override layer_profile[{layer}][{phase_name}] = {overrides}"
                    )

    # ---------- PUBLIC API ----------

    def get_phase_by_ratio(self, progress_ratio: float) -> ZenPhaseDefinition:
        """
        Lấy phase theo ratio (0..1) của bài.

        Nếu ratio ngoài [0,1] -> clamp.
        Nếu không khớp phase (lý thuyết không xảy ra) -> trả về phase cuối.
        """
        r = max(0.0, min(1.0, float(progress_ratio)))
        for p in self.phases:
            if p.contains_ratio(r):
                return p
        # fallback: phase cuối
        return self.phases[-1]

    def get_phase_for_segment(
        self,
        segment_index: int,
        total_segments: int,
    ) -> ZenPhaseDefinition:
        """
        Map index segment -> ratio -> phase.

        segment_index: 0..total_segments-1
        total_segments: >= 1
        """
        if total_segments <= 1:
            ratio = 0.0
        else:
            # map 0..(N-1) -> 0..1
            ratio = segment_index / float(max(1, total_segments - 1))
        return self.get_phase_by_ratio(ratio)

    def get_phase_for_tick(
        self,
        current_tick: int,
        total_ticks: int,
    ) -> ZenPhaseDefinition:
        """
        Map tick hiện tại -> ratio -> phase.

        current_tick: 0..total_ticks
        total_ticks: > 0
        """
        if total_ticks <= 0:
            ratio = 0.0
        else:
            ratio = current_tick / float(total_ticks)
        return self.get_phase_by_ratio(ratio)

    def get_layer_profile(
        self,
        phase_name: str,
        layer: str,
    ) -> Dict[str, float]:
        """
        Lấy profile của 1 layer trong 1 phase.

        Trả về dict:
            {
                "density_mul": float,
                "velocity_mul": float,
                "movement_bias": float,
                "register_bias": float,
            }

        Nếu không có dữ liệu -> trả profile trung tính.
        """
        neutral = {
            "density_mul": 1.0,
            "velocity_mul": 1.0,
            "movement_bias": 0.5,
            "register_bias": 0.5,
        }

        layer_matrix = self.layer_profiles.get(layer)
        if layer_matrix is None:
            return neutral

        prof = layer_matrix.get(phase_name)
        if prof is None:
            return neutral

        # đảm bảo đầy đủ keys
        out = dict(neutral)
        out.update(prof)
        return out

    def describe(self) -> str:
        """
        Trả về chuỗi mô tả ma trận Zen Arc hiện tại (debug/kiểm tra).
        """
        lines = []
        lines.append("ZenArcMatrix: 5-phase timeline")
        for p in self.phases:
            lines.append(
                f"  [{p.index}] {p.display_name:11s} ({p.name}): "
                f"{p.start_ratio:.3f} -> {p.end_ratio:.3f}, "
                f"energy={p.base_energy:.2f}, move={p.movement_bias:.2f}, "
                f"bright={p.brightness_bias:.2f}, tension={p.tension_bias:.2f}"
            )
        lines.append("Layer profiles:")
        for layer, per_phase in self.layer_profiles.items():
            lines.append(f"  Layer: {layer}")
            for ph in self.PHASE_ORDER:
                prof = per_phase.get(ph, {})
                dm = prof.get("density_mul", 1.0)
                vm = prof.get("velocity_mul", 1.0)
                mb = prof.get("movement_bias", 0.5)
                rb = prof.get("register_bias", 0.5)
                lines.append(
                    f"    - {ph:11s}: dens={dm:.2f}, vel={vm:.2f}, "
                    f"move={mb:.2f}, reg_bias={rb:.2f}"
                )
        return "\n".join(lines)

