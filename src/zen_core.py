# Tệp: src/zen_core.py
# (FINAL V11.2.2) - NEO ZEN CORE
# PHASE 3 - DYNAMIC SEMITONE JOURNEY (FREQUENCY-AWARE, SAFE LIMIT) + V11 UI SYNC
#
# Vai trò:
# - "Bộ não tổng" gọi các lớp trong core/, engines/, utils/, exporters/.
# - Không còn khái niệm v9/v10 tách rời, chỉ còn 1 pipeline Neo Zen thống nhất.
#
# PHASE 1:
# - Gắn TuningCoreV3, RegisterManager, SafetyFilter, ActivityMap V2, Drone/Bass/Binaural/Handpan.
#
# PHASE 2:
# - Thêm global transpose theo bán cung (static) từ TuningPlan:
#     + tuning_plan.global_semitone_shift_planned -> làm tròn & kẹp trong [-phase2_max_semitone, +phase2_max_semitone].
#     + Áp dụng qua DynamicTransposingWriter.default_shift.
#
# PHASE 3 (bản này):
# - Thêm dynamic transpose theo hành trình tần số (Frequency Journey):
#     + Nếu enable_phase3_journey = True và FrequencyJourney.enabled:
#         * Mỗi Stage được gán stage.shift_semitones (global_shift + stage_shift_local).
#         * stage_shift_local được suy ra từ tần số Stage so với Stage 1: 12 * log2(f_stage / f_base).
#         * stage_shift_local được kẹp trong [-phase3_max_semitone_per_stage, +phase3_max_semitone_per_stage].
#     + DynamicTransposingWriter:
#         * journey = freq_journey
#         * default_shift = global_semitone_shift (vùng ngoài stage).
#
# NOTE:
# - Chưa dùng pitch bend cents / global retune theo cents (dành Phase 4).
# - BinauralEngine vẫn làm việc trên Hz, không bị transpose MIDI.
# - Đồng bộ với app V11:
#     + v10_air_profile / v10_chime_profile ưu tiên hơn air_profile/chime_profile.
#     + v9_pulse_profile default = "pulse_kalimba_texture".
#     + handpan_tuning_mode default = "pure_key".

import os
import yaml
import datetime
import random
import math
from typing import Dict, Any

# Core Logic
from src.core.tempo_breath import TempoBreath, TempoMap
from src.core.structure_builder import StructureBuilder, Segment
from src.core.music_theory import (
    NOTE_TO_PC,
    midi_to_hz,
    parse_progression_string,
)
from src.core.frequency_journey import build_frequency_journey, FrequencyJourney
from src.core.brainwave_journey import build_brainwave_journey, BrainwaveJourney
from src.core.tuning_core import TuningCoreV3
from src.core.zen_arc_matrix import ZenArcMatrix
from src.core.breath_sync import BreathSyncManager
from src.core.register_manager import RegisterManager
from src.core.safety_filter import SafetyFilter

# Utils
from src.utils.midi_writer import MidiWriter
from src.utils.activity_map import ActivityMap
from src.utils.config_loader import ProfileLoader
from src.utils.dynamic_transposer import DynamicTransposingWriter

# Engines (alias)
# Engines (alias an toàn, dựa trên alias cuối file mỗi engine)
from src.engines.melody_engine_v10 import MelodyEngineV10 as MelodyEngine
from src.engines.pulse_engine_v10 import PulseEngineV10 as PulseEngine

from src.engines.harm_engine import HarmEngine          # alias bên trong trỏ đúng V mới nhất
from src.engines.drone_engine import DroneEngine        # alias -> DroneEngineV1
from src.engines.air_engine import AirEngineV1 as AirEngine

from src.engines.chime_engine import ChimeEngine        # alias -> ChimeEngineV1
from src.engines.binaural_engine import BinauralEngine  # alias -> BinauralEngine (V11)

from src.engines.nature_engine import NatureEngineV1 as NatureEngine
from src.engines.vocal_engine import VocalEngineV1 as VocalEngine
from src.engines.bass_engine import BassEngineV1 as BassEngine
from src.engines.handpan_engine import HandpanEngineV1 as HandpanEngine

# Exporters (Reaper / Guide – optional)
# from src.exporters.reaper import ReaperGeneratorV9
# from src.exporters.guide import MixingGuideV9

# Config paths
HARM_PROFILES = "config/harm_profiles.yaml"
MELODY_PROFILES = "config/melody_profiles.yaml"  # khớp với file bạn đang dùng

# =========================
# Profile resolvers (giữ lại để dùng sau nếu cần)
# =========================

HARM_STYLE_TO_PROFILE = {
    "layered":  ("harm_chord_pad", "v8_slow_strings"),
    "pad":      ("v8_warm_pad", None),
    "choir":    ("harm_angelic_choir", "v8_slow_strings"),
    "modal_texture": ("harm_modal_texture", None),
    "arpeggio": ("piano_arp", "v8_slow_strings"),
}

def resolve_harm_profiles(v9_harm_style: str) -> tuple[str, str | None]:
    try:
        return HARM_STYLE_TO_PROFILE[v9_harm_style]
    except KeyError:
        raise KeyError(f"[ZenCore] Unknown v9_harm_style: {v9_harm_style!r}")

