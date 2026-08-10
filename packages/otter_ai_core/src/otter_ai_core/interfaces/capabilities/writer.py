from __future__ import annotations

from typing import Protocol


class Writer[TEvent](Protocol):
    def push(self, event: TEvent) -> None: ...

    def end(self) -> None: ...


__all__ = [
    "Writer",
]
