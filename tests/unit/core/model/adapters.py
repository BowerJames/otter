"""Test adapters for the model's port."""

from otter.core.domain.messages import AssistantMessage, TextPart
from otter.core.model import ModelInput, ModelPort


class FakeModelAdapter(ModelPort):
    """Records what it is asked, and answers every turn with `reply`.

    `calls` lists "open", "close" and each input generated from, in order. While
    `failing_to_open` is set, opening raises it.
    """

    def __init__(self) -> None:
        self.reply = AssistantMessage((TextPart("Hi!"),))
        self.calls: list[str | ModelInput] = []
        self.failing_to_open: Exception | None = None

    async def open(self) -> None:
        if self.failing_to_open is not None:
            raise self.failing_to_open
        self.calls.append("open")

    async def close(self) -> None:
        self.calls.append("close")

    async def generate(self, model_input: ModelInput) -> AssistantMessage:
        self.calls.append(model_input)
        return self.reply