def resolve_melody_profile(persona: str) -> str:
    # persona: "flute_flow", "piano_kintsugi", ...
    return persona

def resolve_air_profile_from_options(options: Dict[str, Any]) -> str | None:
    """
    Ưu tiên:
    - v10_air_profile (UI V11 mới): "air_crystal_shimmer" / "off"
    - fallback: air_profile (preset cũ)
    - None hoặc "off" => skip layer
    """
    v10_val = options.get("v10_air_profile")
    if isinstance(v10_val, str):
        if v10_val.lower() == "off":
            return None
        return v10_val

    legacy = options.get("air_profile")
    if isinstance(legacy, str):
        if legacy.lower() == "off":
            return None
        return legacy

    # default an toàn
    return "air_crystal_shimmer"

def resolve_chime_profile_from_options(options: Dict[str, Any]) -> str | None:
    """
    Ưu tiên:
    - v10_chime_profile (UI V11 mới): "chime_crystal_bell"
    - fallback: chime_profile (preset cũ)
    - nếu density quá thấp (~0) hoặc profile "off" => có thể bỏ qua
    """
    v10_val = options.get("v10_chime_profile")
    if isinstance(v10_val, str) and v10_val.lower() != "off":
        return v10_val

    legacy = options.get("chime_profile")
    if isinstance(legacy, str) and legacy.lower() != "off":
        return legacy

    # default an toàn
    return "chime_crystal_bell"

# =========================
# 1. YAML + HELPER
# =========================

def _load_yaml(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}

def _safe_int(value, default: int) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default

def _normalize_seed(options: Dict[str, Any]) -> int:
    """
    Chuẩn hoá seed:
    - Nếu user đã set seed (int) -> dùng.
    - Nếu None hoặc không đúng kiểu -> random từ hệ thống, nhưng log lại để tái lập.
    """
    seed = options.get("seed", None)
    try:
        if seed is not None:
            return int(seed)
    except (TypeError, ValueError):
        pass

    # Tạo seed mới
    new_seed = random.randint(0, 2**31 - 1)
    print(f"[NeoZen] No valid seed provided, using random seed = {new_seed}")
    return new_seed

def _validate_options(options: Dict[str, Any]) -> None:
    """
    Đảm bảo một số field cơ bản luôn có giá trị hợp lệ.
    """
    if not options.get("key"):
        options["key"] = "C"
    if not options.get("scale"):
        options["scale"] = "major"
    if options.get("base_tempo", 0) <= 0:
        options["base_tempo"] = 60
    if options.get("total_duration_seconds", 0) <= 0:
        options["total_duration_seconds"] = 600

def _auto_duration_from_chords(options: Dict[str, Any]) -> None:
    """
    Port logic 'AUTO DURATION' sang Zen Core:
    - Nếu auto_duration_from_chords = True và có custom_chord_progression:
        => Tự tính total_duration_seconds dựa vào:
           + số chord
           + bars_per_chord
           + tempo hiện tại
    """
    if not options.get("auto_duration_from_chords", False):
        return

    progression = options.get("custom_chord_progression", "")
    if not progression:
        return

    bars_per_chord = float(options.get("bars_per_chord", 4.0) or 4.0)
    base_tempo = float(options.get("base_tempo", 60.0) or 60.0)

    # Đếm chord từ string progression (giống parse_progression_string)
    try:
        chords = parse_progression_string(progression)
        num_chords = max(1, len(chords))
    except Exception:
        num_chords = 8

    # 1 bar 4/4 ở 60 BPM ~ 4 giây
    seconds_per_bar = (60.0 / base_tempo) * 4.0
    total_bars = num_chords * bars_per_chord
    total_seconds = int(total_bars * seconds_per_bar)
    options["total_duration_seconds"] = total_seconds
    print(
        f"[NeoZen] Auto duration from chords: {num_chords} chords, "
        f"{bars_per_chord} bars/chord -> ~{total_seconds}s"
    )

def _build_output_paths(user_options: Dict[str, Any], output_root: str):
    """
    Port logic đặt tên file sang Zen Core:
    Tạo:
      output_root / 2025-11-29_2105_PROFILE_KEY_SCALE_[FreqTag] /
                   2025-11-29_2105_PROFILE_KEY_SCALE_[FreqTag].mid

    Ưu tiên:
      - Nếu user_options['output_mid_name'] có -> dùng làm filename.
      - Nếu user_options['session_name'] có   -> dùng làm folder.
      - Nếu không: auto đặt cả hai.
    """
    os.makedirs(output_root, exist_ok=True)

    # Nếu user đã override tên file cụ thể
    manual_mid_name = user_options.get("output_mid_name")
    manual_session = user_options.get("session_name")

    # Tag tần số / Journey
    freq_cfg = user_options.get("frequency_journey", {}) or {}
    if freq_cfg.get("enabled", False):
        freq_tag = "_Journey"
    else:
        try:
            solf = int(user_options.get("solf_profile", 528) or 528)
        except Exception:
            solf = 528
        freq_tag = f"_{solf}Hz"

    # Key/scale/mood để đặt tên
    key = str(user_options.get("key", "C")).replace("#", "s").replace(" ", "")
    scale = str(user_options.get("scale", "major")).replace(" ", "")
    mood = str(user_options.get("mood_label", "Zen")).replace(" ", "")

    now = datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%d_%H%M")

    default_session_name = f"{timestamp}_{mood}_{key}_{scale}{freq_tag}"

    if not manual_session:
        manual_session = default_session_name
    session_dir = os.path.join(output_root, manual_session)
    os.makedirs(session_dir, exist_ok=True)

    if not manual_mid_name:
        manual_mid_name = manual_session

    mid_filename = f"{manual_mid_name}.mid"
    final_midi_path = os.path.join(session_dir, mid_filename)
    return manual_session, session_dir, final_midi_path

