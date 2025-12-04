# Tệp: src/engines/pulse_engine_v10.py
# (FINAL V10.11.2) - PULSE ENGINE V10
# MATCH performance.py + SWITCHABLE LAYERS + ZEN CORE INTEGRATION + STRONG ACTIVITY MAP
#
# Mục tiêu:
# - Đóng gói PulseGenerator + Activity Awareness (nhường nhịn theo ActivityMap).
# - Route ra 2 track: Heartbeat (7) & Texture (8), giống logic Zen Core.
# - Thêm các công tắc:
#     + enable_pulse_layer      : ON/OFF toàn bộ Pulse.
#     + enable_heartbeat_layer  : ON/OFF Heartbeat (track 7).
#     + enable_kalimba_layer    : ON/OFF Texture/Kalimba (track 8).
# - Tích hợp với bộ não Zen:
#     + safety_filter           : kiểm soát pitch/velocity/density (nếu bật).
#     + register_manager        : quản lý quãng an toàn theo layer.
#     + breath_sync             : hook cho phát triển sau (breath-aware).
#     + activity_map            : dùng để trim Pulse theo Melody/Zen Arc (mạnh nhưng có luật).
#     + zen_arc_matrix          : hook cho zen-phase trong tương lai.
#     + layer_name              : tên layer để log/safety.
#
# Nguyên tắc mới (theo spec Pulse):
# - Activity trung bình: giảm Kalimba/Texture trước, Heartbeat giảm nhẹ.
# - Activity rất cao   : có thể chỉ giữ Heartbeat nhẹ, tắt Kalimba/Texture.
# - Không “giết sạch” Pulse trừ khi apply_pulse_activity_trim đã xoá hết.

from __future__ import annotations

from typing import List, Dict, Any, Optional

from src.utils.midi_writer import MidiWriter, MidiTrack
from src.core.pulse_generator import PulseGenerator, PulseNote
from src.core.structure_builder import Segment
from src.utils.activity_map import ActivityMap
from src.utils.config_loader import InstrumentProfile

