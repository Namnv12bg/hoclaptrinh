# Tệp: app.py
# (FINAL CLEAN V11.0.2) - UNIFIED UI FOR NEO ZEN CORE + TUNING + JOURNEYS + DEBUG FLAGS
#
# Kiến trúc:
# - UI chỉ còn một pipeline duy nhất: gọi Neo Zen Core (generate_zen_track),
#   không còn Standard vs Zen tách riêng, không còn trung gian.
# - Zen Core luôn bật. Không có toggle ON/OFF.
# - Tab 2:
#   + Chọn drone_mode (4 mode TuningCore: pure_key / solf_root / solf_dual / key_plus_solf_drone).
#   + Static Solfeggio (solf_profile).
#   + Frequency Journey (tần số vật lý) – độc lập.
#   + Brainwave Journey (sóng não, beat Hz) – độc lập nhưng có thể khóa với Frequency Journey.
# - Tab 3:
#   + Tempo / Duration / Breath.
#   + Key / Scale / Chord Script.
#   + Debug Flags: debug_print_segments, debug_print_notes.
# - breath_cycle_bars luôn bị ép >= 0.5 để tránh bug.
# - V11 bổ sung:
#   + BassEngineV1 & HandpanEngineV1: control ở Tab 1.
#   + Mapping 'binaural' config cho Zen Core (enabled + beat_hz).
# - V11.0.2:
#   + Chuẩn hoá key AIR/CHIME khớp với melody_profiles.yaml:
#       * v10_air_profile: "air_crystal_shimmer" / "off"
#       * v10_chime_profile: "chime_crystal_bell"
#   + Vẫn giữ v9_air_mode để tương thích UI cũ, nhưng engine đọc từ v10_air_profile.
#   + Đặt DEFAULT_PRESET_FILE = "config/presets/v11_full_default.yaml" (preset full ON mức trung bình).

import os
import yaml
import datetime
import streamlit as st
from typing import Dict, Any
import importlib
import traceback

# =========================
# 1. CONFIG & INFO MAPS
# =========================

DEFAULT_OPTIONS_FILE = "runs/user_options.yaml"
DEFAULT_PRESET_FILE = "config/presets/v11_full_default.yaml"
CUSTOM_LABEL = "Custom (Tự chỉnh)"

INFO_MAP: Dict[str, Dict[str, str]] = {
    "instruments": {
        "kintsugi": "Kintsugi: Piano rải nốt lấp lánh, tập trung chi tiết nhỏ, hợp Focus/Healing.",
        "flow": "Flow: Sáo trúc / Pan Flute kể chuyện chậm rãi, hợp Zen & Nature.",
        "mantra": "Mantra: Piano/Synth lặp đều, tạo cảm giác tụng niệm, hợp thiền sâu.",
        "sparks": "Sparks: Nốt rời ở quãng cao, hợp Deep Sleep / Space.",
        "heartbeat": "Heartbeat: Nhịp trầm, tạo cảm giác an toàn, giữ nhịp thở.",
        "shaman": "Shaman: Trống bộ lạc, năng lượng hơn, hợp Breathwork / Ritual.",
        "forest": "Forest: Sáo rừng + Marimba mộc, cho cảm giác đi giữa rừng.",
        "zen": "Zen: Shakuhachi & gõ mộc, rất tĩnh, hợp Zen Garden / Zazen.",
    },
    "frequencies": {
        "174": "174 Hz – Giảm đau thể chất.",
        "285": "285 Hz – Hồi phục mô & tế bào.",
        "396": "396 Hz – Giải phóng sợ hãi & tội lỗi.",
        "417": "417 Hz – Xoá bỏ tắc nghẽn / stuck energy.",
        "432": "432 Hz – Tuning tự nhiên, dịu hơn A440.",
        "528": "528 Hz – 'Love Frequency', healing & DNA.",
        "639": "639 Hz – Kết nối & quan hệ.",
        "741": "741 Hz – Thanh lọc & trực giác.",
        "852": "852 Hz – Trực giác & inner voice.",
        "963": "963 Hz – 'God frequency', cảm giác mở rộng.",
    },
    "tuning": {
        "retune": "Retune: Dịch toàn bộ bài hát về tần số Solfeggio (vd 528 Hz) thay vì A440.",
        "tags": "Chord Script: Dùng thẻ <Intro>, <Verse>, <Chorus> trong kịch bản hợp âm để engine hiểu cấu trúc.",
        "strum": "Zen Strum: Gảy Harp/Piano theo kiểu arpeggio khi đổi hợp âm.",
    },
}

# =========================
# 2. YAML HELPERS
# =========================

def load_yaml_file(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}

def save_yaml_file(path: str, data: Dict[str, Any]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)

# =========================
# 2b. SAFE RERUN HELPER
# =========================

def safe_rerun():
    """
    Tương thích nhiều version Streamlit:
    - Streamlit mới: dùng st.rerun()
    - Streamlit cũ: dùng st.experimental_rerun()
    - Nếu không có cái nào thì bỏ qua (tránh crash).
    """
    try:
        if hasattr(st, "rerun") and callable(getattr(st, "rerun")):
            st.rerun()
        elif hasattr(st, "experimental_rerun") and callable(
            getattr(st, "experimental_rerun")
        ):
            st.experimental_rerun()
    except Exception:
        # Không làm gì thêm, chỉ tránh crash UI
        pass

# =========================
# 3. RUN PIPELINE (UNIFIED)
# =========================

