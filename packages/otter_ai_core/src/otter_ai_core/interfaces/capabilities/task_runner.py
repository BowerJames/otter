from __future__ import annotations

from collections.abc import Generator
from types import TracebackType
from typing import Protocol, Self


class TaskRunner(Protocol):
    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None: ...

    def __await__(self) -> Generator[None, None, None]: ...

    def end(self) -> None: ...


__all__ = ["TaskRunner"]
