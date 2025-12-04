# Tệp: src/core/music_theory.py
# (FINAL V9.9.80) - SMART VOICE LEADING & THEORY UPGRADE
# Features:
# - Improved Chord Parsing (m7b5, 9, sus, dim)
# - Smart Voice Leading (Minimal Motion, Gravity Center)
# - Pedal Bass Logic (Grounding)
# - Full Backward Compatibility API

import math
import re
import random
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

# --- CONSTANTS ---
NOTE_TO_PC = {
    'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3,
    'E': 4, 'F': 5, 'F#': 6, 'Gb': 6, 'G': 7, 'G#': 8, 'Ab': 8,
    'A': 9, 'A#': 10, 'Bb': 10, 'B': 11, 'Cb': 11
}
# Reverse lookup map
PC_TO_NOTE = {v: k for k, v in NOTE_TO_PC.items() if len(k) < 2} 
PC_TO_NOTE.update({1: 'C#', 3: 'D#', 6: 'F#', 8: 'G#', 10: 'A#'})

# --- CORE FUNCTIONS (API Preserved) ---
def note_number(pc: int, octave: int) -> int:
    """Trả về MIDI note number từ Pitch Class và Octave."""
    return int(pc + 12 * (octave + 1))

def midi_to_hz(note: int, tuning: float = 440.0) -> float:
    """Chuyển đổi MIDI note sang tần số Hz."""
    return tuning * (2 ** ((note - 69) / 12))

# Alias cho tương thích ngược (nếu có module cũ dùng _midi_to_hz)
def _midi_to_hz(note: int, tuning: float = 440.0) -> float:
    return midi_to_hz(note, tuning)

# --- CLASSES ---

class Scale:
    def __init__(self, root_note: str, scale_type: str, family: str = "diatonic"):
        self.root_note = root_note
        self.scale_type = scale_type
        self.root_pc = NOTE_TO_PC.get(root_note, 0)
        self.pcs = self._build_scale()

    def _build_scale(self):
        # Default Diatonic intervals
        intervals = [0, 2, 4, 5, 7, 9, 11] # Major/Ionian
        
        st = self.scale_type.lower()
        if 'minor' in st or 'aeolian' in st: 
            intervals = [0, 2, 3, 5, 7, 8, 10]
        elif 'dorian' in st: 
            intervals = [0, 2, 3, 5, 7, 9, 10]
        elif 'mixolydian' in st: 
            intervals = [0, 2, 4, 5, 7, 9, 10]
        elif 'lydian' in st: 
            intervals = [0, 2, 4, 6, 7, 9, 11]
        elif 'phrygian' in st: 
            intervals = [0, 1, 3, 5, 7, 8, 10]
        elif 'locrian' in st:
            intervals = [0, 1, 3, 5, 6, 8, 10]
            
        return [(self.root_pc + i) % 12 for i in intervals]

    def contains_pc(self, pc):
        return pc in self.pcs
    
    def get_pitch_classes(self):
        return self.pcs

class Chord:
    def __init__(self, name: str, key: str = "C", scale: str = "major"):
        self.name = name
        self.root_pc = 0
        self.pcs = []
        self._parse()

    def _parse(self):
        """
        [UPGRADE] Enhanced Chord Parsing logic.
        Hỗ trợ: Maj7, m7, 7, m7b5, dim, aug, sus2, sus4, add9.
        """
        # 1. Tách Root Note
        root_str = ""
        # Tìm nốt gốc dài nhất có thể (ví dụ C# > C)
        for note_name in sorted(NOTE_TO_PC.keys(), key=len, reverse=True):
            if self.name.startswith(note_name):
                root_str = note_name
                break
        
        if not root_str:
            # Fallback nếu tên không chuẩn
            root_str = self.name[:1] if self.name else "C"

        self.root_pc = NOTE_TO_PC.get(root_str, 0)
        
        # 2. Xác định Intervals dựa trên Suffix
        suffix = self.name[len(root_str):]
        
        # Mặc định là Major Triad [0, 4, 7]
        intervals = [0, 4, 7]
        
        # Minor Logic
        if 'm' in suffix and 'maj' not in suffix: # Cẩn thận với 'maj'
            intervals = [0, 3, 7] # Minor triad
            
        # Diminished
        if 'dim' in suffix or '°' in suffix:
            intervals = [0, 3, 6]
            if '7' in suffix: intervals.append(9) # Dim7 (fully diminished)
            
        # Augmented
        if 'aug' in suffix or '+' in suffix:
            intervals = [0, 4, 8]
            
        # Suspended
        if 'sus2' in suffix:
            intervals = [0, 2, 7]
        elif 'sus4' in suffix:
            intervals = [0, 5, 7]
            
        # 7th Logic (Thêm vào base triad)
        if 'maj7' in suffix or 'M7' in suffix:
            if 11 not in intervals: intervals.append(11)
        elif '7' in suffix: # Dominant 7 or Minor 7
            if 'dim' not in suffix: # Tránh dim7 đã xử lý
                intervals.append(10)
                
        # m7b5 (Half-diminished) - Special Case
        if 'm7b5' in suffix or 'ø' in suffix:
            intervals = [0, 3, 6, 10]
            
        # Extensions (9)
        if '9' in suffix: # add9 or maj9 or 9
            # Thường thêm bậc 2 (tức 14 -> 2 mod 12)
            if 2 not in intervals: intervals.append(2)
            # Nếu chỉ ghi C9 -> Dominant 9 (tức có cả b7)
            if 'maj' not in suffix and 'add' not in suffix and 10 not in intervals:
                intervals.append(10)

        # Build Pitch Classes
        self.pcs = sorted(list(set([(self.root_pc + i) % 12 for i in intervals])))

    def get_pitch_classes(self):
        return self.pcs

