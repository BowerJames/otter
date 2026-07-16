import asyncio
from dataclasses import dataclass, field


@dataclass(slots=True)
class State:
    _is_idle: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self) -> None:
        self._is_idle.set()

    def set_idle(self) -> None:
        self._is_idle.set()

    def set_busy(self) -> None:
        self._is_idle.clear()
