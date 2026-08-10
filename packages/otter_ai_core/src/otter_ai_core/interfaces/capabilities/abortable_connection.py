from __future__ import annotations

from typing import Protocol

from .connection import Connection


class AbortableConnection[TRead, TWrite](Connection[TRead, TWrite], Protocol):
    def abort(self) -> None: ...


__all__ = [
    "AbortableConnection",
]