class VoiceLeading:
    """
    (UPGRADE) Smart Voice Leading module.
    Mục tiêu: Minimal Motion + Grounding.
    """
    def __init__(self):
        self.center_octave = 3 # Vùng đẹp cho Pad (C3-B3)

    def find_next_voicing(self, target_chord: 'Chord', previous_voicing: List[int]) -> List[int]:
        """
        Tìm voicing mới cho target_chord sao cho di chuyển mượt nhất từ previous_voicing.
        """
        target_pcs = target_chord.get_pitch_classes()
        if not target_pcs: return previous_voicing or []

        # Case 1: Chưa có voicing trước đó (Khởi đầu)
        if not previous_voicing:
            voicing = []
            # Root note luôn ở dưới (Octave thấp hơn center 1 chút để dày)
            voicing.append(note_number(target_pcs[0], self.center_octave - 1))
            # Các nốt còn lại rải quanh center octave
            for pc in target_pcs[1:]:
                voicing.append(note_number(pc, self.center_octave))
            return sorted(list(set(voicing)))

        # Case 2: Smart Leading (Minimal Motion)
        new_voicing = []
        
        # Tính "Trọng tâm" (Gravity Center) của voicing cũ
        # Đây là điểm trung bình cao độ, giúp voicing mới không bị trôi đi quá xa
        avg_pitch = sum(previous_voicing) / len(previous_voicing)
        
        for pc in target_pcs:
            # Tìm tất cả các vị trí có thể của nốt này trong dải octave 2-5
            candidates = [
                note_number(pc, 2), 
                note_number(pc, 3), 
                note_number(pc, 4), 
                note_number(pc, 5)
            ]
            
            # Chọn nốt gần với trọng tâm cũ nhất
            best_note = min(candidates, key=lambda x: abs(x - avg_pitch))
            new_voicing.append(best_note)
            
        # [SOUL LOGIC] Pedal Bass / Grounding
        # Luôn đảm bảo nốt gốc (Root) nằm ở dưới đáy để giữ vững nền móng.
        # Nhưng không được để Bass nhảy quá xa so với voicing (tránh gap lớn bất thường).
        
        root_pc = target_chord.root_pc
        # Tìm nốt root thấp nhất trong voicing vừa tạo
        current_roots = [n for n in new_voicing if n % 12 == root_pc]
        
        if not current_roots:
            # Nếu voicing tự động không có root (hiếm, nhưng có thể do invert), thêm Root vào đáy
            # Ưu tiên Root ở Octave 2 hoặc 3 tùy vào độ cao trung bình
            ideal_root = note_number(root_pc, 2)
            if abs(ideal_root - avg_pitch) > 18: # Nếu xa quá thì dùng Octave 3
                ideal_root = note_number(root_pc, 3)
            new_voicing.append(ideal_root)
        else:
            # Nếu có root, đảm bảo root thấp nhất không bị "bay" quá cao
            min_root = min(current_roots)
            # Nếu root thấp nhất lại cao hơn C4 (60), ép xuống Octave 2 hoặc 3
            if min_root > 60:
                new_voicing.remove(min_root)
                new_voicing.append(note_number(root_pc, 3)) # Reset về nền

        # Sắp xếp và lọc trùng
        return sorted(list(set(new_voicing)))

# --- UTILS (Helper functions for Prog Parsing & Key Detection) ---

def parse_progression_string(prog_str: str) -> List[Tuple[str, str]]:
    """
    Parse chuỗi hợp âm từ UI/Config thành list các tuple (ChordName, Section).
    Hỗ trợ format: 
    <Intro> C*4 Am*4
    <Verse> Fmaj7*2 G7*2
    """
    result = []
    current_section = "Verse"
    
    # Chuẩn hóa chuỗi: thay | bằng space, tách dòng
    prog_str = prog_str.replace("|", " ")
    lines = prog_str.replace(",", " ").split("\n")
    
    for line in lines:
        tokens = line.strip().split()
        for token in tokens:
            if token.startswith("<") and token.endswith(">"):
                current_section = token[1:-1] # Lấy tên section
                continue
            
            chord = token
            count = 1
            if "*" in token:
                parts = token.split("*")
                chord = parts[0]
                try: count = int(parts[1])
                except: count = 1
            
            for _ in range(count):
                result.append((chord, current_section))
                
    return result

def detect_key_from_chords(chords: List['Chord']) -> Tuple[str, str]:
    """
    Đoán Key và Mode từ danh sách hợp âm.
    Logic đơn giản dựa trên tần suất xuất hiện Root Note và tính chất Major/Minor.
    """
    if not chords:
        return "C", "major"

    counts = [0] * 12
    minor_count = 0
    major_count = 0

    for c in chords:
        if not c: continue
        counts[c.root_pc] += 1
        # Heuristic: tên có 'm' nhưng không có 'maj' -> minor
        if 'm' in c.name and 'maj' not in c.name:
            minor_count += 1
        else:
            major_count += 1

    root_pc = max(range(12), key=lambda i: counts[i])
    mode = "aeolian" if minor_count > major_count else "major"
    root_name = PC_TO_NOTE.get(root_pc, "C")
    
    return root_name, mode
