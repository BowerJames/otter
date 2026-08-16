from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import ClassVar


class TerminatingStream[TPartialEvent, TTerminalEvent](ABC):
    terminal_event_type: ClassVar[type[TTerminalEvent]]

    @abstractmethod
    def _iterate_source(self) -> AsyncIterator[TPartialEvent | TTerminalEvent]: ...

    def __aiter__(self) -> AsyncIterator[TPartialEvent | TTerminalEvent]:
        return self._iterate_until_terminal_event()

    async def _iterate_until_terminal_event(self) -> AsyncIterator[TPartialEvent | TTerminalEvent]:
        async for event in self._iterate_source():
            yield event
            if isinstance(event, self.terminal_event_type):
                return
