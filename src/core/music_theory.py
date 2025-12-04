"""Basic music theory utilities used across the project.

This module keeps the pitch-class mappings lightweight so that the
StructureBuilder can normalise user input even when only a subset of the
full engine is present. Only essentials are implemented.
"""
from typing import Dict, List, Tuple, Union

# Pitch-class mappings. We keep both sharp and flat spellings for safety.
NOTE_TO_PC: Dict[str, int] = {
    "C": 0,
    "C#": 1,
    "Db": 1,
    "D": 2,
    "D#": 3,
    "Eb": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "Gb": 6,
    "G": 7,
    "G#": 8,
    "Ab": 8,
    "A": 9,
    "A#": 10,
    "Bb": 10,
    "B": 11,
}

# Use a flat-leaning mapping so we have a deterministic note name for each PC.
PC_TO_NOTE: Dict[int, str] = {
    0: "C",
    1: "C#",
    2: "D",
    3: "Eb",
    4: "E",
    5: "F",
    6: "F#",
    7: "G",
    8: "Ab",
    9: "A",
    10: "Bb",
    11: "B",
}


def parse_progression_string(prog: str) -> List[Union[str, Tuple[str, str]]]:
    """Very small helper to parse chord progressions.

    The real implementation supports roman numerals and mixed sections; here we
    keep it intentionally tiny but compatible with StructureBuilder:

    - Split on whitespace, commas or bars.
    - Tokens can optionally carry a section name separated by ':'; when present
      we return a tuple ``(chord, section)``.
    - Otherwise the chord symbol itself is returned.
    """

    if not isinstance(prog, str):
        raise ValueError("Progression must be a string")

    cleaned = prog.replace("|", " ").replace(",", " ")
    tokens = [tok.strip() for tok in cleaned.split() if tok.strip()]

    progression: List[Union[str, Tuple[str, str]]] = []
    for tok in tokens:
        if ":" in tok:
            chord, section = tok.split(":", 1)
            progression.append((chord.strip(), section.strip() or "Verse"))
        else:
            progression.append(tok)
    return progression
