"""What a model needs from the provider that serves it."""

from typing import Protocol

from otter.core.domain.messages import AssistantMessage

from .data import ModelInput


class ModelPort(Protocol):
    """A provider's model, spoken to in the provider's own format."""

    async def open(self) -> None:
        """Take hold of anything the provider needs open between turns."""
        ...

    async def close(self) -> None:
        """Let go of anything `open` took hold of."""
        ...

    async def generate(self, model_input: ModelInput) -> AssistantMessage:
        """Send `model_input` to the model and return the turn it produces.

        Called only between `open` and `close`. The user turns of the context hold only
        what the model takes in. Each turn's context starts with the one before, entry
        for equal entry, unless the caller started the conversation over, so a provider
        may remember what it made of the entries it has seen.
        """
        ...
