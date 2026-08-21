from collections.abc import Sequence
from types import TracebackType
from typing import Self

from otter_ai_core.conversation import SessionMessage


class InMemorySessionManager:
    async def __aenter__(self) -> Self:
        raise NotImplementedError

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        raise NotImplementedError

    async def append_message(self, message: SessionMessage) -> None:
        raise NotImplementedError

    async def get_messages(self) -> Sequence[SessionMessage]:
        raise NotImplementedError
