from collections.abc import Sequence
from enum import Enum, auto
from types import TracebackType
from typing import Self

from otter_ai_core.types import SessionEntry, SessionMessage


class _SessionState(Enum):
    NEW = auto()
    OPEN = auto()
    CLOSED = auto()


class InMemorySessionManager:
    """An in-memory session store. Writes are append-only: entries are held
    in the order they were appended and readable for the session's
    lifetime."""

    def __init__(self) -> None:
        self._messages: list[SessionEntry] = []
        self._state = _SessionState.NEW

    async def __aenter__(self) -> Self:
        """Opens the session. A session can only be entered once;
        re-entering raises RuntimeError."""
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
        """Closes the session. Exceptions from the session body propagate."""
        self._state = _SessionState.CLOSED

    async def append_message(self, message: SessionMessage) -> None:
        """Appends the message to the session. Raises RuntimeError outside an
        open session."""
        self._require_open("append_message")
        self._messages.append(message)

    async def get_messages(self) -> Sequence[SessionMessage]:
        """Returns the session's messages in order. Raises RuntimeError
        outside an open session. The returned sequence is a snapshot: later
        appends do not alter it."""
        self._require_open("get_messages")
        return self.entries

    @property
    def entries(self) -> Sequence[SessionEntry]:
        """Returns the session's entries in order, regardless of session
        state, including after the session closes."""
        return tuple(self._messages)

    def _require_open(self, method: str) -> None:
        if self._state is not _SessionState.OPEN:
            raise RuntimeError(
                f"{method}() called outside an open session (state: {self._state.name})"
            )
