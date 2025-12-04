# Tệp: src/utils/config_loader.py
# (FINAL V10.1.1) - CONFIG & PROFILE LOADER (UNIFIED, SAFE NAME FIELD)
#
# Gộp & đổi tên từ:
#   - src/utils/v9_profile_loader.py (FINAL V9.9.34)
#
# Nhiệm vụ:
#   - Định nghĩa InstrumentProfile (dataclass).
#   - Load harm_profiles.yaml & melody_profiles.yaml vào dict[ref -> InstrumentProfile].
#   - Cung cấp API trung tính version: ProfileLoader.

import dataclasses
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml


@dataclass
class InstrumentProfile:
    name: str
    # Basic
    program: int = 0
    velocity: int = 80
    channel: int = 0

    # --- Melody Config ---
    rhythm_mode: str = "rubato"  # flow, mantra, sparks, kintsugi
    articulation: str = "sustained"  # sustained, plucked
    register: List[int] = field(default_factory=lambda: [60, 84])
    legato: float = 1.0
    phrase_rest_prob: float = 0.4
    # [NEW V9.9.30] Ghost & Jitter
    enable_ghosts: bool = False
    humanize_ms: int = 15

    # --- Harm Config ---
    v7_harm_mode: str = "pad"
    v9_voicing_mode: str = "normal"  # stable_locked, ambient_open, neo_zen_open...
    v9_motion_mode: str = "normal"
    v7_pad_overlap_ratio: float = 0.1
    v9_color_intensity: float = 0.5
    v9_motion_intensity: float = 0.3
    # [NEW V9.9.31] Micro-Drift
    enable_drift: bool = False
    drift_amount_cents: float = 8.0
    drift_cycle_secs: float = 30.0

    # [NEW V10] Breath Filter cho HARM (Pad thở bằng CC)
    enable_breath_filter: bool = False
    filter_min_cc: int = 40
    filter_max_cc: int = 100

    # --- Pulse Config ---
    v7_pulse_mode: str = "kalimba"  # heartbeat, shamanic
    v7_shaman_note: int = 36
    v7_shaman_vel: int = 40
    v7_shaman_steps: int = 1
    base_density: float = 0.5
    breath_sync: float = 0.0
    v7_pulse_rest_on_change: bool = True
    v7_pulse_avoid_beats: List[int] = field(default_factory=list)
    v7_pulse_intensity: str = "low"
    v7_pulse_density_rand: float = 0.05
    # [NEW V9.9.32] Polyrhythm
    poly_enabled: bool = False
    poly_steps: int = 3

    # --- Frequency / Drone / Air ---
    v9_mix_level: float = 0.6
    v7_pb_range: int = 2
    # [NEW]
    v9_lowpass_cc: Optional[int] = None
    v9_pan_width: float = 0.2
    enable_breath: bool = False  # Drone Breath (cho DroneEngine)
    breath_depth: int = 15
    enable_morph: bool = False  # Air Morph (cho AirEngine)

    # Legacy/Others (Backward Compatibility)
    duration_ticks: Optional[int] = None
    velocity_low: int = 40
    v7_register_high: bool = False
    v7_vel_low: bool = False
    v7_max_notes: int = 4
    v7_notes_per_bar: int = 4


class ProfileLoaderV9:
    """
    (Giữ nguyên từ V9.9.34 để backward compatible)
    Dùng được cho cả V9 & V10.
    """

    def __init__(self, harm_path: str, melody_path: str):
        self.harm_profiles: Dict[str, InstrumentProfile] = {}
        self.melody_profiles: Dict[str, InstrumentProfile] = {}
        self._load(harm_path, self.harm_profiles)
        self._load(melody_path, self.melody_profiles)

    def _load(self, path: str, target: Dict[str, InstrumentProfile]):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            valid_fields = {f.name for f in dataclasses.fields(InstrumentProfile)}

            for k, v in data.items():
                if not isinstance(v, dict):
                    continue

                # Nếu YAML có "name" thì ưu tiên dùng làm display name,
                # còn ref key k là "mã profile".
                profile_name = v.get("name", k)

                # Chỉ lấy các key hợp lệ, và LOẠI bỏ "name" để tránh truyền 2 lần.
                clean_v = {
                    key: val
                    for key, val in v.items()
                    if key in valid_fields and key != "name"
                }

                target[k] = InstrumentProfile(name=profile_name, **clean_v)
        except Exception as e:
            print(f"  [WARN] Loader Error {path}: {e}")

    def get_harm_profile(self, ref: str) -> InstrumentProfile:
        return self.harm_profiles.get(ref, InstrumentProfile(name="default"))

    def get_melody_profile(self, ref: str) -> InstrumentProfile:
        return self.melody_profiles.get(ref, InstrumentProfile(name="default"))


class ProfileLoader(ProfileLoaderV9):
    """
    Alias "đời mới" không dính version.
    Dùng trong V10+:
        loader = ProfileLoader("config/harm_profiles.yaml",
                               "config/melody_profiles.yaml")
    """

    pass