# =========================
# 2. PUBLIC ENTRY
# =========================

def generate_zen_track(options_path: str) -> None:
    """
    Entry duy nhất được gọi từ app.py / UI.
    - Đọc user_options từ options_path (thường là runs/user_options.yaml).
    - Chuẩn hoá:
        + seed (ngẫu nhiên nếu None)
        + key / scale / base_tempo / total_duration_seconds
        + auto_duration_from_chords nếu bật
    - Suy ra: duration_sec, key, scale, output_root.
    - Gọi nội bộ _generate_zen_track_internal(...) để thực thi pipeline.
    """
    user_options: Dict[str, Any] = _load_yaml(options_path)

    # Chuẩn hoá & set seed cho toàn bộ pipeline (tránh int(None))
    seed = _normalize_seed(user_options)
    user_options["seed"] = seed
    random.seed(seed)
    print(f"[NeoZen] Using seed = {seed}")

    # Đặt mặc định cho một số tuỳ chọn mới (Handpan, Nature, Vocal, Bass...)
    user_options.setdefault("handpan_tuning_mode", "pure_key")  # đồng bộ UI V11

    # Nature & Vocal
    user_options.setdefault("enable_nature_layer", True)
    user_options.setdefault("v10_nature_profile", "v10_nature_default")
    user_options.setdefault("enable_vocal_layer", False)
    user_options.setdefault("v10_vocal_profile", "v10_vocal_om")

    # Bass
    user_options.setdefault("enable_bass_layer", True)
    user_options.setdefault("v10_bass_profile", "v10_bass_warm")

    # Handpan
    user_options.setdefault("enable_handpan_layer", False)
    user_options.setdefault("v10_handpan_profile", "v10_handpan_soft")

    # Phase 2: global semitone shift (MẶC ĐỊNH BẬT)
    user_options.setdefault("enable_phase2_semitone", True)
    user_options.setdefault("phase2_max_semitone", 6)

    # Phase 3: journey-based semitone (MẶC ĐỊNH BẬT)
    user_options.setdefault("enable_phase3_journey", True)
    user_options.setdefault("phase3_max_semitone_per_stage", 4)

    # Chuẩn hoá option cơ bản
    _validate_options(user_options)

    # Auto duration từ chord script (nếu bật)
    _auto_duration_from_chords(user_options)

    # Lấy tham số cơ bản (an toàn với None)
    duration_sec = _safe_int(user_options.get("total_duration_seconds", None), 600)
    key = user_options.get("key", "C")
    scale = user_options.get("scale", "major")

    # Nơi lưu file:(output/ hoặc runs/output/)
    output_root = user_options.get("output_root", "output")

    _generate_zen_track_internal(
        output_root=output_root,
        duration_sec=duration_sec,
        key=key,
        scale=scale,
        user_options=user_options,
    )

# =========================
# 3. INTERNAL PIPELINE
# =========================

