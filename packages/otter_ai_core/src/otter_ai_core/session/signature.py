from collections.abc import Awaitable, Sequence
from types import TracebackType
from typing import Protocol, Self

from otter_ai_core.conversation import SessionMessage


class SessionManager(Protocol):
    def __aenter__(self) -> Awaitable[Self]: ...

    def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Awaitable[bool | None]: ...

    def append_message(self, message: SessionMessage) -> Awaitable[None]: ...

    def get_messages(self) -> Awaitable[Sequence[SessionMessage]]: ...
