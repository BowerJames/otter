from __future__ import annotations

from typing import Protocol

from .stream import Stream


class AbortableStream[TEvent](Stream[TEvent], Protocol):
    def abort(self) -> None: ...


__all__ = [
    "AbortableStream",
]
