from __future__ import annotations

from typing import Protocol


class BinaryStateMachine(Protocol):
    def is_idle(self) -> bool: ...

    async def wait_for_idle(self) -> None: ...

    def abort(self) -> None: ...


__all__ = [
    "BinaryStateMachine",
]
