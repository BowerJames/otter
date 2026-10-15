"""What a model is to its callers, whichever provider serves it."""

from types import TracebackType
from typing import Protocol, Self

from otter.core.domain.messages import AssistantMessage

from .data import ModelInput


class Model(Protocol):
    """A model that produces the next turn of a conversation it is shown whole.

    A model is an async context manager, and may hold something open for as long as it
    is entered, such as a connection to its provider: use it in `async with`, and
    generate inside.
    """

    async def generate(self, model_input: ModelInput) -> AssistantMessage:
        """Return the turn the model produces next, given `model_input`.

        A part of a user turn the model cannot take in, an image or a sound clip, is not
        sent: a short note saying it was left out goes in its place. Thinking in the
        assistant turns of the context may not be sent, as the provider allows.

        Raises `ModelNotOpen` outside `async with`. Whatever the provider raises
        propagates.
        """
        ...

    async def __aenter__(self) -> Self:
        """Take hold of anything the model needs open; the model is returned.

        If that fails, the error propagates and the model is not open.
        """
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Let go of anything held open. The model is closed even if that fails."""
        ...
