import asyncio


class Gate:
    """An admission gate: one ``open()`` releases every waiter currently
    blocked on ``wait_for_open()``, and the gate closes again behind them
    as they pass through, ready to be waited on again. ``open()`` with no
    waiter present leaves the gate open until the next waiter passes
    through; ``open()`` on an already-open gate does not queue an
    additional pass."""

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._arrival = asyncio.Event()
        self._parked = 0

    def open(self) -> None:
        """Opens the gate, releasing every waiter currently blocked on
        ``wait_for_open()``."""
        # The arrival epoch ends the moment the parked callers are
        # released, ahead of their resumption.
        self._arrival.clear()
        self._event.set()

    async def wait_for_open(self) -> None:
        """Blocks while the gate is closed, completing only once the gate
        has opened; the pass closes the gate again."""
        # A caller finding the gate already open takes a free pass and
        # never pauses, so it counts as no arrival.
        parked = not self._event.is_set()
        if parked:
            self._parked += 1
            self._arrival.set()
        try:
            await self._event.wait()
        finally:
            if parked:
                # Runs on release and cancellation alike, so the arrival
                # signal drops only when no caller is left at the gate.
                self._parked -= 1
                if self._parked == 0:
                    self._arrival.clear()
        # Clearing is safe for everyone released by this opening: their
        # waiters were already resolved when open() fired, so they complete
        # regardless. The clear only denies later arrivals a free pass.
        self._event.clear()

    async def wait_for_arrival(self) -> None:
        """Completes once at least one caller is blocked in
        ``wait_for_open()`` at the closed gate — the pause point is
        reached. The signal resets when ``open()`` releases the parked
        callers, and fires again for the next arrival. A caller passing
        straight through an already-open gate does not count as an
        arrival: nothing is paused at the gate. If every parked caller is
        cancelled, the signal resets."""
        await self._arrival.wait()