def run_generation(settings: Dict[str, Any], template_name: str):
    """
    Ghi user_options.yaml và gọi Zen Core (generate_zen_track).
    Zen Core sẽ tự quyết:
        - Static vs Journey (frequency_journey.enabled).
        - 4 chế độ Tuning (drone_mode).
        - Brainwave Journey vs static band.
        - Bio-Sync (Breath, Pulse, Chime...) dựa trên options.
    """
    try:
        # Ghi profile đang dùng
        if template_name != CUSTOM_LABEL:
            settings["zen_profile"] = template_name
        else:
            settings["zen_profile"] = "custom"

        # Đồng bộ config Binaural cho Zen Core (V11):
        # - brainwave_enable -> binaural.enabled
        # - binaural_beat_hz -> binaural.beat_hz (nếu > 0)
        binaural_cfg = settings.get("binaural", {}) or {}
        binaural_cfg["enabled"] = bool(settings.get("brainwave_enable", False))
        beat_custom = float(settings.get("binaural_beat_hz", 0.0) or 0.0)
        if beat_custom > 0.0:
            binaural_cfg["beat_hz"] = beat_custom
        settings["binaural"] = binaural_cfg

        # Đảm bảo profile CHIME/AIR chuẩn hoá trước khi ghi
        settings.setdefault("v10_chime_profile", "chime_crystal_bell")
        if settings.get("v10_air_profile") == "off":
            # Engine sẽ bỏ qua nếu profile không tìm thấy
            pass
        else:
            settings.setdefault("v10_air_profile", "air_crystal_shimmer")

        # Ghi YAML cho Unified Engine
        save_yaml_file(DEFAULT_OPTIONS_FILE, settings)

        # Chuẩn bị output dir (Zen Core sẽ dùng)
        output_dir = "output"
        os.makedirs(output_dir, exist_ok=True)

        # Import & reload Zen Core (hot reload khi bạn sửa code)
        from src import zen_core as zen_core
        importlib.reload(zen_core)

        with st.spinner("Đang thiền định với Neo Zen Core..."):
            # giả định signature: generate_zen_track(options_path: str)
            zen_core.generate_zen_track(DEFAULT_OPTIONS_FILE)

        st.success("Hoàn tất! File MIDI nằm trong thư mục 'output/'")
        st.balloons()

    except Exception as e:
        # Hiện lỗi chính
        st.error(f"Lỗi Zen Core: {e}")

        # Lấy full traceback
        tb = traceback.format_exc()

        # In ra UI để dễ copy
        st.code(tb)

        # In ra console (cửa sổ cmd) cho chắc
        print("\n===== TRACEBACK FROM NEO ZEN CORE =====")
        print(tb)
        print("===================================\n")

# =========================
# 4. MAIN UI
# =========================