def _generate_zen_track_internal(
    output_root: str,
    duration_sec: int,
    key: str,
    scale: str,
    user_options: Dict[str, Any],
) -> None:
    """
    Hàm nội bộ: giữ nguyên cấu trúc & logic soạn nhạc cơ bản,
    nhưng bây giờ:
        - Tự build tên file & thư mục theo pattern.
        - Gắn TuningCoreV3 (effective_key, frequency anchors).
        - ZenArcMatrix (5 phase).
        - BreathSyncManager (map tick -> breath / phase).
        - RegisterManager (quản lý quãng an toàn theo layer + phase).
        - SafetyFilter (Pitch / Velocity / Density / Shock).
        - ActivityMap V2 (Zen Director).
        - BassEngine + HandpanEngine: đã đấu dây nhưng có thể bật/tắt bằng flag.
        - PHASE 2: DynamicTransposingWriter với global semitone shift (static).
        - PHASE 3: Nếu bật, DynamicTransposingWriter dùng FrequencyJourney để đổi shift theo thời gian.
    """
    print("\n=== NEO ZEN CORE: GENERATION START ===")

    # 1. FOLDER & PATHS
    session_name, session_dir, final_midi_path = _build_output_paths(
        user_options, output_root
    )
    print(f"  > Session: {session_name}")
    print(f"  > Output MIDI: {final_midi_path}")

    # 2. PROFILE LOADER & TEMPO / BREATH
    loader = ProfileLoader(HARM_PROFILES, MELODY_PROFILES)
    bpm = float(user_options.get("base_tempo", 60))

    # BREATH CYCLE: ưu tiên user_options["breath_cycle_bars"], fallback theo breath_mode
    breath_mode = user_options.get("breath_mode", "auto")
    raw_cycle = user_options.get("breath_cycle_bars", None)
    try:
        breath_cycle = float(raw_cycle) if raw_cycle is not None else 0.0
    except (TypeError, ValueError):
        breath_cycle = 0.0

    if breath_cycle <= 0.0:
        if breath_mode in ("auto", "deep"):
            breath_cycle = 2.0  # ~8s @60BPM, 4/4
        elif breath_mode == "flow":
            breath_cycle = 1.0  # ~4s @60BPM, 4/4
        else:
            breath_cycle = 2.0

    print(f"  > Breath: mode={breath_mode}, cycle={breath_cycle} bars/breath")

    ppq = 480
    tempo_breath = TempoBreath(base_tempo=bpm, ppq=ppq, cycle_bars=breath_cycle)
    tempo_map: TempoMap = tempo_breath.generate_map(duration_sec)
    tempo_map.breath_cycle_bars = breath_cycle

    # 3. TUNING CORE (4 MODE) – XÁC ĐỊNH TUNING PLAN & EFFECTIVE KEY
    tuning_core = TuningCoreV3(user_options=user_options, preset=None)
    tuning_plan = tuning_core.build_plan()

    # effective_key = key dùng để soạn hoà âm / melody.
    effective_key = tuning_plan.new_key or key
    composition_scale = tuning_plan.scale or scale

    print(
        f"  > TuningPlan: mode={tuning_plan.mode}, "
        f"base_key={tuning_plan.base_key}, new_key={tuning_plan.new_key}, "
        f"primary_solf={tuning_plan.primary_solf_hz}, "
        f"secondary_solf={tuning_plan.secondary_solf_hz}, "
        f"global_semitone_planned={tuning_plan.global_semitone_shift_planned:.3f}",
    )
    print(
        f"  > Composition key: requested={key}, "
        f"effective={effective_key}, scale={composition_scale}"
    )

    # 3b. PHASE 2 – TÍNH GLOBAL SEMITONE SHIFT AN TOÀN
    enable_phase2 = bool(user_options.get("enable_phase2_semitone", False))
    max_abs_shift = int(user_options.get("phase2_max_semitone", 6) or 0)

    planned_shift = 0.0
    try:
        planned_shift = float(
            getattr(tuning_plan, "global_semitone_shift_planned", 0.0) or 0.0
        )
    except (TypeError, ValueError):
        planned_shift = 0.0

    if not enable_phase2 or max_abs_shift <= 0:
        global_semitone_shift = 0
        print(
            f"  > Phase2 Global Semitone: DISABLED "
            f"(planned={planned_shift:.3f}, max_abs={max_abs_shift})"
        )
    else:
        # Làm tròn & kẹp trong [-max_abs_shift, +max_abs_shift]
        s = int(round(planned_shift))
        if s > max_abs_shift:
            s = max_abs_shift
        if s < -max_abs_shift:
            s = -max_abs_shift
        global_semitone_shift = s
        print(
            f"  > Phase2 Global Semitone: ENABLED -> shift={global_semitone_shift} "
            f"(planned={planned_shift:.3f}, max_abs={max_abs_shift})"
        )

    # 4. ZEN ARC + BREATH + SAFETY CORES
    print("  > Initializing Zen Arc / Breath / Safety cores...")

    # Zen Arc Matrix (5 phase)
    zen_arc = ZenArcMatrix(user_options)

    # Breath Sync: map tick -> (breath_index, breath_phase)
    breath_sync = BreathSyncManager(tempo_map=tempo_map, user_options=user_options)

    # Register Manager
    register_manager = RegisterManager(
        tuning_core=tuning_core,
        user_options=user_options,
        tuning_plan=tuning_plan,
        tempo_map=tempo_map,
    )

    # Safety Filter
    safety_filter = SafetyFilter(
        user_options=user_options,
        register_manager=register_manager,
        tempo_map=tempo_map,
    )

    # 5. STRUCTURE
    print("  > Building structure (Zen Narrative + Phase Tags)...")

    struct_builder = StructureBuilder(
        tempo_map=tempo_map,
        key=effective_key,
        scale=composition_scale,
        ppq=ppq,
        user_options=user_options,
        zen_arc_matrix=zen_arc,
    )
    segments = struct_builder.build_segments()
    total_ticks = struct_builder.total_ticks
    print(f"  > Total segments: {len(segments)}, total_ticks={total_ticks}")

    # Debug: in segments nếu bật flag
    if user_options.get("debug_print_segments", False):
        print("  [DEBUG] Segments:")
        for idx, seg in enumerate(segments):
            print(
                f"    #{idx:02d} "
                f"ticks={seg.start_tick}->{seg.end_tick} "
                f"dur={seg.duration_ticks} "
                f"chord={getattr(seg, 'chord_name', '')} "
                f"section={getattr(seg, 'section_type', '')} "
                f"energy={getattr(seg, 'energy_bias', 0.0)}"
            )

    # 6. JOURNEYS (FREQUENCY / BRAINWAVE)
    print("  > Building Journeys (Frequency / Brainwave)...")

    freq_journey: FrequencyJourney = build_frequency_journey(
        user_options=user_options,
        total_ticks=total_ticks,
    )
    is_freq_journey_active = freq_journey.enabled and bool(freq_journey.stages)

    if is_freq_journey_active:
        print("  [FREQ JOURNEY] Active with stages:")
        for s in freq_journey.stages:
            print(
                f"    - {s.label}: {s.start_tick}->{s.end_tick}, "
                f"{s.start_hz}->{s.end_hz}Hz"
            )
    else:
        print("  [FREQ JOURNEY] Disabled or static profile.")

    brainwave_journey: BrainwaveJourney = build_brainwave_journey(
        user_options=user_options,
        total_ticks=total_ticks,
    )
    is_brain_journey_active = brainwave_journey.enabled and bool(
        brainwave_journey.stages
    )

    if is_brain_journey_active:
        print("  [BRAINWAVE JOURNEY] Active with stages:")
        for s in brainwave_journey.stages:
            print(
                f"    - {s.label}: {s.start_tick}->{s.end_tick}, "
                f"{s.start_beat_hz}->{s.end_beat_hz}Hz"
            )
    else:
        print("  [BRAINWAVE JOURNEY] Disabled or static (will use band/default Hz).")

    # 7. BASE WRITER + ACTIVITY MAP V2 + PHASE 3 JOURNEY SEMITONE
    writer = MidiWriter(ppq=ppq, tempo_map=tempo_map)
    activity_map = ActivityMap(
        tempo_map=tempo_map,
        zen_arc_matrix=zen_arc,
        breath_sync=breath_sync,
        user_options=user_options,
        total_ticks=total_ticks,
        rng_seed=user_options.get("activity_rng_seed", user_options.get("seed")),
    )

    enable_phase3 = bool(user_options.get("enable_phase3_journey", False))
    max_stage_shift = int(user_options.get("phase3_max_semitone_per_stage", 4) or 0)

    journey_for_transposer = None

    if (
        enable_phase3
        and is_freq_journey_active
        and max_stage_shift > 0
        and len(freq_journey.stages) > 0
    ):
        # Tính shift local cho từng Stage dựa trên tần số
        base_stage = freq_journey.stages[0]
        # Ưu tiên start_hz, fallback sang end_hz hoặc solf_profile
        base_hz = float(
            getattr(base_stage, "start_hz", 0.0)
            or getattr(base_stage, "end_hz", 0.0)
            or (user_options.get("solf_profile") or 0.0)
        )
        if base_hz <= 0.0:
            # Fallback cuối cùng: primary_solf_hz hoặc 528 Hz
            base_hz = float(
                getattr(tuning_plan, "primary_solf_hz", 0.0)
                or getattr(tuning_plan, "secondary_solf_hz", 0.0)
                or 528.0
            )

        print(
            f"  > Phase3 Journey Semitone: ENABLED "
            f"(base_hz={base_hz:.3f}, max_stage_shift={max_stage_shift}, "
            f"global_shift={global_semitone_shift})"
        )

        for idx, stage in enumerate(freq_journey.stages):
            # Lấy tần số đại diện cho Stage
            f_stage = float(
                getattr(stage, "start_hz", 0.0)
                or getattr(stage, "end_hz", 0.0)
                or base_hz
            )
            if f_stage <= 0.0 or base_hz <= 0.0:
                local_shift = 0
            else:
                # 12 * log2(f_stage / base_hz)
                ratio = f_stage / base_hz
                try:
                    local = 12.0 * math.log(ratio, 2.0)
                except ValueError:
                    local = 0.0
                # Làm tròn & kẹp
                s_local = int(round(local))
                if s_local > max_stage_shift:
                    s_local = max_stage_shift
                if s_local < -max_stage_shift:
                    s_local = -max_stage_shift
                local_shift = s_local

            # Stage shift = global shift + local
            total_stage_shift = global_semitone_shift + local_shift

            # Gắn thuộc tính cho DynamicTransposer
            setattr(stage, "shift_semitones", int(total_stage_shift))

            print(
                f"    [Stage {idx}] {stage.label}: f≈{f_stage:.3f}Hz, "
                f"local_shift={local_shift}, "
                f"stage_shift_total={total_stage_shift}"
            )

        journey_for_transposer = freq_journey
    else:
        if not enable_phase3:
            print("  > Phase3 Journey Semitone: DISABLED (flag off).")
        elif not is_freq_journey_active:
            print(
                "  > Phase3 Journey Semitone: DISABLED "
                "(FrequencyJourney not active)."
            )
        elif max_stage_shift <= 0:
            print(
                "  > Phase3 Journey Semitone: DISABLED "
                "(phase3_max_semitone_per_stage <= 0)."
            )

    # DynamicTransposingWriter:
    trans_writer = DynamicTransposingWriter(
        writer,
        journey=journey_for_transposer,
        default_shift=global_semitone_shift,
    )

    # ============================================================
    # 8. EXECUTE LAYERS (ENGINES)
    # ============================================================

    # --- A. MELODY ---
    print("  > Weaving Melody...")
    mel_prof_name = user_options.get("v9_melody_persona", "flute_flow")
    mel_prof = loader.get_melody_profile(mel_prof_name)
    if not mel_prof:
        mel_prof = loader.get_melody_profile("flute_flow")
    if mel_prof:
        mel_eng = MelodyEngine(
            trans_writer,
            mel_prof,
            ppq=ppq,
            user_options=user_options,
            activity_map=activity_map,
            tempo_map=tempo_map,
            register_manager=register_manager,
            safety_filter=safety_filter,
            breath_sync=breath_sync,
        )
        mel_eng.render(
            segments=segments,
            key=effective_key,
            scale=composition_scale,
            tempo_map=tempo_map,
            activity_map=activity_map,
        )
    else:
        print("  [Melody] No valid melody profile found, skipping Melody layer.")

    # --- B. PULSE ---
    print("  > Building Pulse / Rhythmic bed...")
    pulse_prof_name = user_options.get("v9_pulse_profile", "pulse_kalimba_texture")
    pulse_prof = loader.get_melody_profile(pulse_prof_name)
    if not pulse_prof:
        pulse_prof = loader.get_melody_profile("pulse_kalimba_texture")
    if pulse_prof:
        pulse_eng = PulseEngine(
            trans_writer,
            pulse_prof,
            ppq=ppq,
            user_options=user_options,
            activity_map=activity_map,
            tempo_map=tempo_map,
            register_manager=register_manager,
            safety_filter=safety_filter,
            breath_sync=breath_sync,
        )
        pulse_eng.render(
            segments=segments,
            key=effective_key,
            scale=composition_scale,
            tempo_map=tempo_map,
            activity_map=activity_map,
        )
    else:
        print("  [Pulse] No valid pulse profile found, skipping Pulse layer.")

    # --- C. HARM (PAD / STRINGS) ---
    print("  > Expanding Space (Harm)...")
    harm_style = user_options.get("v9_harm_style", "layered")

    if harm_style == "layered":
        prof_main = loader.get_harm_profile("v8_warm_pad")
        prof_layer = loader.get_harm_profile("v8_slow_strings")
        if prof_main:
            h_eng = HarmEngine(
                trans_writer,
                prof_main,
                channel=1,
                role="main",
                safety_filter=safety_filter,
                register_manager=register_manager,
                breath_sync=breath_sync,
                activity_map=activity_map,
                zen_arc_matrix=zen_arc,
            )
            h_eng.render(
                segments=segments,
                key=effective_key,
                scale=composition_scale,
                tempo_map=tempo_map,
                activity_map=activity_map,
            )
            # HARM LAYER (strings overlay)
            if prof_layer:
                l_eng = HarmEngine(
                    trans_writer,
                    prof_layer,
                    channel=3,
                    role="layer",
                    safety_filter=safety_filter,
                    register_manager=register_manager,
                    breath_sync=breath_sync,
                    activity_map=activity_map,
                    zen_arc_matrix=zen_arc,
                )
                l_eng.render_layer(
                    segments,
                    h_eng.get_voicing_map() if prof_main else {},
                    "normal",
                    1,
                    tempo_map,
                )
    else:
        ref_map = {
            "pad": "v8_warm_pad",
            "modal_texture": "harm_modal_texture",
            "arpeggio": "piano_arp",
        }
        prof_name = ref_map.get(harm_style, "v8_warm_pad")
        prof = loader.get_harm_profile(prof_name)
        if prof:
            h_eng = HarmEngine(
                trans_writer,
                prof,
                channel=1,
                role="main",
                safety_filter=safety_filter,
                register_manager=register_manager,
                breath_sync=breath_sync,
                activity_map=activity_map,
                zen_arc_matrix=zen_arc,
            )
            h_eng.render(
                segments=segments,
                key=effective_key,
                scale=composition_scale,
                tempo_map=tempo_map,
                activity_map=activity_map,
            )
        else:
            print(f"  [Harm] Profile '{prof_name}' not found, skipping Harm layer.")

    # --- D. DRONE / AIR / CHIME ---
    print("  > Adding Drone / Air / Chime layers...")

    # DRONE
    drone_prof_name = user_options.get("v9_drone_profile", "v9_drone_base")
    drone_prof = loader.get_harm_profile(drone_prof_name)
    if drone_prof:
        drone_eng = DroneEngine(
            trans_writer,
            drone_prof,
            channel=2,
            safety_filter=safety_filter,
            register_manager=register_manager,
            breath_sync=breath_sync,
            activity_map=activity_map,
            zen_arc_matrix=zen_arc,
        )
        drone_eng.render(
            segments=segments,
            key=effective_key,
            scale=composition_scale,
            tempo_map=tempo_map,
            activity_map=activity_map,
            tuning_plan=tuning_plan,  # V11 hook: thông tin tuning vẫn giữ nguyên
        )
    else:
        print(f"  [Drone] Profile '{drone_prof_name}' not found, skipping Drone layer.")

    # AIR (Ưu tiên v10_air_profile, rồi air_profile; "off" => skip)
    air_prof_name = resolve_air_profile_from_options(user_options)
    if air_prof_name:
        air_prof = loader.get_harm_profile(air_prof_name)
    else:
        air_prof = None

    if air_prof:
        air_eng = AirEngine(
            trans_writer,
            air_prof,
            channel=5,
            safety_filter=safety_filter,
            register_manager=register_manager,
            breath_sync=breath_sync,
            activity_map=activity_map,
            zen_arc_matrix=zen_arc,
        )
        air_eng.render(
            segments=segments,
            key=effective_key,
            scale=composition_scale,
            tempo_map=tempo_map,
            activity_map=activity_map,
        )
    else:
        print(
            f"  [Air] Profile '{air_prof_name}' not found or disabled, skipping Air layer."
        )

    # CHIME (Ưu tiên v10_chime_profile, rồi chime_profile; "off" => skip)
    chime_prof_name = resolve_chime_profile_from_options(user_options)
    if chime_prof_name:
        chime_prof = loader.get_harm_profile(chime_prof_name)
    else:
        chime_prof = None

    if chime_prof:
        chime_eng = ChimeEngine(
            trans_writer,
            chime_prof,
            channel=6,
            safety_filter=safety_filter,
            register_manager=register_manager,
            breath_sync=breath_sync,
            activity_map=activity_map,
            zen_arc_matrix=zen_arc,
        )
        chime_eng.render(
            segments=segments,
            key=effective_key,
            scale=composition_scale,
            tempo_map=tempo_map,
            activity_map=activity_map,
        )
    else:
        print(
            f"  [Chime] Profile '{chime_prof_name}' not found or disabled, skipping Chime layer."
        )

    # --- E. BASS ---
    if user_options.get("enable_bass_layer", True):
        print("  > Adding Bass layer...")
        bass_profile_name = user_options.get("v10_bass_profile", "v10_bass_warm")
        bass_prof = loader.get_harm_profile(bass_profile_name)
        if bass_prof:
            bass_eng = BassEngine(
                trans_writer,
                bass_prof,
                ppq=ppq,
                user_options=user_options,
                safety_filter=safety_filter,
                register_manager=register_manager,
                breath_sync=breath_sync,
                activity_map=activity_map,
                zen_arc_matrix=zen_arc,
                layer_name="bass",
            )
            bass_eng.render(
                segments=segments,
                tempo_map=tempo_map,
                tuning_plan=tuning_plan,
            )
        else:
            print(
                f"  [Bass] Profile '{bass_profile_name}' not found, skipping Bass layer."
            )
    else:
        print("  [Bass] Disabled via user_options, skipping Bass layer.")

    # --- F. HANDPAN ---
    if user_options.get("enable_handpan_layer", False):
        print("  > Adding Handpan layer...")
        handpan_profile_name = user_options.get(
            "v10_handpan_profile", "v10_handpan_soft"
        )
        # Handpan mang tính melodic/rhythmic → dùng melody_profiles
        handpan_prof = loader.get_melody_profile(handpan_profile_name)
        if handpan_prof:
            handpan_eng = HandpanEngine(
                trans_writer,
                handpan_prof,
                channel=10,
                safety_filter=safety_filter,
                register_manager=register_manager,
                breath_sync=breath_sync,
                activity_map=activity_map,
                zen_arc_matrix=zen_arc,
                tempo_map=tempo_map,
                user_options=user_options,
            )
            handpan_eng.render(
                segments=segments,
                key=effective_key,
                scale=composition_scale,
                tempo_map=tempo_map,
                activity_map=activity_map,
                tuning_plan=tuning_plan,
            )
        else:
            print(
                f"  [Handpan] Profile '{handpan_profile_name}' not found, skipping Handpan layer."
            )
    else:
        print("  [Handpan] Disabled via user_options, skipping Handpan layer.")

    # --- G. NATURE ---
    if user_options.get("enable_nature_layer", True):
        print("  > Adding Nature layer...")
        nature_profile_name = user_options.get(
            "v10_nature_profile", "v10_nature_default"
        )
        nature_prof = loader.get_harm_profile(nature_profile_name)
        if nature_prof:
            nature_eng = NatureEngine(
                trans_writer,
                nature_prof,
                channel=7,
                safety_filter=safety_filter,
                register_manager=register_manager,
                breath_sync=breath_sync,
                activity_map=activity_map,
                zen_arc_matrix=zen_arc,
            )
            nature_eng.render(
                segments=segments,
                key=effective_key,
                scale=composition_scale,
                tempo_map=tempo_map,
                activity_map=activity_map,
            )
        else:
            print(
                f"  [Nature] Profile '{nature_profile_name}' not found, skipping Nature layer."
            )
    else:
        print("  [Nature] Disabled via user_options, skipping Nature layer.")

    # --- H. VOCAL (OM / CHANT) ---
    if user_options.get("enable_vocal_layer", False):
        print("  > Adding Vocal layer...")
        vocal_profile_name = user_options.get("v10_vocal_profile", "v10_vocal_om")
        vocal_prof = loader.get_harm_profile(vocal_profile_name)
        if vocal_prof:
            vocal_eng = VocalEngine(
                trans_writer,
                vocal_prof,
                channel=8,
                safety_filter=safety_filter,
                register_manager=register_manager,
                breath_sync=breath_sync,
                activity_map=activity_map,
                zen_arc_matrix=zen_arc,
            )
            vocal_eng.render(
                segments=segments,
                key=effective_key,
                scale=composition_scale,
                tempo_map=tempo_map,
                activity_map=activity_map,
            )
        else:
            print(
                f"  [Vocal] Profile '{vocal_profile_name}' not found, skipping Vocal layer."
            )
    else:
        print("  [Vocal] Disabled via user_options, skipping Vocal layer.")

    # --- I. BINAURAL ---
    print("  > Adding Binaural layer (if configured)...")

    binaural_cfg = user_options.get("binaural", {}) or {}
    binaural_enabled = bool(binaural_cfg.get("enabled", True))
    if binaural_enabled:
        # Chọn profile (mặc định vẫn là v9_drone_base để giữ chất cũ)
        binaural_profile_name = binaural_cfg.get("profile", "v9_drone_base")
        bin_prof = loader.get_harm_profile(binaural_profile_name)
        if not bin_prof:
            print(
                f"  [Binaural] Profile '{binaural_profile_name}' not found, "
                "skipping Binaural layer."
            )
        else:
            # Setup 2 track L/R – giữ nguyên tư tưởng cũ, nhưng cho phép override channel
            left_ch = int(
                binaural_cfg.get(
                    "left_channel",
                    getattr(bin_prof, "channel", 13),
                )
            )
            right_ch = int(binaural_cfg.get("right_channel", left_ch + 1))
            bin_prof.channel = left_ch
            t_bin_l = writer.get_track(left_ch)
            t_bin_r = writer.get_track(right_ch)
            t_bin_l.set_program(bin_prof.program)
            t_bin_r.set_program(bin_prof.program)
            t_bin_l.set_name("BINAURAL L")
            t_bin_r.set_name("BINAURAL R")

            # Khởi tạo Engine theo chuẩn V11 (có đủ hook an toàn)
            bin_eng = BinauralEngine(
                writer,  # LƯU Ý: dùng writer raw, không transpose
                bin_prof,
                user_options=user_options,
                safety_filter=safety_filter,
                register_manager=register_manager,
                breath_sync=breath_sync,
                activity_map=activity_map,
                zen_arc_matrix=zen_arc,
                layer_name="binaural",
            )

            # 1) Base anchor frequency
            base_freq_hz = float(binaural_cfg.get("base_freq_hz", 0.0) or 0.0)
            if base_freq_hz <= 0.0:
                if getattr(tuning_plan, "primary_solf_hz", 0.0) > 0.0:
                    base_freq_hz = tuning_plan.primary_solf_hz
                elif getattr(tuning_plan, "secondary_solf_hz", 0.0) > 0.0:
                    base_freq_hz = tuning_plan.secondary_solf_hz
                else:
                    try:
                        root_pc = NOTE_TO_PC[effective_key]
                    except Exception:
                        root_pc = NOTE_TO_PC.get("C", 0)
                    base_freq_hz = midi_to_hz(root_pc + 36)

            # 2) Base beat Hz
            base_beat_hz = float(binaural_cfg.get("beat_hz", 4.0) or 4.0)
            if base_beat_hz <= 0.0:
                base_beat_hz = 4.0

            # 3) Fade config
            default_fade_in = ppq * 2   # ~2 bar @60BPM
            default_fade_out = ppq * 4  # ~4 bar cuối
            fade_in_ticks = int(binaural_cfg.get("fade_in_ticks", default_fade_in))
            fade_out_ticks = int(binaural_cfg.get("fade_out_ticks", default_fade_out))
            fade_cfg = {
                "in": max(0, fade_in_ticks),
                "out_start": max(0, total_ticks - max(0, fade_out_ticks)),
                "out": max(0, fade_out_ticks),
                "total": total_ticks,
            }

            # 4) Gọi render – SAFE MODE
            bin_eng.render(
                segments=segments,
                base_freq=base_freq_hz,
                base_beat_hz=base_beat_hz,
                tempo_map=tempo_map,
                fade_cfg=fade_cfg,
                tuning_plan=tuning_plan,
                brainwave_journey=(
                    brainwave_journey if is_brain_journey_active else None
                ),
            )

            # 5) Logging Frequency Journey
            if is_freq_journey_active:
                print("  [Binaural] Frequency Journey active (Phase 3 = log only):")
                for idx, stage in enumerate(freq_journey.stages):
                    print(
                        f"    - Stage {idx} {stage.label}: "
                        f"{stage.start_tick}->{stage.end_tick} ticks, "
                        f"{stage.start_hz}->{stage.end_hz}Hz"
                    )
            else:
                print(
                    "  [Binaural] Using static anchor/beat "
                    "(no Frequency Journey binding in Phase 3)."
                )
    else:
        print("  [Binaural] Disabled via user_options, skipping Binaural entirely.")

    # ============================================================
    # 9. FLUSH MIDI
    # ============================================================
    print("  > Writing MIDI file...")
    writer.save(final_midi_path)
    print("=== NEO ZEN CORE: GENERATION DONE ===\n")
