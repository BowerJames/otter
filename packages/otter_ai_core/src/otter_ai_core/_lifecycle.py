from __future__ import annotations

import asyncio
import contextlib


async def await_or_cancel(task: asyncio.Task[None], timeout: float | None) -> None:
    if task.done():
        return
    try:
        await asyncio.wait_for(task, timeout)
    except TimeoutError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    except BaseException:
        # The await itself was cancelled: cancel the task too, then re-raise.
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        raise
