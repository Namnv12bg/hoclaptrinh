from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple, Optional, Any


@dataclass
class RegisterBand:
    """
    Dải quãng an toàn cho một layer (min_midi, max_midi).
    """

    min_midi: int
    max_midi: int

    def shifted(self, semitones: int) -> "RegisterBand":
        if semitones == 0:
            return self
        return RegisterBand(self.min_midi + semitones, self.max_midi + semitones)

    def clamp(self, pitch: int) -> int:
        if pitch < self.min_midi:
            return self.min_midi
        if pitch > self.max_midi:
            return self.max_midi
        return pitch


class RegisterManager:
    """
    Register Manager V3 – Neo Zen V11

    - Quản lý quãng an toàn cho từng layer.
    - Áp dụng global register shift theo TuningPlan (Solf Mode).
    - Cho phép override band từ user_options.

    Khởi tạo:

        rm = RegisterManager(
            tuning_core=tuning_core,
            user_options=user_options,
            tuning_plan=tuning_plan,
            tempo_map=tempo_map,
        )

    Sử dụng:

        safe_pitch = rm.constrain_pitch("BASS", raw_pitch)

    Layer name nên viết chuẩn upper-case:
        "DRONE", "BASS", "HARM", "MELODY", "PULSE",
        "AIR", "CHIME", "HANDPAN", "NATURE", "VOCAL", "BINAURAL"
    """

    # ------------------------------------------
    # 1. DEFAULT BANDS (trước khi shift/override)
    # ------------------------------------------
    DEFAULT_BANDS: Dict[str, RegisterBand] = {
        # Siêu trầm / drone gốc, không quá thấp để tránh sub khó mix
        "DRONE": RegisterBand(36, 52),  # C2..E3
        # Bass: trầm nhưng không chạm sub quá sâu, tránh lòi lên mid
        "BASS": RegisterBand(36, 60),  # C2..C4
        # Harm (pad/strings): thân bài
        "HARM": RegisterBand(48, 76),  # C3..E5
        # Melody & Chime & Air & Handpan: vùng cao
        "MELODY": RegisterBand(60, 96),  # C4..C7
        "CHIME": RegisterBand(65, 100),  # F4..E7
        "AIR": RegisterBand(60, 100),  # C4..E7
        "HANDPAN": RegisterBand(60, 88),  # C4..E6
        # Pulse (kalimba/groove nhẹ): low-mid
        "PULSE": RegisterBand(48, 76),  # C3..E5
        # Nature: layer FX, thường không dùng pitch rõ ràng,
        # nhưng nếu engine có pitch thì giữ mid.
        "NATURE": RegisterBand(48, 88),  # C3..E6
        # Vocal chant / OM: mid-warm
        "VOCAL": RegisterBand(48, 80),  # C3..G5
        # Binaural: thường không "clamp", nhưng để tránh quá cao,
        # giữ band rất thấp (nếu có convert pitch nào đó).
        "BINAURAL": RegisterBand(24, 48),  # C1..C3
        # Fallback generic band
        "GENERIC": RegisterBand(36, 96),  # C2..C7
    }

    # Map alias cũ -> layer chuẩn
    LAYER_ALIAS: Dict[str, str] = {
        "HARM_MAIN": "HARM",
        "HARM_LAYER": "HARM",
        "PAD": "HARM",
        "STRINGS": "HARM",
        "MELODY_MAIN": "MELODY",
        "LEAD": "MELODY",
        "FLUTE": "MELODY",
        "DRONE_LOW": "DRONE",
        "DRONE_HIGH": "DRONE",
        "BASS_MAIN": "BASS",
        "KICK_BASS": "BASS",
        "PULSE_MAIN": "PULSE",
        "FX": "NATURE",
        "AMBIENT": "NATURE",
    }

    def __init__(
        self,
        tuning_core: Optional[Any] = None,
        user_options: Optional[Dict[str, Any]] = None,
        tuning_plan: Optional[Any] = None,
        tempo_map: Optional[Any] = None,
    ) -> None:
        self.tuning_core = tuning_core
        self.user_options = user_options or {}
        self.tuning_plan = tuning_plan
        self.tempo_map = tempo_map

        # 1) Global shift (semitone) từ TuningPlan – chỉ đọc MỘT LẦN.
        self.global_shift_semitones: int = self._extract_global_shift_semitones(
            tuning_plan
        )

        # 2) Khởi tạo bands với default + shift + override
        self.bands: Dict[str, RegisterBand] = self._build_bands_with_shift_and_override()

        # (Optional) debug
        if self.user_options.get("debug_register_manager", False):
            self.debug_print_bands()

    # ------------------------------------------
    # 2. INTERNAL: LẤY GLOBAL SHIFT TỪ TUNING PLAN
    # ------------------------------------------
    def _extract_global_shift_semitones(self, tuning_plan: Optional[Any]) -> int:
        """
        Lấy shift semitone từ TuningPlan nếu có,
        đảm bảo nằm trong [-12..+12] để an toàn.
        """

        if tuning_plan is None:
            return 0

        shift = 0
        # Ưu tiên method register_shift_semitones() nếu tồn tại
        if hasattr(tuning_plan, "register_shift_semitones"):
            try:
                shift = int(round(tuning_plan.register_shift_semitones()))
            except Exception:
                shift = 0
        # Nếu không, thử dùng field "global_semitone_shift_planned"
        elif hasattr(tuning_plan, "global_semitone_shift_planned"):
            try:
                shift = int(round(tuning_plan.global_semitone_shift_planned))
            except Exception:
                shift = 0

        # Clamp shift trong khoảng hợp lý, tránh đẩy band quá xa
        if shift < -12:
            shift = -12
        if shift > 12:
            shift = 12
        return shift

    # ------------------------------------------
    # 3. INTERNAL: XÂY BANDS (DEFAULT + SHIFT + OVERRIDE)
    # ------------------------------------------
    def _build_bands_with_shift_and_override(self) -> Dict[str, RegisterBand]:
        """
        - Clone DEFAULT_BANDS.
        - Áp dụng global_shift_semitones.
        - Áp dụng override từ user_options (nếu có).
        """

        # Clone default
        bands: Dict[str, RegisterBand] = {}
        for name, band in self.DEFAULT_BANDS.items():
            bands[name] = band.shifted(self.global_shift_semitones)

        # Override từ user_options
        rm_cfg = self.user_options.get("register_manager", {}) or {}
        override_cfg = rm_cfg.get("register_override", {}) or {}

        # Format mong đợi:
        # register_override:
        #   BASS:
        #     min: 38
        #     max: 60
        #   MELODY:
        #     min: 62
        #     max: 96
        for layer_name, cfg in override_cfg.items():
            try:
                if not isinstance(cfg, dict):
                    continue
                min_val = int(cfg.get("min", None))
                max_val = int(cfg.get("max", None))
                if min_val > max_val:
                    min_val, max_val = max_val, min_val
            except Exception:
                continue

            layer_key = self._normalize_layer_name(layer_name)
            bands[layer_key] = RegisterBand(min_val, max_val)

        return bands

    # ------------------------------------------
    # 4. LAYER NAME NORMALIZATION
    # ------------------------------------------
    def _normalize_layer_name(self, layer_name: str) -> str:
        """
        Chuẩn hoá tên layer:
        - upper-case
        - map alias -> tên chuẩn
        - fallback "GENERIC" nếu không nhận diện được
        """

        if not layer_name:
            return "GENERIC"

        nm = str(layer_name).strip().upper()

        # Nếu mapping alias → layer chuẩn
        if nm in self.LAYER_ALIAS:
            nm = self.LAYER_ALIAS[nm]

        if nm not in self.DEFAULT_BANDS:
            nm = "GENERIC"

        return nm

    # ------------------------------------------
    # 5. PUBLIC API: BANDS & CLAMPING
    # ------------------------------------------
    def get_band(self, layer_name: str) -> Tuple[int, int]:
        """
        Lấy (min_midi, max_midi) cho layer.
        Nếu layer không biết → dùng band "GENERIC".
        """

        key = self._normalize_layer_name(layer_name)
        band = self.bands.get(key)
        if band is None:
            band = self.DEFAULT_BANDS["GENERIC"].shifted(self.global_shift_semitones)
        return band.min_midi, band.max_midi

    def constrain_pitch(self, layer_name: str, pitch: int) -> int:
        """
        Hàm chính để engine clamp pitch về quãng an toàn.
        """

        key = self._normalize_layer_name(layer_name)
        band = self.bands.get(key)

        if band is None:
            # Fallback nếu vì lý do nào đó band chưa được build
            band = self.DEFAULT_BANDS["GENERIC"].shifted(self.global_shift_semitones)

        if pitch < band.min_midi:
            return band.min_midi
        if pitch > band.max_midi:
            return band.max_midi
        return pitch

    # Alias để không vỡ code cũ (nếu trước đây dùng tên khác)
    def safe_pitch(self, layer_name: str, pitch: int) -> int:
        return self.constrain_pitch(layer_name, pitch)

    def clamp_pitch(self, layer_name: str, pitch: int) -> int:
        return self.constrain_pitch(layer_name, pitch)

    # ------------------------------------------
    # 6. DEBUG & INSPECTION
    # ------------------------------------------
    def debug_print_bands(self) -> None:
        """
        In ra toàn bộ bands sau khi áp dụng shift & override.
        Chỉ dùng cho debug (khi debug_register_manager=True).
        """

        print("[RegisterManager] Bands after shift & override:")
        print(f"  Global shift (semitones) = {self.global_shift_semitones}")
        for name, band in sorted(self.bands.items()):
            print(f"    - {name}: {band.min_midi} .. {band.max_midi}")
