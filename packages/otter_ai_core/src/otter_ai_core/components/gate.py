class Gate:
    """An admission gate: one ``set()`` releases every waiter currently
    blocked on ``wait()``, and the gate closes again behind them, ready
    to be waited on again. ``set()`` with no waiter present leaves the
    gate open until the next waiter passes through; ``set()`` on an
    already-open gate does not queue an additional pass."""

    def set(self) -> None:
        """Opens the gate, releasing every waiter currently blocked on
        ``wait()``."""
        raise NotImplementedError

    async def wait(self) -> None:
        """Blocks while the gate is closed, completing only once the gate
        has opened."""
        raise NotImplementedError
