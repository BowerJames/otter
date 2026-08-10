from __future__ import annotations

from collections.abc import AsyncIterable
from typing import Protocol


class Stream[TEvent](AsyncIterable[TEvent], Protocol):
    pass


__all__ = [
    "Stream",
]
