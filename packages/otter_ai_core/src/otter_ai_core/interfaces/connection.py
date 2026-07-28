from __future__ import annotations

from typing import Protocol

from .stream import Stream
from .writer import Writer


class Connection[TRead, TWrite](Stream[TRead], Writer[TWrite], Protocol):
    pass


__all__ = [
    "Connection",
]
