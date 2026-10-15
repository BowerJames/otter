"""A model, served by the provider behind its port."""

from types import TracebackType
from typing import Self

from otter.core.domain.messages import (
    AssistantMessage,
    AudioPart,
    ContextEntry,
    ImagePart,
    ImageUrlPart,
    TextPart,
    UserMessage,
    UserPart,
)

from .data import ModelInput
from .errors import ModelNotOpen
from .port import ModelPort

_IMAGE_OMITTED = TextPart("[image omitted: this model cannot view images]")
_AUDIO_OMITTED = TextPart("[audio omitted: this model cannot hear audio]")


class ModelImpl:
    """A model served by `port`.

    `accepts_images` and `accepts_audio` say what the model can take in: a part of a user
    turn it cannot is replaced by a short note before the provider sees it.
    """

    def __init__(self, port: ModelPort, *, accepts_images: bool, accepts_audio: bool) -> None:
        self._port = port
        self._accepts_images = accepts_images
        self._accepts_audio = accepts_audio
        self._open = False

    async def generate(self, model_input: ModelInput) -> AssistantMessage:
        if not self._open:
            raise ModelNotOpen()
        context = tuple(self._taken_in(entry) for entry in model_input.context)
        return await self._port.generate(ModelInput(model_input.system, model_input.tools, context))

    def _taken_in(self, entry: ContextEntry) -> ContextEntry:
        """`entry` as the model can take it in: the same object, if it can take all of it."""
        if not isinstance(entry, UserMessage) or all(map(self._accepts, entry.content)):
            return entry
        return UserMessage(tuple(self._note_for(part) for part in entry.content))

    def _accepts(self, part: UserPart) -> bool:
        match part:
            case ImagePart() | ImageUrlPart():
                return self._accepts_images
            case AudioPart():
                return self._accepts_audio
            case _:
                return True

    def _note_for(self, part: UserPart) -> UserPart:
        if self._accepts(part):
            return part
        return _AUDIO_OMITTED if isinstance(part, AudioPart) else _IMAGE_OMITTED

    async def __aenter__(self) -> Self:
        await self._port.open()
        self._open = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._open = False
        await self._port.close()
