from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing
from typing import ClassVar


class TerminatingStream[TPartialEvent, TTerminalEvent](ABC):
    terminal_event_type: ClassVar[type[TTerminalEvent]]

    @abstractmethod
    def _iterate_source(self) -> AsyncGenerator[TPartialEvent | TTerminalEvent, None]: ...

    def __aiter__(self) -> AsyncIterator[TPartialEvent | TTerminalEvent]:
        return self._iterate_until_terminal_event()

    async def _iterate_until_terminal_event(self) -> AsyncIterator[TPartialEvent | TTerminalEvent]:
        async with aclosing(self._iterate_source()) as source:
            async for event in source:
                yield event
                if isinstance(event, self.terminal_event_type):
                    return