# Unified Performance Layer
from src.utils.performance import apply_pulse_activity_trim


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class PulseEngineV10:
    """
    V10 Pulse Engine:
    - Heartbeat + Kalimba/Texture.
    - Nhường nhịn Melody / Arc thông qua ActivityMap (apply_pulse_activity_trim + per-note trim).
    - Có công tắc bật/tắt layer.
    - Đã tích hợp interface mới cho Neo Zen Core (safety_filter, register_manager...).
    """

    def __init__(
        self,
        writer: MidiWriter,
        kalimba_profile: InstrumentProfile,
        ppq: int,
        user_options: Dict[str, Any],
        safety_filter: Optional[object] = None,
        register_manager: Optional[object] = None,
        breath_sync: Optional[object] = None,
        activity_map: Optional[ActivityMap] = None,
        zen_arc_matrix: Optional[object] = None,
        layer_name: str = "pulse",
    ) -> None:
        self.writer = writer
        self.kalimba_profile = kalimba_profile
        self.ppq = ppq
        self.user_options = user_options or {}

        # Hooks từ Zen Core
        self.safety_filter = safety_filter
        self.register_manager = register_manager
        self.breath_sync = breath_sync
        self.activity_map = activity_map
        self.zen_arc_matrix = zen_arc_matrix
        self.layer_name = layer_name or "pulse"

        # ===== SWITCHES (có thể đến từ user_options hoặc profile) =====
        def _bool_opt(name: str, profile_attr: str, default: bool = True) -> bool:
            if name in self.user_options:
                return bool(self.user_options.get(name))
            return bool(getattr(self.kalimba_profile, profile_attr, default))

        # Master: bật/tắt toàn bộ Pulse layer
        self.enable_pulse_layer: bool = _bool_opt(
            "enable_pulse_layer", "enable_pulse_layer", True
        )
        # Bật/tắt Heartbeat (track 7)
        self.enable_heartbeat_layer: bool = _bool_opt(
            "enable_heartbeat_layer", "enable_heartbeat_layer", True
        )
        # Bật/tắt Texture / Kalimba (track 8)
        self.enable_kalimba_layer: bool = _bool_opt(
            "enable_kalimba_layer", "enable_kalimba_layer", True
        )

        # ===== Activity thresholds riêng cho Pulse (mạnh) =====
        # Ngưỡng trung bình: bắt đầu giảm Kalimba/Texture.
        self.pulse_activity_mid_threshold: float = float(
            self.user_options.get(
                "pulse_activity_mid_threshold",
                getattr(self.kalimba_profile, "pulse_activity_mid_threshold", 0.6),
            )
        )
        # Ngưỡng cao: có thể tắt Kalimba, Heartbeat chỉ giảm nhẹ.
        self.pulse_activity_high_threshold: float = float(
            self.user_options.get(
                "pulse_activity_high_threshold",
                getattr(self.kalimba_profile, "pulse_activity_high_threshold", 0.85),
            )
        )
        self.pulse_activity_mid_threshold = _clamp(
            self.pulse_activity_mid_threshold, 0.0, 1.0
        )
        self.pulse_activity_high_threshold = _clamp(
            self.pulse_activity_high_threshold, 0.0, 1.0
        )
        if self.pulse_activity_high_threshold < self.pulse_activity_mid_threshold:
            # đảm bảo high >= mid
            self.pulse_activity_high_threshold = self.pulse_activity_mid_threshold

        # Brain
        self.generator = PulseGenerator(ppq=ppq, user_options=self.user_options)

        # Track Heartbeat (trống sâu)
        self.track_hb: MidiTrack = writer.get_track(7)
        self.track_hb.set_name("7. HEART (Pulse)")
        # GM Taiko / Deep Drum (có thể override bằng profile nếu sau này cần)
        self.track_hb.set_program(117)

        # Track Texture (Kalimba/Bell)
        self.track_tex: MidiTrack = writer.get_track(8)
        self.track_tex.set_name("8. HEART (Texture)")
        tex_prog = getattr(kalimba_profile, "program", 108) or 108
        self.track_tex.set_program(tex_prog)

    # -------------------------------------------------------
    # PUBLIC
    # -------------------------------------------------------
    def render(
        self,
        segments: List[Segment],
        key: str,
        scale: str,
        tempo_map,  # giữ signature khớp Zen Core, hiện chưa dùng trực tiếp
    ) -> None:
        """
        Pipeline:
            1. PulseGenerator → List[PulseNote].
            2. Lọc theo công tắc: enable_pulse_layer / enable_heartbeat_layer / enable_kalimba_layer.
            3. apply_pulse_activity_trim (performance.py) để Pulse nhường Melody (dựa trên ActivityMap).
            4. Trim thêm từng nốt dựa trên ActivityMap:
                 - Kalimba: có thể tắt khi Activity rất cao.
                 - Heartbeat: không tắt, chỉ giảm velocity.
            5. (Tuỳ chọn) SafetyFilter/RegisterManager cho từng nốt (nếu có).
            6. Route sang 2 track: Heartbeat (7) / Texture (8) rồi ghi MIDI.
        """
        # Master OFF: tắt cả Pulse layer
        if not self.enable_pulse_layer:
            print("   [PulseV10] Pulse layer disabled (enable_pulse_layer = False).")
            return

        if not segments:
            return

        # 1. Sinh toàn bộ Pulse (Heartbeat + Kalimba/Texture)
        notes: List[PulseNote] = self.generator.generate_full_pulse(
            segments, key, scale
        )

        if not notes:
            print("   [PulseV10] No pulse notes generated.")
            return

        # 2. Lọc theo công tắc Heartbeat / Kalimba dựa trên channel của PulseNote
        #    Quy ước hiện tại:
        #       - channel == 1  → Texture/Kalimba (track_tex)
        #       - các channel khác → Heartbeat (track_hb)
        filtered: List[PulseNote] = []
        for n in notes:
            ch = getattr(n, "channel", 0)

            if ch == 1:
                # Texture / Kalimba
                if not self.enable_kalimba_layer:
                    continue
            else:
                # Heartbeat
                if not self.enable_heartbeat_layer:
                    continue

            filtered.append(n)

        notes = filtered
        if not notes:
            print("   [PulseV10] All pulse notes filtered by switches (no output).")
            return

        # 3. Cho Performance Layer xử lý list PulseNote (Activity-aware, global)
        #    Nếu không có ActivityMap thì bỏ qua bước trim, ghi thẳng.
        if self.activity_map is not None:
            threshold = float(
                self.user_options.get(
                    "pulse_activity_threshold",
                    getattr(self.kalimba_profile, "pulse_activity_threshold", 0.6),
                )
            )
            reduction_ratio = float(
                self.user_options.get(
                    "pulse_reduction_ratio",
                    getattr(self.kalimba_profile, "pulse_reduction_ratio", 0.6),
                )
            )

            print(f"   [PulseV10] Rendering {len(notes)} notes (Activity-aware)...")

            notes = apply_pulse_activity_trim(
                notes,
                self.activity_map,
                pulse_activity_threshold=threshold,
                pulse_reduction_ratio=reduction_ratio,
                melody_track_name="MELODY",
            )

            if not notes:
                print("   [PulseV10] All notes removed by activity trim.")
                return
        else:
            print("   [PulseV10] No ActivityMap provided, skipping activity trim.")

        # 4. Per-note Activity trim + (tuỳ chọn) SafetyFilter + RegisterManager
        safe_notes: List[PulseNote] = []

        for n in notes:
            pitch = int(n.pitch)
            vel = int(n.velocity)
            start_tick = int(n.start_tick)
            dur = int(n.duration_ticks)

            is_kalimba = getattr(n, "channel", 0) == 1

            # 4.a ActivityMap: trim mạnh hơn cho Kalimba, nhẹ cho Heartbeat
            if self.activity_map is not None:
                try:
                    act_level = 0.0
                    # ưu tiên API mới
                    if hasattr(self.activity_map, "get_activity_at_tick"):
                        act_level = float(
                            self.activity_map.get_activity_at_tick(start_tick)
                        )
                    elif hasattr(self.activity_map, "get_energy_at_tick"):
                        act_level = float(
                            self.activity_map.get_energy_at_tick(self.layer_name, start_tick)
                        )
                    elif hasattr(self.activity_map, "get_track_energy"):
                        act_level = float(
                            self.activity_map.get_track_energy(
                                self.layer_name, start_tick
                            )
                        )
                    act_level = _clamp(act_level, 0.0, 1.5)
                except Exception:
                    act_level = 0.0

                # Logic:
                # - Nếu là Kalimba:
                #       + act >= high_threshold  → bỏ nốt.
                #       + act >= mid_threshold   → giảm velocity.
                # - Nếu là Heartbeat:
                #       + act >= high_threshold  → chỉ giảm velocity (không bỏ).
                if is_kalimba:
                    if act_level >= self.pulse_activity_high_threshold:
                        # full-busy: bỏ Kalimba, chỉ giữ Heartbeat
                        continue
                    elif act_level >= self.pulse_activity_mid_threshold:
                        vel = int(vel * 0.7)
                else:
                    if act_level >= self.pulse_activity_high_threshold:
                        vel = int(vel * 0.8)

            vel = max(1, min(127, vel))

            # 4.b RegisterManager: ép nốt về register an toàn nếu có API phù hợp
            if self.register_manager is not None:
                try:
                    # Giữ kiểu duck-typing để không phá API hiện tại:
                    # Ưu tiên hàm apply_register(layer_name, pitch, tick)
                    if hasattr(self.register_manager, "apply_register"):
                        pitch = int(
                            self.register_manager.apply_register(
                                self.layer_name, pitch, start_tick
                            )
                        )
                    elif hasattr(self.register_manager, "apply_for_layer"):
                        pitch = int(
                            self.register_manager.apply_for_layer(
                                layer=self.layer_name,
                                pitch=pitch,
                                tick=start_tick,
                            )
                        )
                except Exception:
                    # Nếu có lỗi thì fallback giữ nguyên pitch
                    pass

            # 4.c SafetyFilter: kiểm tra/scan nốt, có meta chuẩn hoá
            allowed = True
            if self.safety_filter is not None:
                meta = {
                    "layer": self.layer_name,
                    "sub_layer": "kalimba" if is_kalimba else "heartbeat",
                    "section_type": getattr(n, "section_type", None),
                    "energy_bias": getattr(n, "energy_bias", None),
                    "t_norm": getattr(n, "t_norm", None),
                }
                try:
                    # Pattern 1: filter_note(...) trả (allowed, new_pitch, new_vel)
                    if hasattr(self.safety_filter, "filter_note"):
                        try:
                            res = self.safety_filter.filter_note(
                                layer=self.layer_name,
                                pitch=pitch,
                                velocity=vel,
                                tick=start_tick,
                                meta=meta,
                            )
                        except TypeError:
                            # SafetyFilter cũ không có tham số meta
                            res = self.safety_filter.filter_note(
                                layer=self.layer_name,
                                pitch=pitch,
                                velocity=vel,
                                tick=start_tick,
                            )

                        if isinstance(res, (tuple, list)) and len(res) >= 3:
                            allowed, pitch, vel = (
                                bool(res[0]),
                                int(res[1]),
                                int(res[2]),
                            )
                        else:
                            allowed = bool(res)
                    # Pattern 2: allow_note(...) trả bool
                    elif hasattr(self.safety_filter, "allow_note"):
                        try:
                            allowed = bool(
                                self.safety_filter.allow_note(
                                    layer=self.layer_name,
                                    pitch=pitch,
                                    velocity=vel,
                                    tick=start_tick,
                                    meta=meta,
                                )
                            )
                        except TypeError:
                            # allow_note cũ không nhận meta
                            allowed = bool(
                                self.safety_filter.allow_note(
                                    layer=self.layer_name,
                                    pitch=pitch,
                                    velocity=vel,
                                    tick=start_tick,
                                )
                            )
                except Exception:
                    # Bất kỳ lỗi nào trong SafetyFilter đều không chặn pipeline
                    allowed = True

            if not allowed:
                continue

            # Cập nhật lại note nếu pitch/velocity thay đổi
            n.pitch = int(pitch)
            n.velocity = max(1, min(127, int(vel)))
            n.start_tick = start_tick
            n.duration_ticks = dur
            safe_notes.append(n)

        if not safe_notes:
            print("   [PulseV10] All notes filtered by Activity/Safety/Register, no output.")
            return

        # 5. Route & ghi nốt ra 2 track
        for n in safe_notes:
            target: MidiTrack = (
                self.track_tex
                if getattr(n, "channel", 0) == 1  # channel 1 = Texture
                else self.track_hb                 # còn lại = Heartbeat
            )

            target.add_note(
                int(n.pitch),
                int(n.velocity),
                int(n.start_tick),
                int(n.duration_ticks),
            )
