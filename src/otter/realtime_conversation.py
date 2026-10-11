"""What a caller needs from a conversation with a model that replies as it goes."""

from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from typing import Protocol

from otter.messages import AssistantMessage, ContextEntry, ToolSpec, UserPart


@dataclass(frozen=True)
class TextDelta:
    """The next piece of the text the model is writing."""

    text: str


@dataclass(frozen=True)
class AudioDelta:
    """The next piece of what the model is saying: `data` is 16-bit mono PCM at 24 kHz."""

    data: bytes


@dataclass(frozen=True)
class TranscriptDelta:
    """The next piece of the transcript of what the model is saying."""

    text: str


@dataclass(frozen=True)
class TurnDone:
    """The model has finished its turn: `message` is the whole of it.

    What the model said aloud is in `message` as the text of its transcript.
    """

    message: AssistantMessage


type RealtimeEvent = TextDelta | AudioDelta | TranscriptDelta | TurnDone


class RealtimeConversation(Protocol):
    """One conversation with one model: it holds the history and streams the next turn.

    A conversation may hold a connection open between turns; `aclose` lets go of it.
    """

    def add_user_message(self, content: Sequence[UserPart]) -> None:
        """Append a user turn; it is sent to the model on the next `generate`."""
        ...

    def add_tool_result(self, tool_call_id: str, text: str) -> None:
        """Append the result of a tool call the model asked for in its last turn."""
        ...

    def generate(self) -> AsyncGenerator[RealtimeEvent, None]:
        """Have the model take its turn, yielding each piece of it as it is produced.

        The last thing yielded is a `TurnDone` holding the whole turn, which by then has
        joined the history. Nothing is sent until the stream is read. If generating
        fails, the error propagates and the history is left as it was. Closing the
        stream before `TurnDone` abandons the turn: the model stops, and the history is
        left as it was.
        """
        ...

    async def aclose(self) -> None:
        """Let go of any connection held. Closing a closed conversation does nothing."""
        ...


class RealtimeConversationFactory(Protocol):
    """Starts a new realtime conversation with `model`.

    `context` is the history the conversation starts out with, oldest first; leave it
    out to start empty. It is sent to the model as it stands, ahead of anything added
    later. The thinking in its assistant turns is not sent.
    """

    def __call__(
        self,
        model: str,
        *,
        system: str | None = None,
        tools: Sequence[ToolSpec] = (),
        context: Sequence[ContextEntry] = (),
    ) -> RealtimeConversation: ...
