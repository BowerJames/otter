from __future__ import annotations

from typing import Protocol


class AbortObservable(Protocol):
    async def wait_for_abort(self) -> None: ...


__all__ = [
    "AbortObservable",
]
