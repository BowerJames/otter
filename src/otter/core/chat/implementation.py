"""A chat: what the user submits is put to a session, and what happens there is shown."""

import asyncio
from collections.abc import Iterator, Sequence

from otter.core.domain.messages import (
    AssistantMessage,
    ContextEntry,
    TextPart,
    ThinkingPart,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    UserPart,
)

from .data import (
    AssistantLine,
    ErrorLine,
    Idle,
    NoticeLine,
    ThinkingLine,
    ToolCallLine,
    ToolResultLine,
    TranscriptLine,
    UserLine,
)
from .port import ChatPort


class ChatImpl:
    """A chat with the session `port` holds, shown on its screen.

    The transcript opens with the session's conversation so far. Each message the user
    submits is put to the session, a blank one aside, and everything that happens in the
    session is shown as it happens. The status says whether the session is working or
    idle.

    If the session fails, the error is shown and the status is stopped: the chat goes
    on, and the next message has the session run again, which picks up from where it
    failed. A message the session will not take is shown as an error.
    """

    def __init__(self, port: ChatPort) -> None:
        self._port = port

    async def __call__(self) -> None:
        await self._port.open()
        try:
            for entry in self._port.history():
                self._show(entry)
            await self._take_submissions()
        finally:
            await self._port.close()

    async def _take_submissions(self) -> None:
        reading = asyncio.create_task(self._show_what_happens())
        try:
            async for text in self._port.submissions():
                if not text.strip():
                    continue
                try:
                    self._port.prompt(text)
                except Exception as error:
                    self._port.show(ErrorLine(str(error)))
                    continue
                self._port.set_status("working")
                # Reading stops when the session fails; reading again picks up from there.
                if reading.done():
                    reading = asyncio.create_task(self._show_what_happens())
        finally:
            reading.cancel()
            await asyncio.wait([reading])

    async def _show_what_happens(self) -> None:
        try:
            async for update in self._port.updates():
                if isinstance(update, Idle):
                    self._port.set_status("idle")
                else:
                    self._show(update)
        except Exception as error:
            self._port.show(ErrorLine(str(error)))
            self._port.show(NoticeLine("Send another message to try again."))
            self._port.set_status("stopped")

    def _show(self, entry: ContextEntry) -> None:
        for line in _lines_of(entry):
            self._port.show(line)


def _lines_of(entry: ContextEntry) -> Iterator[TranscriptLine]:
    match entry:
        case UserMessage(content):
            yield UserLine(_text_of(content))
        case AssistantMessage(content):
            for part in content:
                match part:
                    case ThinkingPart(text):
                        yield ThinkingLine(text)
                    case TextPart(text):
                        yield AssistantLine(text)
                    case ToolCall(_, name, arguments):
                        yield ToolCallLine(name, arguments)
        case ToolResultMessage(_, text):
            yield ToolResultLine(text)


def _text_of(content: Sequence[UserPart]) -> str:
    return " ".join(part.text if isinstance(part, TextPart) else "[attachment]" for part in content)
