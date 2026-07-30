from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Protocol, Self


class TaskRunner(Protocol):
    tasks: asyncio.TaskGroup

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None: ...


__all__ = ["TaskRunner"]
