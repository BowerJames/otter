import asyncio


class Gate:
    """An admission gate: one ``set()`` releases every waiter currently
    blocked on ``wait()``, and the gate closes again behind them as they
    pass through, ready to be waited on again. ``set()`` with no waiter
    present leaves the gate open until the next waiter passes through;
    ``set()`` on an already-open gate does not queue an additional pass."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def set(self) -> None:
        """Opens the gate, releasing every waiter currently blocked on
        ``wait()``."""
        self._event.set()

    async def wait(self) -> None:
        """Blocks while the gate is closed, completing only once the gate
        has opened; the pass closes the gate again."""
        await self._event.wait()
        # Clearing is safe for everyone released by this opening: their
        # waiters were already resolved when set() fired, so they complete
        # regardless. The clear only denies later arrivals a free pass.
        self._event.clear()
