# Tệp: src/core/humanity_core.py
# (BETA V10.11.0) - HUMANITY CORE V1
# MICRO-IMPERFECTION + FEEL MAP (BREATH / PHASE / LAYER AWARE)
#
# Vai trò:
#   - Gom toàn bộ "chất người" (human feel) vào một nơi, để:
#       + Các Engine không phải tự humanize lung tung.
#       + Dễ kiểm soát mức "nhân tính" toàn hệ (global & per-layer).
#   - Chỉ xử lý những thứ vi mô, không phá vỡ Zen:
#       + Timing jitter nhẹ, lệch ± vài tick.
#       + Velocity humanize (mềm / nhấn / tan).
#       + Breath-aware phrasing (đầu hơi / cuối hơi).
#       + Phase/Zen Arc aware (Intro mềm, Awakening rõ nét hơn, v.v.).
#
# Thiết kế:
#   from src.core.humanity_core import HumanityCore, HumanityConfig
#
#   humanity = HumanityCore.from_user_options(
#       user_options=user_options,
#       ppq=ppq,
#       tempo_bpm=bpm,
#   )
#
#   # Trong Engine:
#   tick_h, vel_h = humanity.humanize_note(
#       layer="melody",
#       tick=start_tick,
#       velocity=raw_vel,
#       phase_name=segment.phase_name,
#       breath_phase=breath_info.breath_phase,
#   )
#
# Nguyên tắc:
#   - Luôn trả về giá trị hợp lệ, không làm crash.
#   - Mặc định conservative (ít tác động) nếu không có config.
#   - Không đụng đến register (pitch range) → việc của RegisterManager/SafetyFilter.
#   - Không thay đổi logic hòa âm → việc của Safe Harmony.
#
# Cấu hình gợi ý trong user_options.yaml:
#
# humanity_core:
#   enabled: true
#   global_strength: 0.6        # 0..1 – độ mạnh chung
#   max_timing_jitter_ms: 25    # lệch thời gian tối đa (ms)
#   max_velocity_jitter: 8      # lệch velocity tối đa (0..127)
#   breath_accent_inhale: -3    # điều chỉnh velocity ở inhale
#   breath_accent_exhale: +4    # điều chỉnh velocity ở exhale
#   breath_accent_hold: -6      # điều chỉnh velocity ở hold
#
#   phase_multipliers:
#     Grounding: 0.4
#     Immersion: 0.7
#     Awakening: 1.0
#     Integration: 0.5
#
#   layer_profiles:
#     melody:
#       strength: 0.9
#       timing_focus: 1.0
#       velocity_focus: 1.0
#     harm:
#       strength: 0.3
#       timing_focus: 0.4
#       velocity_focus: 0.5
#     drone:
#       strength: 0.1
#       timing_focus: 0.2
#       velocity_focus: 0.0
#
# Nếu không khai báo → dùng giá trị mặc định rất an toàn.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, Optional
import random


