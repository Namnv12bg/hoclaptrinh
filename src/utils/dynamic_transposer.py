# Tệp: src/utils/dynamic_transposer.py
# (FINAL V10.10.0) - DYNAMIC TRANSPOSER (SEMITONE JOURNEY, TRANSPARENT BY DEFAULT)
#
# Vai trò:
# - Wrapper cho MidiWriter/MidiTrack, cho phép dịch nốt theo Semitone tuỳ theo Stage của FrequencyJourney.
# - Trong kiến trúc Neo Zen Core hiện tại (PHASE 2):
#     + Zen Core truyền journey=None, default_shift=0
#     + => DynamicTransposingWriter hoạt động như "writer trong suốt" (không transpose).
#
# Chuẩn bị cho tương lai:
# - Hỗ trợ forwarding add_pitch_bend_cents để Phase 3 có thể dùng pitch bend theo cents
#   (global retune) mà không phải sửa lại các Engine.

from typing import Optional

from src.utils.midi_writer import MidiTrack, MidiWriter
from src.core.frequency_journey import FrequencyJourney, FrequencyStage


class DynamicTransposingTrack:
    """
    Lớp bọc (Wrapper) cho MidiTrack.

    Ý tưởng gốc:
    - Lén thay đổi cao độ (Pitch) của nốt nhạc trước khi ghi xuống file thật,
      dựa trên thời điểm (Tick) mà nốt nhạc đó xuất hiện.
    - Dùng cho các kịch bản Journey mà từng Stage cần transpose ±semitones.

    Trong Neo Zen Core (PHASE 2):
    - Journey thường = None, default_shift = 0 -> lớp này không dùng.
    - Nếu bạn gán Journey thủ công cho một số case đặc biệt, logic cũ vẫn hoạt động.
    """

    def __init__(
        self,
        original_track: MidiTrack,
        journey: Optional[FrequencyJourney] = None,
        default_shift: int = 0,
    ):
        self.track = original_track
        # Chỉ giữ journey nếu nó thực sự bật & có stage
        self.journey = (
            journey
            if (journey and getattr(journey, "enabled", False) and journey.stages)
            else None
        )
        self.default_shift = int(default_shift)

    def _get_shift_for_tick(self, tick: int) -> int:
        """
        Tính số bán cung cần dịch tại một tick cụ thể.
        - Nếu không có Journey: dùng default_shift (Static mode).
        - Nếu có Journey: hỏi Stage tương ứng.
        """
        # Nếu không có hành trình, dùng mức dịch cố định (Static Mode)
        if self.journey is None:
            return self.default_shift

        # Nếu có hành trình, hỏi xem Tick này thuộc Stage nào?
        stage: Optional[FrequencyStage] = self.journey.get_stage_at_tick(tick)
        if stage is None:
            return self.default_shift

        # Trả về số bán cung cần dịch của Stage đó
        return int(getattr(stage, "shift_semitones", 0))

    # =========================
    # NOTE / CC / PITCHBEND
    # =========================

    def add_note(self, pitch: int, velocity: int, start_tick: int, duration_ticks: int):
        # 1. Tính toán mức dịch
        shift = self._get_shift_for_tick(start_tick)

        # 2. Áp dụng dịch
        new_pitch = int(pitch) + shift

        # 3. Kẹp giá trị an toàn (MIDI chỉ cho phép 0-127)
        if new_pitch < 0:
            new_pitch = 0
        elif new_pitch > 127:
            new_pitch = 127

        # 4. Ghi xuống track thật
        self.track.add_note(new_pitch, velocity, start_tick, duration_ticks)

    # Các hàm khác chuyển tiếp nguyên vẹn (Forwarding)
    def add_cc(self, *args, **kwargs):
        return self.track.add_cc(*args, **kwargs)

    def add_pitch_bend(self, *args, **kwargs):
        return self.track.add_pitch_bend(*args, **kwargs)

    def add_pitch_bend_cents(self, *args, **kwargs):
        """
        Forward helper mới từ MidiTrack:
        - Cho phép gửi pitch bend theo cents (dùng ở Phase 3 nếu cần).
        """
        # Nếu MidiTrack chưa có method này (phiên bản cũ), sẽ raise AttributeError.
        # Điều này là ok trong dev; trong production ta đang dùng bản MidiTrack mới.
        return self.track.add_pitch_bend_cents(*args, **kwargs)

    def set_name(self, *args, **kwargs):
        return self.track.set_name(*args, **kwargs)

    def set_program(self, *args, **kwargs):
        return self.track.set_program(*args, **kwargs)


class DynamicTransposingWriter:
    """
    Lớp bọc cho MidiWriter.
    Thay vì trả về Track thường, nó trả về DynamicTransposingTrack
    để tự động xử lý transpose theo Journey / default_shift.

    Trong Neo Zen Core (PHASE 2):
    - Zen Core truyền journey=None, default_shift=0
    - => get_track(...) trả về MidiTrack gốc (không transpose).
    """

    def __init__(
        self,
        writer: MidiWriter,
        journey: Optional[FrequencyJourney] = None,
        default_shift: int = 0,
    ):
        self.writer = writer
        self.journey = (
            journey
            if (journey and getattr(journey, "enabled", False) and journey.stages)
            else None
        )
        self.default_shift = int(default_shift)

    def get_track(self, channel: int):
        """
        Lấy track cho 1 channel:
        - Nếu không cần dịch: trả về MidiTrack gốc cho nhanh.
        - Nếu có dịch (Journey hoặc default_shift): trả về DynamicTransposingTrack.
        """
        real_track = self.writer.get_track(channel)

        # Nếu không cần dịch gì cả, trả về track thật cho nhanh
        if self.journey is None and self.default_shift == 0:
            return real_track

        # Nếu cần dịch, trả về bản bọc
        return DynamicTransposingTrack(
            real_track,
            journey=self.journey,
            default_shift=self.default_shift,
        )

    @property
    def ppq(self) -> int:
        return self.writer.ppq
