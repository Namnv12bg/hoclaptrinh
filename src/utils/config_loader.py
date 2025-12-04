from __future__ import annotations


class InstrumentProfile:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