def _clamp_int(x: int, lo: int, hi: int) -> int:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _clamp_float(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


@dataclass
class HumanityLayerProfile:
    """
    Cấu hình humanize cho từng layer.

    strength       : 0..1 – độ mạnh tổng (0 = tắt, 1 = mạnh nhất trong giới hạn cho phép).
    timing_focus   : 0..1 – ưu tiên humanize về timing.
    velocity_focus : 0..1 – ưu tiên humanize về velocity.
    """

    strength: float = 0.5
    timing_focus: float = 0.7
    velocity_focus: float = 0.7

    def effective_strength(self, global_strength: float) -> float:
        """Kết hợp global_strength và strength riêng layer."""
        return _clamp_float(global_strength * self.strength, 0.0, 1.0)


@dataclass
class HumanityConfig:
    """
    Cấu hình tổng cho HumanityCore.

    Ý tưởng:
      - global_strength: "master" knob cho toàn hệ.
      - max_timing_jitter_ms: lệch timing tối đa (ở strength=1).
      - max_velocity_jitter: lệch velocity tối đa (ở strength=1).
      - phase_multipliers: scale theo phase (Grounding/Immersion/Awakening/Integration).
      - layer_profiles: map layer -> HumanityLayerProfile.
    """

    enabled: bool = True

    global_strength: float = 0.5
    max_timing_jitter_ms: float = 20.0
    max_velocity_jitter: int = 6

    # Breath accent (velocity offset) theo breath_phase
    breath_accent_inhale: int = -2
    breath_accent_exhale: int = +3
    breath_accent_hold: int = -5

    # Phase multipliers (phase_name -> factor)
    phase_multipliers: Dict[str, float] = field(
        default_factory=lambda: {
            "Grounding": 0.4,
            "Immersion": 0.7,
            "Awakening": 1.0,
            "Integration": 0.5,
        }
    )

    # Layer-specific profiles
    layer_profiles: Dict[str, HumanityLayerProfile] = field(
        default_factory=lambda: {
            "melody": HumanityLayerProfile(strength=0.9, timing_focus=1.0, velocity_focus=1.0),
            "harm": HumanityLayerProfile(strength=0.3, timing_focus=0.5, velocity_focus=0.4),
            "drone": HumanityLayerProfile(strength=0.1, timing_focus=0.2, velocity_focus=0.0),
            "chime": HumanityLayerProfile(strength=0.7, timing_focus=0.6, velocity_focus=0.8),
            "air": HumanityLayerProfile(strength=0.5, timing_focus=0.4, velocity_focus=0.6),
            "pulse": HumanityLayerProfile(strength=0.8, timing_focus=0.9, velocity_focus=0.7),
        }
    )

    def get_phase_multiplier(self, phase_name: str) -> float:
        if not phase_name:
            return 1.0
        return float(self.phase_multipliers.get(phase_name, 1.0))

    def get_layer_profile(self, layer: str) -> HumanityLayerProfile:
        return self.layer_profiles.get(layer, HumanityLayerProfile())


class HumanityCore:
    """
    HumanityCore – lớp xử lý "nhân tính" (micro-imperfection) cho nốt.

    Mức độ can thiệp:
      - Chỉ thay đổi TICK & VELOCITY.
      - Không chạm đến PITCH (pitch do Engine + SafeHarmony/SafetyFilter quyết).
      - Không làm lệch groove/breath quá mạnh – chỉ ± vài tick.

    API chính:
      - humanize_note(layer, tick, velocity, phase_name, breath_phase, segment_index, rng=None)
      - humanize_timing(layer, tick, phase_name, rng=None)
      - humanize_velocity(layer, velocity, phase_name, breath_phase, rng=None)
    """

    def __init__(
        self,
        config: HumanityConfig,
        ppq: int,
        tempo_bpm: float,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.config = config
        self.ppq = int(ppq)
        self.tempo_bpm = float(tempo_bpm) if tempo_bpm > 0 else 60.0
        self._rng = rng or random.Random()

        # Precompute: 1 ms = ? ticks (dựa trên BPM & PPQ)
        # 1 quarter note = 60 / bpm (seconds)
        # 1 tick = (60 / bpm) / ppq (seconds)
        # -> 1 ms = 0.001 / ((60 / bpm) / ppq) ticks
        sec_per_quarter = 60.0 / self.tempo_bpm
        sec_per_tick = sec_per_quarter / float(self.ppq)
        self._ticks_per_ms = 0.001 / sec_per_tick if sec_per_tick > 0 else 0.0

    # =========================
    # FACTORY TỪ USER_OPTIONS
    # =========================

    @classmethod
    def from_user_options(
        cls,
        user_options: Dict[str, Any],
        ppq: int,
        tempo_bpm: float,
        rng_seed: Optional[int] = None,
    ) -> "HumanityCore":
        """
        Tạo HumanityCore từ user_options["humanity_core"].

        Nếu không có config -> HumanityConfig mặc định (an toàn).
        """
        hc_opt = user_options.get("humanity_core", {}) or {}

        enabled = bool(hc_opt.get("enabled", True))
        global_strength = float(hc_opt.get("global_strength", 0.5))
        max_timing_jitter_ms = float(hc_opt.get("max_timing_jitter_ms", 20.0))
        max_velocity_jitter = int(hc_opt.get("max_velocity_jitter", 6))

        breath_accent_inhale = int(hc_opt.get("breath_accent_inhale", -2))
        breath_accent_exhale = int(hc_opt.get("breath_accent_exhale", +3))
        breath_accent_hold = int(hc_opt.get("breath_accent_hold", -5))

        # Phase multipliers
        phase_multipliers = {
            **HumanityConfig().phase_multipliers  # default
        }
        user_phase = hc_opt.get("phase_multipliers", {}) or {}
        for k, v in user_phase.items():
            try:
                phase_multipliers[str(k)] = float(v)
            except (TypeError, ValueError):
                continue

        # Layer profiles
        default_layer_profiles = HumanityConfig().layer_profiles
        layer_profiles: Dict[str, HumanityLayerProfile] = {}
        user_layers = hc_opt.get("layer_profiles", {}) or {}

        for layer_name, lp_cfg in user_layers.items():
            try:
                s = float(lp_cfg.get("strength", default_layer_profiles.get(layer_name, HumanityLayerProfile()).strength))
                tf = float(lp_cfg.get("timing_focus", default_layer_profiles.get(layer_name, HumanityLayerProfile()).timing_focus))
                vf = float(lp_cfg.get("velocity_focus", default_layer_profiles.get(layer_name, HumanityLayerProfile()).velocity_focus))
            except Exception:
                s, tf, vf = 0.5, 0.7, 0.7
            layer_profiles[layer_name] = HumanityLayerProfile(
                strength=_clamp_float(s, 0.0, 1.0),
                timing_focus=_clamp_float(tf, 0.0, 1.0),
                velocity_focus=_clamp_float(vf, 0.0, 1.0),
            )

        # Keep defaults for layers not overridden
        for k, lp in default_layer_profiles.items():
            if k not in layer_profiles:
                layer_profiles[k] = lp

        cfg = HumanityConfig(
            enabled=enabled,
            global_strength=_clamp_float(global_strength, 0.0, 1.0),
            max_timing_jitter_ms=max_timing_jitter_ms,
            max_velocity_jitter=max_velocity_jitter,
            breath_accent_inhale=breath_accent_inhale,
            breath_accent_exhale=breath_accent_exhale,
            breath_accent_hold=breath_accent_hold,
            phase_multipliers=phase_multipliers,
            layer_profiles=layer_profiles,
        )

        rng = random.Random(rng_seed) if rng_seed is not None else random.Random()
        return cls(cfg, ppq=ppq, tempo_bpm=tempo_bpm, rng=rng)

    # =========================
    # PUBLIC API
    # =========================

    def is_enabled(self) -> bool:
        return self.config.enabled and self.config.global_strength > 0.0

    def humanize_timing(
        self,
        layer: str,
        tick: int,
        phase_name: Optional[str] = None,
        segment_index: Optional[int] = None,
        rng: Optional[random.Random] = None,
    ) -> int:
        """
        Humanize TICK (thời điểm bắt đầu nốt).

        - Áp dụng jitter theo:
            + global_strength
            + layer_profile.strength & timing_focus
            + phase_multiplier (Grounding/Immersion/Awakening/Integration)
        - Jitter luôn là số nguyên tick (round).
        """
        if not self.is_enabled():
            return int(tick)

        r = rng or self._rng
        t = int(tick)

        lp = self.config.get_layer_profile(layer)
        g = self.config.global_strength
        s_eff = lp.effective_strength(g)
        if s_eff <= 0.0 or lp.timing_focus <= 0.0 or self._ticks_per_ms <= 0.0:
            return t

        phase_mult = self.config.get_phase_multiplier(phase_name or "")
        strength = s_eff * lp.timing_focus * phase_mult
        strength = _clamp_float(strength, 0.0, 1.0)

        # max jitter (ms) → ticks
        max_ms = self.config.max_timing_jitter_ms
        max_ticks = max_ms * self._ticks_per_ms

        # Jitter thực tế theo strength
        jitter_range = max_ticks * strength

        if jitter_range <= 0.0:
            return t

        # Random trong [-jitter_range, +jitter_range], dùng phân phối tam giác nhẹ cho cảm giác tự nhiên
        raw = r.uniform(-1.0, 1.0)
        # Tam giác: trọng tâm gần 0 (ít lệch mạnh)
        shaped = raw * abs(r.uniform(-1.0, 1.0))
        jitter_ticks = int(round(shaped * jitter_range))

        t_human = t + jitter_ticks
        if t_human < 0:
            t_human = 0
        return t_human

    def humanize_velocity(
        self,
        layer: str,
        velocity: int,
        phase_name: Optional[str] = None,
        breath_phase: Optional[str] = None,
        rng: Optional[random.Random] = None,
    ) -> int:
        """
        Humanize VELOCITY.

        - Áp dụng jitter + breath accent.
        - Không vượt quá [1..127].
        """
        v = _clamp_int(int(velocity), 0, 127)
        if not self.is_enabled():
            return v

        r = rng or self._rng

        lp = self.config.get_layer_profile(layer)
        g = self.config.global_strength
        s_eff = lp.effective_strength(g)
        if s_eff <= 0.0 or lp.velocity_focus <= 0.0:
            return v

        phase_mult = self.config.get_phase_multiplier(phase_name or "")
        strength = s_eff * lp.velocity_focus * phase_mult
        strength = _clamp_float(strength, 0.0, 1.0)

        max_vjit = self.config.max_velocity_jitter
        vjit_range = max_vjit * strength

        # Random jitter (phân phối nhẹ)
        raw = r.uniform(-1.0, 1.0)
        shaped = raw * abs(r.uniform(-1.0, 1.0))
        jitter = int(round(shaped * vjit_range))

        v_new = v + jitter

        # Breath accent
        bp = (breath_phase or "").lower()
        if bp.startswith("in"):
            v_new += self.config.breath_accent_inhale
        elif bp.startswith("out") or bp.startswith("ex"):
            v_new += self.config.breath_accent_exhale
        elif "hold" in bp:
            v_new += self.config.breath_accent_hold

        # Clip final
        v_new = _clamp_int(v_new, 0, 127)
        return v_new

    def humanize_note(
        self,
        layer: str,
        tick: int,
        velocity: int,
        phase_name: Optional[str] = None,
        breath_phase: Optional[str] = None,
        segment_index: Optional[int] = None,
        rng: Optional[random.Random] = None,
    ) -> tuple[int, int]:
        """
        API tiện lợi cho Engine: humanize cả timing & velocity một lần.

        Trả về:
            (tick_humanized, velocity_humanized)
        """
        if not self.is_enabled():
            return int(tick), _clamp_int(int(velocity), 0, 127)

        r = rng or self._rng

        t_h = self.humanize_timing(
            layer=layer,
            tick=tick,
            phase_name=phase_name,
            segment_index=segment_index,
            rng=r,
        )
        v_h = self.humanize_velocity(
            layer=layer,
            velocity=velocity,
            phase_name=phase_name,
            breath_phase=breath_phase,
            rng=r,
        )
        return t_h, v_h
