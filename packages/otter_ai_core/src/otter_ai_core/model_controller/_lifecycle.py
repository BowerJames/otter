"""Internal async teardown helper for the model controller.

The controller's background drain task must be awaited under a deadline and
force-cancelled if it overruns. The generic bus owns its corresponding helper
within :mod:`otter_ai_core.bus`.
"""

from __future__ import annotations

import asyncio
import contextlib


async def await_or_cancel(task: asyncio.Task[None], timeout: float | None) -> None:
    """Await ``task`` for up to ``timeout`` seconds; force-cancel if it overruns.

    ``timeout`` of ``None`` waits indefinitely (drain-or-hang). A timed-out or
    otherwise-interrupted await still cancels the task (so its ``finally`` blocks
    run) so no owned task is left pending. No-op if ``task`` is already done.
    """
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
