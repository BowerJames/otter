from collections.abc import Sequence
from enum import Enum, auto
from types import TracebackType
from typing import Self

from otter_ai_core.conversation import SessionEntry, SessionMessage


class _SessionState(Enum):
    NEW = auto()
    OPEN = auto()
    CLOSED = auto()


class InMemorySessionManager:
    def __init__(self) -> None:
        self._messages: list[SessionMessage] = []
        self._state = _SessionState.NEW

    async def __aenter__(self) -> Self:
        if self._state is not _SessionState.NEW:
            raise RuntimeError(
                "InMemorySessionManager session can only be entered once; "
                "construct a new InMemorySessionManager"
            )
        self._state = _SessionState.OPEN
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._state = _SessionState.CLOSED

    async def append_message(self, message: SessionMessage) -> None:
        self._require_open("append_message")
        self._messages.append(message)

    async def get_messages(self) -> Sequence[SessionMessage]:
        self._require_open("get_messages")
        return tuple(self._messages)

    @property
    def entries(self) -> Sequence[SessionEntry]:
        return tuple(self._messages)

    def _require_open(self, method: str) -> None:
        if self._state is not _SessionState.OPEN:
            raise RuntimeError(
                f"{method}() called outside an open session (state: {self._state.name})"
            )
