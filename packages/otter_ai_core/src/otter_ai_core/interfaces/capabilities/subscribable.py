from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

type UnsubscriberFn = Callable[[], None]


class Subscribable(Protocol):
    def on(self, type: str, handler: Callable[..., object]) -> UnsubscriberFn: ...


__all__ = [
    "Subscribable",
    "UnsubscriberFn",
]