def main():
    st.set_page_config(
        page_title="Neo Zen Engine V11 (Unified Core)",
        layout="wide",
        page_icon="🧘",
    )

    st.title("Neo Zen Engine V11.0 (Unified Journey UI)")

    if "last_template" not in st.session_state:
        st.session_state["last_template"] = None

    # Load options & preset
    user_opts = load_yaml_file(DEFAULT_OPTIONS_FILE)
    preset_data = load_yaml_file(DEFAULT_PRESET_FILE)

    zen_templates = preset_data.get("zen_templates", {}) or {}
    template_names = [CUSTOM_LABEL] + list(zen_templates.keys())

    # Bản settings đang active
    active_settings: Dict[str, Any] = user_opts.copy()

    # ========== SIDEBAR ==========
    with st.sidebar:
        st.header("Điều Khiển")

        # Zen Core luôn bật – không còn Standard/V9 riêng nữa
        active_settings["zen_mode_enabled"] = True

        st.info(
            "**Neo Zen Core V11 luôn hoạt động:**\n"
            "- Zen Arc & Bio-Sync (nhịp thở, nhịp tim)\n"
            "- Drone Bridge & Ping-Pong khi bật Frequency Journey\n"
            "- Static / Dynamic Solfeggio & Binaural chỉnh ở Tab 2\n\n"
            "Bạn chỉ cần chọn preset và chỉnh tham số; bật/tắt các Journey được điều khiển "
            "trực tiếp trong Tab **Tần Số & Journey**."
        )

        # Chọn preset / template
        selected_template = st.selectbox("Chọn Mẫu (Mood)", template_names)
        template_changed = (selected_template != st.session_state["last_template"])
        st.session_state["last_template"] = selected_template

        # Khi chọn template khác → apply override và reload UI
        if (
            template_changed
            and selected_template != CUSTOM_LABEL
            and selected_template in zen_templates
        ):
            tmpl = zen_templates[selected_template]
            if "options_override" in tmpl:
                active_settings.update(tmpl["options_override"] or {})
            if "preset_override" in tmpl:
                active_settings.update(tmpl["preset_override"] or {})

            save_yaml_file(DEFAULT_OPTIONS_FILE, active_settings)
            safe_rerun()

        # Hiển thị mô tả template nếu có
        if selected_template != CUSTOM_LABEL and selected_template in zen_templates:
            tmpl = zen_templates[selected_template]
            label = tmpl.get("label", "").strip()
            desc = tmpl.get("description", "").strip()
            if label or desc:
                st.info(f"**{label}**\n\n{desc}")

        st.divider()
        run_clicked = st.button("🎼 Sáng Tác Ngay", type="primary")

    # ========== TABS ==========
    tab1, tab2, tab3 = st.tabs(
        ["🎻 Dàn Nhạc", "🔭 Tần Số & Journey", "📐 Cấu Trúc & Hơi Thở"]
    )

    # -------------------------
    # TAB 1 – DÀN NHẠC
    # -------------------------
    with tab1:
        col1, col2 = st.columns(2)

        # ===== COL 1: MELODY + HARM =====
        with col1:
            st.subheader("Giai Điệu (Voice)")

            MELODY_MAP = {
                "🎋 Flute (Trúc)": "flute_flow",
                "🧘 Shakuhachi (Zen)": "shakuhachi_zen",
                "🌲 Pan Flute (Rừng)": "pan_flute_forest",
                "💎 Piano Kintsugi": "piano_kintsugi",
                "🔁 Piano Mantra (Classic)": "piano_mantra",
                "🧠 Piano Zen (Smart Flow)": "piano_zen_flow",
                "🎐 Sitar (Yoga)": "sitar_mantra",
                "✨ Sparks (Sleep)": "flute_deep_sleep",
                "🔔 Crystal Bell": "crystal_bell_solo",
            }

            cur_mel = active_settings.get("v9_melody_persona", "flute_flow")
            mel_label = next(
                (k for k, v in MELODY_MAP.items() if v == cur_mel),
                "🎋 Flute (Trúc)",
            )

            sel_mel = st.selectbox(
                "Nhạc cụ Chính",
                list(MELODY_MAP.keys()),
                index=list(MELODY_MAP.keys()).index(mel_label),
            )
            active_settings["v9_melody_persona"] = MELODY_MAP[sel_mel]

            # Tooltip theo loại
            if "Kintsugi" in sel_mel:
                st.info(INFO_MAP["instruments"]["kintsugi"])
            elif "Flute" in sel_mel or "Pan Flute" in sel_mel:
                st.info(INFO_MAP["instruments"]["flow"])
            elif "Mantra" in sel_mel or "Sitar" in sel_mel:
                st.info(INFO_MAP["instruments"]["mantra"])
            elif "Sparks" in sel_mel:
                st.info(INFO_MAP["instruments"]["sparks"])

            st.caption(
                "Giai điệu luôn dùng bộ não V10/V11 (Generator mới). "
                "Khi bạn bật các Journey ở Tab 2, toàn bộ flow sẽ đi theo Zen Arc & Breath Map."
            )

            st.subheader("Lớp Nền (Space)")
            HARM_MAP = {
                "🌊 Layered Pad (Deep)": "layered",
                "🎹 Zen Strum (Arp)": "arpeggio",
                "☁️ Cloud (Texture)": "modal_texture",
                "🎼 Standard Pad": "pad",
            }
            cur_harm = active_settings.get("v9_harm_style", "layered")
            harm_label = next(
                (k for k, v in HARM_MAP.items() if v == cur_harm),
                "🌊 Layered Pad (Deep)",
            )
            sel_harm = st.selectbox(
                "Phong cách Hòa âm",
                list(HARM_MAP.keys()),
                index=list(HARM_MAP.keys()).index(harm_label),
            )
            active_settings["v9_harm_style"] = HARM_MAP[sel_harm]

            if "Layered" in sel_harm:
                st.caption("Pad dày, Layered, dùng Liquid Harmony, hợp Deep Meditation.")
            elif "Standard" in sel_harm:
                st.caption("Pad cơ bản, dùng profile Warm Pad giống lớp chính của Layered.")

        # ===== COL 2: PULSE + AIR + CHIME + NATURE + VOCAL + BASS/HANDPAN =====
        with col2:
            st.subheader("Nhịp Điệu (Heart)")

            # ----- PulseEngineV10 UI -----
            PULSE_CHOICES = {
                "🚫 Off": "off",
                "❤️ Heartbeat + Texture": "both",
                "❤️ Heartbeat only": "heart_only",
                "🔔 Texture only": "texture_only",
            }

            # Suy ra trạng thái hiện tại từ các flag
            cur_enable_pulse = bool(active_settings.get("enable_pulse", True))
            cur_enable_pulse_layer = bool(
                active_settings.get("enable_pulse_layer", True)
            )
            cur_enable_heartbeat_layer = bool(
                active_settings.get("enable_heartbeat_layer", True)
            )
            cur_enable_kalimba_layer = bool(
                active_settings.get("enable_kalimba_layer", True)
            )

            if not cur_enable_pulse or not cur_enable_pulse_layer:
                pulse_mode_val = "off"
            else:
                if cur_enable_heartbeat_layer and cur_enable_kalimba_layer:
                    pulse_mode_val = "both"
                elif cur_enable_heartbeat_layer and not cur_enable_kalimba_layer:
                    pulse_mode_val = "heart_only"
                elif (not cur_enable_heartbeat_layer) and cur_enable_kalimba_layer:
                    pulse_mode_val = "texture_only"
                else:
                    pulse_mode_val = "off"

            # Tìm label tương ứng
            pulse_label_cur = next(
                (k for k, v in PULSE_CHOICES.items() if v == pulse_mode_val),
                "🚫 Off",
            )

            sel_pulse_label = st.selectbox(
                "Heart Layer (Pulse V10)",
                list(PULSE_CHOICES.keys()),
                index=list(PULSE_CHOICES.keys()).index(pulse_label_cur),
                help=(
                    "Heartbeat: trống sâu giữ nhịp.\n"
                    "Texture: Kalimba/texture nhẹ hỗ trợ nhịp tim.\n"
                    "Cả hai: phù hợp Breathwork & thiền động.\n"
                    "Off: tắt hoàn toàn lớp nhịp."
                ),
            )
            pulse_mode = PULSE_CHOICES[sel_pulse_label]

            if pulse_mode == "off":
                active_settings["enable_pulse"] = False
                active_settings["enable_pulse_layer"] = False
                active_settings["enable_heartbeat_layer"] = False
                active_settings["enable_kalimba_layer"] = False
            else:
                active_settings["enable_pulse"] = True
                active_settings["enable_pulse_layer"] = True
                # Chuẩn hoá profile Pulse về pulse_kalimba_texture (melody_profiles.yaml)
                active_settings["v9_pulse_profile"] = "pulse_kalimba_texture"
                active_settings["enable_heartbeat_layer"] = pulse_mode in (
                    "both",
                    "heart_only",
                )
                active_settings["enable_kalimba_layer"] = pulse_mode in (
                    "both",
                    "texture_only",
                )

            with st.expander("Tinh chỉnh Pulse (Advanced)", expanded=False):
                cur_thr = float(
                    active_settings.get("pulse_activity_threshold", 0.6)
                )
                cur_red = float(
                    active_settings.get("pulse_reduction_ratio", 0.6)
                )
                active_settings["pulse_activity_threshold"] = st.slider(
                    "Ngưỡng Activity để Pulse né Melody",
                    0.0,
                    1.0,
                    cur_thr,
                    0.01,
                    help=(
                        "Activity càng cao (gần 1) nghĩa là Melody/Chime đang dày. "
                        "Pulse sẽ né những vùng vượt ngưỡng này."
                    ),
                )
                active_settings["pulse_reduction_ratio"] = st.slider(
                    "Tỉ lệ giảm mật độ Pulse khi bị trùng",
                    0.0,
                    1.0,
                    cur_red,
                    0.01,
                    help=(
                        "0.0: gần như tắt Pulse ở vùng bận.\n"
                        "1.0: hầu như không giảm (Pulse vẫn chạy mạnh)."
                    ),
                )

            # ===== AIR LAYER (AirEngineV1) =====
            st.subheader("Không Khí (Spirit)")

            # Chuẩn hoá key AIR theo melody_profiles.yaml
            active_settings.setdefault("v10_air_profile", "air_crystal_shimmer")
            # Giữ v9_air_mode cho tương thích UI cũ (meta)
            cur_air_profile = active_settings.get("v10_air_profile", "air_crystal_shimmer")
            if cur_air_profile == "off":
                cur_air_label = "🚫 Off"
            else:
                cur_air_label = "🌫 Air Layer (Crystal Shimmer)"

            AIR_MAP = {
                "🌫 Air Layer (Crystal Shimmer)": "on",
                "🚫 Off": "off",
            }

            sel_air = st.selectbox(
                "Hiệu ứng Air",
                list(AIR_MAP.keys()),
                index=list(AIR_MAP.keys()).index(cur_air_label),
                help="Lớp Air rất mỏng, thở chậm và shimmer nhẹ, phù hợp nền thiền sâu.",
            )
            air_state = AIR_MAP[sel_air]

            if air_state == "off":
                active_settings["v10_air_profile"] = "off"     # Engine sẽ skip nếu không tìm thấy profile
                active_settings["v9_air_mode"] = "off"         # Giữ để không phá preset cũ
            else:
                active_settings["v10_air_profile"] = "air_crystal_shimmer"
                # Gợi ý meta để preset YAML đọc cho đẹp, không ảnh hưởng engine:
                active_settings["v9_air_mode"] = "air_shimmer"

            # ===== CHIME LAYER =====
            st.subheader("Chuông (Awaken)")

            # Chuẩn hoá profile chime mặc định khớp melody_profiles.yaml
            active_settings.setdefault("v10_chime_profile", "chime_crystal_bell")

            cur_chime = float(active_settings.get("chime_density", 0.5))
            chime_den = st.slider(
                "Mật độ Chuông",
                0.0,
                1.0,
                cur_chime,
                0.01,
                help="0.01: Rất thưa (điểm nhịp thỉnh thoảng).",
            )
            active_settings["chime_density"] = chime_den

            CHIME_MODES = {
                "🌬 Breathing": "breathing",
                "📍 Static": "static",
            }
            cur_c_mode = active_settings.get("chime_mode", "breathing")
            c_lbl = next(
                (k for k, v in CHIME_MODES.items() if v == cur_c_mode),
                "🌬 Breathing",
            )
            sel_c = st.radio(
                "Chế độ Chuông",
                list(CHIME_MODES.keys()),
                index=list(CHIME_MODES.keys()).index(c_lbl),
            )
            active_settings["chime_mode"] = CHIME_MODES[sel_c]

            # ===== NATURE LAYER (NatureEngineV1) =====
            st.subheader("Thiên Nhiên (Nature)")

            # đảm bảo có profile default
            active_settings.setdefault("v10_nature_profile", "v10_nature_default")

            enable_nature = bool(
                active_settings.get("enable_nature_layer", True)
            )
            enable_nature = st.checkbox(
                "Bật Nature Layer (mưa, rừng, suối, lửa...)",
                value=enable_nature,
            )
            active_settings["enable_nature_layer"] = enable_nature

            if enable_nature:
                NATURE_TYPES = {
                    "🌲 Forest (chim, lá)": "forest",
                    "🌧 Rain": "rain",
                    "💧 River": "river",
                    "🌊 Ocean": "ocean",
                    "🔥 Fireplace": "fireplace",
                }
                cur_nature_type = active_settings.get(
                    "nature_profile", "forest"
                )
                nat_lbl = next(
                    (k for k, v in NATURE_TYPES.items() if v == cur_nature_type),
                    "🌲 Forest (chim, lá)",
                )
                sel_nat = st.selectbox(
                    "Kiểu Nature",
                    list(NATURE_TYPES.keys()),
                    index=list(NATURE_TYPES.keys()).index(nat_lbl),
                )
                active_settings["nature_profile"] = NATURE_TYPES[sel_nat]

                cur_nat_int = float(
                    active_settings.get("nature_intensity", 0.7)
                )
                active_settings["nature_intensity"] = st.slider(
                    "Độ mạnh Nature",
                    0.0,
                    1.0,
                    cur_nat_int,
                    0.01,
                    help="0.0: gần như tắt, 1.0: dày nhất (vẫn được Zen Arc & Breath điều tiết).",
                )

                cur_nat_breath = float(
                    active_settings.get("nature_breath_amount", 0.7)
                )
                active_settings["nature_breath_amount"] = st.slider(
                    "Độ nhạy với nhịp thở",
                    0.0,
                    1.0,
                    cur_nat_breath,
                    0.01,
                    help="Càng cao, Nature càng “thở” theo Inhale/Exhale.",
                )

                NATURE_BREAK = {
                    "Mute ở Breakdown": "mute",
                    "Soft ở Breakdown": "soft",
                    "Normal (như các đoạn khác)": "normal",
                }
                cur_nb_mode = active_settings.get(
                    "nature_breakdown_mode", "soft"
                )
                nb_lbl = next(
                    (k for k, v in NATURE_BREAK.items() if v == cur_nb_mode),
                    "Soft ở Breakdown",
                )
                sel_nb = st.radio(
                    "Hành vi trong đoạn Breakdown",
                    list(NATURE_BREAK.keys()),
                    index=list(NATURE_BREAK.keys()).index(nb_lbl),
                )
                active_settings["nature_breakdown_mode"] = NATURE_BREAK[sel_nb]

            # ===== VOCAL LAYER (VocalEngineV1) =====
            st.subheader("Vocal (OM / Chant)")

            active_settings.setdefault("v10_vocal_profile", "v10_vocal_om")

            enable_vocal = bool(
                active_settings.get("enable_vocal_layer", False)
            )
            enable_vocal = st.checkbox(
                "Bật Vocal Layer (OM / Chant)",
                value=enable_vocal,
            )
            active_settings["enable_vocal_layer"] = enable_vocal

            if enable_vocal:
                VOCAL_MODES = {
                    "OM Pulse (OM dài, thưa)": "om_pulse",
                    "Long Drone (OM rất dài)": "long_drone",
                    "Call & Response": "call_response",
                    "Chant Pattern (chuỗi OM ngắn)": "chant_pattern",
                }
                cur_vm = active_settings.get("vocal_mode", "om_pulse")
                vm_lbl = next(
                    (k for k, v in VOCAL_MODES.items() if v == cur_vm),
                    "OM Pulse (OM dài, thưa)",
                )
                sel_vm = st.selectbox(
                    "Chế độ Vocal",
                    list(VOCAL_MODES.keys()),
                    index=list(VOCAL_MODES.keys()).index(vm_lbl),
                )
                active_settings["vocal_mode"] = VOCAL_MODES[sel_vm]

                cur_vd = float(active_settings.get("vocal_density", 0.2))
                active_settings["vocal_density"] = st.slider(
                    "Mật độ Vocal",
                    0.0,
                    1.0,
                    cur_vd,
                    0.01,
                    help="Đề xuất: 0.1–0.3 cho Deep Meditation / Sleep.",
                )

                VOCAL_BREAK = {
                    "Soft ở Breakdown": "soft",
                    "Mute ở Breakdown": "mute",
                    "Normal (không giảm)": "normal",
                }
                cur_vb = active_settings.get("vocal_breakdown_mode", "soft")
                vb_lbl = next(
                    (k for k, v in VOCAL_BREAK.items() if v == cur_vb),
                    "Soft ở Breakdown",
                )
                sel_vb = st.radio(
                    "Hành vi Vocal trong Breakdown",
                    list(VOCAL_BREAK.keys()),
                    index=list(VOCAL_BREAK.keys()).index(vb_lbl),
                )
                active_settings["vocal_breakdown_mode"] = VOCAL_BREAK[sel_vb]

                cur_vb_amt = float(
                    active_settings.get("vocal_breath_amount", 0.5)
                )
                active_settings["vocal_breath_amount"] = st.slider(
                    "Độ nhạy Vocal với nhịp thở",
                    0.0,
                    1.0,
                    cur_vb_amt,
                    0.01,
                    help="Càng cao, độ mạnh OM càng thay đổi theo pha thở.",
                )

            # ===== BASS & HANDPAN (NEW V11 HOOKS) =====
            st.subheader("Bass & Handpan (V11)")

            # Bass layer
            active_settings.setdefault("enable_bass_layer", True)
            active_settings.setdefault("v10_bass_profile", "v10_bass_warm")

            enable_bass = bool(active_settings.get("enable_bass_layer", True))
            enable_bass = st.checkbox(
                "Bật Bass Layer (ấm / sâu, giữ nền)",
                value=enable_bass,
            )
            active_settings["enable_bass_layer"] = enable_bass

            if enable_bass:
                BASS_PROFILES = {
                    "Warm Root Bass (khuyến nghị)": "v10_bass_warm",
                    "Deep Drone Bass": "v10_bass_drone",
                    "Soft Sub Pulse": "v10_bass_sub_soft",
                }
                cur_bass_prof = active_settings.get("v10_bass_profile", "v10_bass_warm")
                bass_lbl = next(
                    (k for k, v in BASS_PROFILES.items() if v == cur_bass_prof),
                    "Warm Root Bass (khuyến nghị)",
                )
                sel_bass = st.selectbox(
                    "Kiểu Bass",
                    list(BASS_PROFILES.keys()),
                    index=list(BASS_PROFILES.keys()).index(bass_lbl),
                )
                active_settings["v10_bass_profile"] = BASS_PROFILES[sel_bass]

            # Handpan layer
            active_settings.setdefault("enable_handpan_layer", False)
            active_settings.setdefault("v10_handpan_profile", "v10_handpan_soft")
            active_settings.setdefault("handpan_tuning_mode", "follow_solf")

            enable_handpan = bool(active_settings.get("enable_handpan_layer", False))
            enable_handpan = st.checkbox(
                "Bật Handpan Layer (melodic / meditative)",
                value=enable_handpan,
            )
            active_settings["enable_handpan_layer"] = enable_handpan

            if enable_handpan:
                HANDPAN_PROFILES = {
                    "Handpan Soft Flow": "v10_handpan_soft",
                    "Handpan Meditation": "v10_handpan_meditation",
                    "Handpan Virtuoso (dày hơn)": "v10_handpan_virtuoso",
                }
                cur_hp_prof = active_settings.get("v10_handpan_profile", "v10_handpan_soft")
                hp_lbl = next(
                    (k for k, v in HANDPAN_PROFILES.items() if v == cur_hp_prof),
                    "Handpan Soft Flow",
                )
                sel_hp = st.selectbox(
                    "Handpan Style",
                    list(HANDPAN_PROFILES.keys()),
                    index=list(HANDPAN_PROFILES.keys()).index(hp_lbl),
                )
                active_settings["v10_handpan_profile"] = HANDPAN_PROFILES[sel_hp]

                HP_TUNING = {
                    "Theo Key chính (Pure Key)": "pure_key",
                    "Theo Solf Root (Mode 2)": "solf_root",
                    "Dual / Overlay nhẹ": "solf_dual",
                }
                cur_hp_mode = active_settings.get("handpan_tuning_mode", "pure_key")
                if cur_hp_mode not in HP_TUNING.values():
                    cur_hp_mode = "pure_key"
                hp_mode_lbl = next(
                    (k for k, v in HP_TUNING.items() if v == cur_hp_mode),
                    "Theo Key chính (Pure Key)",
                )
                sel_hp_mode = st.radio(
                    "Tuning cho Handpan",
                    list(HP_TUNING.keys()),
                    index=list(HP_TUNING.keys()).index(hp_mode_lbl),
                    help="Chỉ là hook cho Neo Zen Core V11, hiện tại vẫn ở Safe Mode (chưa retune toàn bài).",
                )
                active_settings["handpan_tuning_mode"] = HP_TUNING[sel_hp_mode]

    # -------------------------
    # TAB 2 – TẦN SỐ & JOURNEY
    # -------------------------
    with tab2:
        # ========== FREQUENCY JOURNEY ==========
        journey_data = active_settings.get("frequency_journey", {}) or {}
        journey_enabled_flag = bool(journey_data.get("enabled", False))

        with st.expander(
            "🧭 Hành trình Tần số (Frequency Journey)", expanded=journey_enabled_flag
        ):
            current_stages = journey_data.get("stages", []) or []
            default_num = len(current_stages) if len(current_stages) >= 2 else 2

            journey_enabled = st.toggle(
                "Kích hoạt Frequency Journey (đa tần số Solfeggio)",
                value=journey_enabled_flag,
                key="journey_enabled",
            )

            if not journey_enabled:
                active_settings["frequency_journey"] = {
                    "enabled": False,
                    "stages": current_stages,
                }
                st.caption(
                    "Frequency Journey tắt: bản nhạc dùng **một tần số cố định** từ mục Solfeggio bên dưới."
                )
            else:
                st.info(
                    "Frequency Journey: bài nhạc sẽ đi qua **nhiều tần số Solfeggio** theo thứ tự. "
                    "Mỗi giai đoạn hiện tại được chia **thời lượng bằng nhau**."
                )

                num_stages = st.number_input(
                    "Số giai đoạn / tần số trong hành trình",
                    min_value=2,
                    max_value=8,
                    value=int(default_num),
                    step=1,
                    help="Ví dụ: 3 tần số 432 → 528 → 639, mỗi giai đoạn chiếm ~1/3 thời lượng.",
                )

                default_freqs = [
                    432.0,
                    528.0,
                    639.0,
                    741.0,
                    852.0,
                    963.0,
                    396.0,
                    417.0,
                ]

                # Chuẩn hoá danh sách stages
                stages = current_stages[:]
                while len(stages) < num_stages:
                    idx = len(stages)
                    fallback = (
                        default_freqs[idx]
                        if idx < len(default_freqs)
                        else 432.0
                    )
                    stages.append(
                        {
                            "label": f"Stage {idx + 1}",
                            "duration_pct": 1.0 / float(num_stages),
                            "freq": fallback,
                        }
                    )
                stages = stages[:num_stages]

                # UI cho từng stage
                for i, stage in enumerate(stages):
                    col_a, col_b = st.columns([2, 1])
                    with col_a:
                        freq_val = st.number_input(
                            f"Tần số Stage {i + 1} (Hz)",
                            min_value=0.0,
                            max_value=10000.0,
                            value=float(
                                stage.get(
                                    "freq",
                                    default_freqs[i]
                                    if i < len(default_freqs)
                                    else 432.0,
                                )
                            ),
                            key=f"journey_freq_{i}",
                        )
                    with col_b:
                        st.caption(
                            INFO_MAP["frequencies"].get(str(int(freq_val)), "")
                        )

                    stage["freq"] = float(freq_val)
                    stage["label"] = f"Stage {i + 1} ({int(freq_val)}Hz)"

                if num_stages > 0:
                    dur = round(1.0 / float(num_stages), 4)
                    for s in stages:
                        s["duration_pct"] = dur
                else:
                    dur = 0.0

                active_settings["frequency_journey"] = {
                    "enabled": True,
                    "stages": stages,
                }

                if num_stages > 0:
                    st.progress(
                        dur,
                        text=f"Mỗi giai đoạn ≈ {int(dur * 100)}% thời lượng (tổng {num_stages} giai đoạn).",
                    )

        st.divider()

        # ========= STATIC SOLFEGGIO & TUNING =========
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Solfeggio & Tuning")

            cur_solf = float(active_settings.get("solf_profile", 528.0))
            solf_freq = st.number_input(
                "Tần số Solfeggio Gốc (Hz)",
                0.0,
                10000.0,
                cur_solf,
            )
            active_settings["solf_profile"] = solf_freq

            st.caption(INFO_MAP["frequencies"].get(str(int(solf_freq)), ""))

            # 4 mode của TuningCoreV3
            TUNING_MODES = {
                "Mode 1 – Pure Key (A440, không dính Solf)": "pure_key",
                "Mode 2 – Solf Root (Key = nốt gần Solf)": "solf_root",
                "Mode 3 – Dual Drone (Key theo Solf + Drone phụ = Solf)": "solf_dual",
                "Mode 4 – Key + Solf Drone Overlay": "key_plus_solf_drone",
            }
            cur_drone = active_settings.get("drone_mode", "pure_key")
            if cur_drone not in TUNING_MODES.values():
                cur_drone = "pure_key"

            d_idx = list(TUNING_MODES.values()).index(cur_drone)
            sel_drone = st.radio(
                "Chế độ Tuning:",
                list(TUNING_MODES.keys()),
                index=d_idx,
            )
            active_settings["drone_mode"] = TUNING_MODES[sel_drone]

            if active_settings["drone_mode"] != "pure_key":
                st.warning(
                    "Các mode 2–4 sẽ gắn key và Drone với tần số Solfeggio. "
                    "Hãy nghe thử và chọn mode phù hợp với bản nhạc."
                )

        # ========= BINAURAL & BRAINWAVE JOURNEY =========
        with col2:
            st.subheader("Binaural Beats & Sóng Não")

            bw_enable = st.toggle(
                "Bật Binaural (Sóng não)",
                value=bool(active_settings.get("brainwave_enable", False)),
            )
            active_settings["brainwave_enable"] = bw_enable

            bands = ["delta", "theta", "alpha", "beta", "gamma", "schumann"]
            cur_band = active_settings.get("brainwave_band", "alpha")
            try:
                b_idx = bands.index(cur_band)
            except ValueError:
                b_idx = 2

            band_sel = st.selectbox(
                "Band mặc định (khi không dùng Brainwave Journey)",
                bands,
                index=b_idx,
                disabled=not bw_enable,
            )
            active_settings["brainwave_band"] = band_sel

            # Optional: custom beat_hz global (dùng khi không khai báo journey)
            global_beat_val = float(
                active_settings.get("binaural_beat_hz", 0.0) or 0.0
            )
            custom_hz = st.number_input(
                "Custom Beat Hz (tùy chọn, override band)",
                min_value=0.0,
                max_value=100.0,
                value=global_beat_val,
                step=0.1,
                disabled=not bw_enable,
                help="Để 0.0 nếu muốn dùng giá trị mặc định theo band (delta/theta/alpha...).",
            )
            active_settings["binaural_beat_hz"] = custom_hz

            # ------- Brainwave Journey (phần 2) -------
            bw_journey = active_settings.get("brainwave_journey", {}) or {}
            bw_j_enabled_flag = bool(bw_journey.get("enabled", False))
            bw_j_lock = bool(bw_journey.get("lock_to_frequency", False))
            bw_stages = bw_journey.get("stages", []) or []

            with st.expander(
                "📡 Brainwave Journey (Hành trình Sóng não)",
                expanded=bw_j_enabled_flag and bw_enable,
            ):
                if not bw_enable:
                    st.caption(
                        "Bạn cần bật **Binaural (Sóng não)** phía trên để hành trình sóng não có hiệu lực."
                    )

                bw_j_enabled = st.toggle(
                    "Kích hoạt Brainwave Journey",
                    value=bw_j_enabled_flag and bw_enable,
                    key="bw_journey_enabled",
                    disabled=not bw_enable,
                )

                bw_j_lock = st.checkbox(
                    "Cố gắng khóa với Frequency Journey (stage 1↔1, 2↔2...)",
                    value=bw_j_lock,
                    disabled=not bw_enable or not bw_j_enabled,
                    help=(
                        "Nếu bật: Neo Zen Core sẽ cố gắng map stage sóng não với stage tần số "
                        "theo index (Stage 1 ↔ Stage 1...). Nếu tắt: "
                        "Brainwave Journey chạy độc lập theo % thời lượng."
                    ),
                )

                if not bw_j_enabled or not bw_enable:
                    active_settings["brainwave_journey"] = {
                        "enabled": False,
                        "lock_to_frequency": bw_j_lock,
                        "stages": bw_stages,
                    }
                else:
                    st.info(
                        "Brainwave Journey: thay đổi **beat Hz** theo từng giai đoạn. "
                        "Có thể dùng cùng hoặc khác với Frequency Journey."
                    )

                    default_bw_num = len(bw_stages) if len(bw_stages) >= 2 else 2
                    num_bw_stages = st.number_input(
                        "Số giai đoạn sóng não",
                        min_value=2,
                        max_value=8,
                        value=int(default_bw_num),
                        step=1,
                    )

                    # Chuẩn hóa list stage
                    bw_stages_norm = bw_stages[:]
                    while len(bw_stages_norm) < num_bw_stages:
                        idx = len(bw_stages_norm)
                        bw_stages_norm.append(
                            {
                                "label": f"Brainwave {idx + 1}",
                                "duration_pct": 1.0 / float(num_bw_stages),
                                "band": band_sel,
                                "beat_hz": 0.0,
                            }
                        )
                    bw_stages_norm = bw_stages_norm[:num_bw_stages]

                    for i, stg in enumerate(bw_stages_norm):
                        c1, c2, c3 = st.columns([1.4, 1.1, 1.0])
                        with c1:
                            band_i = st.selectbox(
                                f"Stage {i + 1} – Band",
                                bands,
                                index=(
                                    bands.index(stg.get("band", band_sel))
                                    if stg.get("band", band_sel) in bands
                                    else bands.index(band_sel)
                                ),
                                key=f"bw_band_{i}",
                            )
                        with c2:
                            beat_i = st.number_input(
                                f"Beat Hz {i + 1}",
                                min_value=0.0,
                                max_value=100.0,
                                value=float(stg.get("beat_hz", 0.0) or 0.0),
                                step=0.1,
                                key=f"bw_beat_{i}",
                            )
                        with c3:
                            st.caption(
                                f"{band_i} – "
                                + (
                                    "custom Hz"
                                    if beat_i > 0
                                    else "dùng mặc định band"
                                )
                            )

                        stg["band"] = band_i
                        stg["beat_hz"] = float(beat_i)
                        stg["label"] = f"Brainwave Stage {i + 1} ({band_i})"

                    # chia đều thời lượng
                    if num_bw_stages > 0:
                        dur_bw = round(1.0 / float(num_bw_stages), 4)
                        for s in bw_stages_norm:
                            s["duration_pct"] = dur_bw
                    else:
                        dur_bw = 0.0

                    active_settings["brainwave_journey"] = {
                        "enabled": True,
                        "lock_to_frequency": bw_j_lock,
                        "stages": bw_stages_norm,
                    }

                    if num_bw_stages > 0:
                        st.progress(
                            dur_bw,
                            text=(
                                f"Mỗi giai đoạn sóng não ≈ {int(dur_bw * 100)}% thời lượng "
                                f"(tổng {num_bw_stages} giai đoạn)."
                            ),
                        )

        st.caption(
            "Tab này điều khiển **tần số vật lý** của bản nhạc (Solfeggio 432/528/639 Hz...) "
            "và **sóng não Binaural**. Frequency Journey chạy trên tần số Solfeggio; "
            "Brainwave Journey chạy trên beat Hz (delta/theta/alpha...). "
            "Bạn có thể dùng độc lập hoặc kết hợp."
        )

    # -------------------------
    # TAB 3 – CẤU TRÚC & HƠI THỞ
    # -------------------------
    with tab3:
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Tempo & Duration")
            cur_bpm = int(active_settings.get("base_tempo", 60))
            bpm = st.slider("BPM", 30, 120, cur_bpm)
            active_settings["base_tempo"] = bpm

            cur_dur = int(active_settings.get("total_duration_seconds", 600) / 60)
            dur_min = st.slider("Thời lượng (Phút)", 1, 120, cur_dur)
            total_seconds = dur_min * 60
            active_settings["total_duration_seconds"] = total_seconds

            st.subheader("🫁 Hơi Thở")

            BREATH_MODES = {
                "Auto": "auto",
                "Deep": "deep",
                "Flow": "flow",
            }
            cur_b = active_settings.get("breath_mode", "auto")
            b_lbl = next(
                (k for k, v in BREATH_MODES.items() if v == cur_b),
                "Auto",
            )
            sel_b = st.selectbox(
                "Chế độ",
                list(BREATH_MODES.keys()),
                index=list(BREATH_MODES.keys()).index(b_lbl),
            )
            active_settings["breath_mode"] = BREATH_MODES[sel_b]

            beats_per_bar = 4
            default_cycle = float(
                active_settings.get(
                    "breath_cycle_bars",
                    2.0
                    if active_settings["breath_mode"] in ("auto", "deep")
                    else 1.0,
                )
            )

            breath_cycle_bars = st.number_input(
                "Số bar cho 1 chu kỳ thở",
                min_value=0.5,
                max_value=32.0,
                value=max(0.5, float(default_cycle)),
                step=0.5,
                help="Ví dụ: 2 bar ≈ 8 giây ở 60 BPM với nhịp 4/4.",
            )
            active_settings["breath_cycle_bars"] = float(breath_cycle_bars)

            seconds_per_beat = 60.0 / bpm if bpm > 0 else 0.0
            seconds_per_bar = seconds_per_beat * beats_per_bar
            breath_duration_seconds = (
                breath_cycle_bars * seconds_per_bar if breath_cycle_bars > 0 else 0.0
            )

            st.caption(
                f"≈ **{breath_duration_seconds:.1f} giây** cho mỗi chu kỳ thở "
                f"(ước tính với nhịp 4/4, {breath_cycle_bars:g} bar / hơi)."
            )

        with col2:
            st.subheader("Khác")

            active_settings["master_intensity"] = st.slider(
                "Cường độ",
                0.0,
                1.0,
                float(active_settings.get("master_intensity", 0.5)),
                help=(
                    "Điều khiển mức 'năng lượng' tổng thể của bản nhạc: "
                    "càng cao thì melody, pulse, chime... sẽ hoạt động dày hơn, mạnh hơn. "
                    "Đây không phải volume master."
                ),
            )

            keys = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
            cur_key = active_settings.get("key", "C")
            if cur_key not in keys:
                cur_key = "C"

            active_settings["key"] = st.selectbox(
                "Key (Tâm âm của bài)",
                keys,
                index=keys.index(cur_key),
                help=(
                    "Key = nốt gốc mà cả bài xoay quanh. "
                    "Key thấp (C, D) cho cảm giác ấm, gần đất; "
                    "Key cao (G, A, B) cho cảm giác sáng, bay."
                ),
            )

            scales = ["major", "minor", "dorian", "mixolydian", "lydian", "phrygian"]
            cur_scale = active_settings.get("scale", "major")
            if cur_scale not in scales:
                cur_scale = "major"

            active_settings["scale"] = st.selectbox(
                "Scale (Thang âm / Mode)",
                scales,
                index=scales.index(cur_scale),
                help=(
                    "Scale quyết định tính chất cảm xúc:\n"
                    "- major: sáng, ấm, an toàn (healing nhẹ, gratitude).\n"
                    "- minor: trầm, nội tâm (thiền tối, introspective).\n"
                    "- dorian: màu thiền/world, cổ nhẹ.\n"
                    "- mixolydian: vui nhưng chill, trôi nhẹ.\n"
                    "- lydian: sáng, mơ mộng, hơi 'cosmic'.\n"
                    "- phrygian: huyền bí, nghi lễ, cổ xưa."
                ),
            )

            st.caption(
                "Key & Scale quyết định cấu trúc hòa âm và cảm xúc. "
                "Các tùy chọn Solfeggio & Journey ở Tab 2 chỉ đổi tần số vật lý (432, 528 Hz...), "
                "không đổi logic hợp âm."
            )

            st.divider()
            custom_prog = st.text_area(
                "Kịch bản Hợp âm",
                value=active_settings.get("custom_chord_progression") or "",
                help=(
                    "Ví dụ: Cmaj7 | Fmaj7 | G6 | Am7...\n"
                    "Có thể dùng thẻ <Intro>, <Verse>, <Chorus> để gợi ý cấu trúc."
                ),
            )
            active_settings["custom_chord_progression"] = (
                custom_prog if custom_prog.strip() else None
            )

            if custom_prog.strip():
                active_settings["auto_duration_from_chords"] = st.checkbox(
                    "Tự tính thời lượng từ hợp âm & nhịp thở",
                    value=active_settings.get("auto_duration_from_chords", True),
                )

            # ========= DEBUG FLAGS (PHASE 4) =========
            st.subheader("Debug (Advanced)")

            active_settings["debug_print_segments"] = st.checkbox(
                "In debug Segments (Zen Arc / Chord / Energy) trong console",
                value=bool(active_settings.get("debug_print_segments", False)),
                help=(
                    "Nếu bật: Neo Zen Core/Engines có thể in danh sách Segment "
                    "(thời gian, chord, energy_bias...) để bạn kiểm tra dòng chảy."
                ),
            )
            active_settings["debug_print_notes"] = st.checkbox(
                "In debug Notes (nếu Engine hỗ trợ)",
                value=bool(active_settings.get("debug_print_notes", False)),
                help=(
                    "Nếu bật và các Engine có hỗ trợ, sẽ in một phần nốt sinh ra "
                    "(pitch, time, layer) để debug chi tiết hơn."
                ),
            )

    # Lưu lại options sau khi chỉnh UI
    save_yaml_file(DEFAULT_OPTIONS_FILE, active_settings)

    # =========================
    # NÚT CHẠY
    # =========================
    if run_clicked:
        run_generation(active_settings, selected_template)

if __name__ == "__main__":
    main()
