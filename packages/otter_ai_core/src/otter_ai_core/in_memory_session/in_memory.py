from collections.abc import Sequence
from types import TracebackType
from typing import Self

from otter_ai_core.types import SessionEntry, SessionMessage


class InMemorySessionManager:
    """An in-memory session store. Writes are append-only: entries are
    held in the order they were appended and readable for the session's
    lifetime. Sessions may be closed and reopened; entries persist across
    opens."""

    def __init__(self) -> None:
        self._messages: list[SessionEntry] = []
        self._open = False

    async def __aenter__(self) -> Self:
        """Opens the session. Entering a session that is already open
        raises RuntimeError; a closed session may be reopened."""
        if self._open:
            raise RuntimeError(
                "InMemorySessionManager session is already open; close it before reopening"
            )
        self._open = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Closes the session. Exceptions from the session body propagate."""
        self._open = False

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
        if not self._open:
            raise RuntimeError(f"{method}() called outside an open session")
