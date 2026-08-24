from collections.abc import Awaitable, Sequence
from types import TracebackType
from typing import Protocol, Self

from otter_ai_core.types import SessionMessage


class SessionManager(Protocol):
    """Abstraction over an append-only store of a conversation's messages.

    A session manager is the durable record of one conversation. Messages
    are appended in the order they occur and read back in that order;
    entries are never modified or deleted. Completing the session (via
    __aexit__) durably persists every appended message, including when the
    session body raised."""

    def __aenter__(self) -> Awaitable[Self]:
        """Opens the session for reading and appending. The session's
        entries outlive any single open and persist across closes: a
        closed session may be reopened. Entering a session that is
        already open raises RuntimeError."""
        ...

    def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Awaitable[bool | None]:
        """Closes the session. Never suppresses exceptions from the session
        body. When this completes, every appended message is durably
        persisted."""
        ...

    def append_message(self, message: SessionMessage) -> Awaitable[None]:
        """Appends the message to the end of the session's ordered log.
        Messages carry identity minted upstream; the session manager
        invents none. Raises RuntimeError outside an open session."""
        ...

    def get_messages(self) -> Awaitable[Sequence[SessionMessage]]:
        """Returns every message in append order as a snapshot:
        prefix-stable, never mutated after return. Raises RuntimeError
        outside an open session."""
        ...
