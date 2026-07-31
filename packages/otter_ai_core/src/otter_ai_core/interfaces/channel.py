from __future__ import annotations

from typing import Protocol

from .connection import Connection


class Channel[TEvent](Connection[TEvent, TEvent], Protocol):
    pass


__all__ = [
    "Channel",
]
