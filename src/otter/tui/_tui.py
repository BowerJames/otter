"""A chat with an agent session, held on a screen."""

import asyncio
from collections.abc import Awaitable, Callable, Iterator, Sequence

from otter.agent_session import AgentSession, AssistantTurn, Idle, ToolResult, UserTurn
from otter.chat_screen import (
    AssistantLine,
    ChatScreen,
    ErrorLine,
    NoticeLine,
    ThinkingLine,
    ToolCallLine,
    ToolResultLine,
    TranscriptLine,
    UserLine,
)
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

type Tui = Callable[[], Awaitable[None]]
"""Holds the chat; returns once the user quits."""


def create_session_tui(
    session: AgentSession, screen: ChatScreen, *, context: Sequence[ContextEntry] = ()
) -> Tui:
    """Return a chat with `session`, held on `screen`.

    The transcript opens with `context`, which is what the session started out with;
    leave it out for a session that started with nothing. Each message the user submits
    is put to the session as a prompt, a blank one aside, and everything that happens in
    the session is shown as it happens. The status says whether the session is working
    or idle.

    If the session fails, the error is shown and the status is stopped: the chat goes
    on, and the next message has the session streamed again, which retries what failed.
    A message the session will not take, because it has ended, is shown as an error.

    The chat lasts until the user quits, and then stops reading the session. It neither
    puts `screen` up nor ends `session`: both are the caller's, to be entered before the
    chat is held and left after it.
    """

    async def show_what_happens() -> None:
        try:
            async for event in session.stream():
                match event:
                    case UserTurn(content):
                        screen.show(_users_line(content))
                    case AssistantTurn(message):
                        for line in _models_lines(message):
                            screen.show(line)
                    case ToolResult(_, text):
                        screen.show(ToolResultLine(text))
                    case Idle():
                        screen.set_status("idle")
        except Exception as error:
            screen.show(ErrorLine(str(error)))
            screen.show(NoticeLine("Send another message to try again."))
            screen.set_status("stopped")

    async def chat() -> None:
        for entry in context:
            match entry:
                case UserMessage(content):
                    screen.show(_users_line(content))
                case AssistantMessage():
                    for line in _models_lines(entry):
                        screen.show(line)
                case ToolResultMessage(_, text):
                    screen.show(ToolResultLine(text))
        reading = asyncio.create_task(show_what_happens())
        try:
            async for text in screen.submissions():
                if not text.strip():
                    continue
                try:
                    session.prompt(text)
                except RuntimeError as error:
                    screen.show(ErrorLine(str(error)))
                    continue
                screen.set_status("working")
                # The stream stops when the session fails; reading it again retries
                # what failed.
                if reading.done():
                    reading = asyncio.create_task(show_what_happens())
        finally:
            reading.cancel()
            await asyncio.wait([reading])

    return chat


def _users_line(content: Sequence[UserPart]) -> UserLine:
    return UserLine(
        " ".join(part.text if isinstance(part, TextPart) else "[attachment]" for part in content)
    )


def _models_lines(message: AssistantMessage) -> Iterator[TranscriptLine]:
    for part in message.content:
        match part:
            case ThinkingPart(text):
                yield ThinkingLine(text)
            case TextPart(text):
                yield AssistantLine(text)
            case ToolCall(_, name, arguments):
                yield ToolCallLine(name, arguments)
