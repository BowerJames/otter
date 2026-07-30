from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass(slots=True)
class State:
    _is_idle: asyncio.Event = field(default_factory=asyncio.Event)
    _is_closing: bool = False

    def __post_init__(self) -> None:
        # A fresh controller is idle: a ``generate()`` must be the first usable
        # command. ``asyncio.Event()`` starts unset (busy), so set it here.
        self._is_idle.set()

    @property
    def is_idle(self) -> asyncio.Event:
        return self._is_idle

    @property
    def is_closing(self) -> bool:
        return self._is_closing

    def set_idle(self) -> None:
        self._is_idle.set()

    def set_busy(self) -> None:
        self._is_idle.clear()

    def begin_closing(self) -> None:
        self._is_closing = True

    async def wait_for_idle(self) -> None:
        await self._is_idle.wait()
