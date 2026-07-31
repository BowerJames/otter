from __future__ import annotations

import asyncio
import contextlib
from abc import ABC, abstractmethod
from collections.abc import Generator
from types import TracebackType
from typing import Protocol, Self, final

_DEFAULT_SHUTDOWN_TIMEOUT: float = 5.0


class TaskRunner(Protocol):
    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None: ...

    def __await__(self) -> Generator[None, None, None]: ...


class TaskRunnerMixIn(ABC):
    _task: asyncio.Task[None] | None = None
    _shutdown_timeout: float = _DEFAULT_SHUTDOWN_TIMEOUT

    @final
    async def __aenter__(self) -> Self:
        self._task = asyncio.create_task(self._run_tasks())
        return self

    @final
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._task is None:
            return
        try:
            async with asyncio.timeout(self._shutdown_timeout):
                await self._task
        except TimeoutError:
            # Best-effort forced reap: cancel the lifecycle task and drain it,
            # swallowing the cancellation so teardown always exits cleanly.
            self._task.cancel()
            with contextlib.suppress(BaseException):
                await self._task

    @final
    async def _run_tasks(self) -> None:
        async with asyncio.TaskGroup() as tg:
            self._register_tasks(tg)

    @final
    def __await__(self) -> Generator[None, None, None]:
        assert self._task is not None
        return self._task.__await__()

    @abstractmethod
    def _register_tasks(self, tg: asyncio.TaskGroup) -> None: ...


__all__ = ["TaskRunner", "TaskRunnerMixIn"]
