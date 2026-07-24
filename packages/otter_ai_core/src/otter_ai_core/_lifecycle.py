"""Shared async teardown helper: ``await_or_cancel``.

Several active runtimes (the descriptor-keyed :class:`~otter_ai_core.bus.Bus`,
the :class:`~otter_ai_core.model_controller.ModelController`, and the
:class:`~otter_ai_core.faux.FauxModelProducer`) each own a background task that
must be awaited under a deadline and force-cancelled if it overruns. This is
the single implementation they all share, so the teardown contract is defined
once rather than copy-pasted per consumer.

It is **package-internal**: it is deliberately not re-exported in any public
``__all__``. The back-compat re-export in
:mod:`otter_ai_core.model_controller._lifecycle` keeps that existing import path
working.
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
