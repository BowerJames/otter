"""A conversation with a model served over OpenAI's realtime endpoint."""

import base64
import io
import json
import wave
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from typing import Protocol, assert_never

from openai.types.realtime import (
    ConversationItemParam,
    RealtimeClientEventParam,
    RealtimeResponse,
    RealtimeServerEvent,
    RealtimeSessionCreateRequestParam,
)
from openai.types.realtime.realtime_conversation_item_user_message_param import (
    Content as UserContentParam,
)

from otter.messages import (
    AssistantMessage,
    AssistantPart,
    AudioPart,
    ContextEntry,
    ImagePart,
    ImageUrlPart,
    TextPart,
    ThinkingPart,
    ToolCall,
    ToolResultMessage,
    ToolSpec,
    UserMessage,
    UserPart,
)
from otter.realtime_conversation import (
    AudioDelta,
    RealtimeEvent,
    TextDelta,
    TranscriptDelta,
    TurnDone,
)


class RealtimeConnection(Protocol):
    """One open connection to a realtime endpoint: events go out, and events come back."""

    async def send(self, event: RealtimeClientEventParam) -> None: ...

    def __aiter__(self) -> AsyncIterator[RealtimeServerEvent]:
        """The events the endpoint sends, as they arrive, until the connection closes."""
        ...


type RealtimeConnect = Callable[[str], AbstractAsyncContextManager[RealtimeConnection]]
"""Opens a connection for a conversation with the named model; leaving it closes it."""


class OpenAIRealtimeConversation:
    """One conversation with one model: it holds the history and streams the next turn.

    `connect` opens the connection the model is spoken to over, and so decides which
    provider that is. `system` is the system prompt the model sees ahead of every turn,
    and `tools` are the tools it may ask to have called. `context` is the history the
    conversation starts out with, oldest first; the thinking in its assistant turns is
    not sent.

    Given a `voice`, the model speaks its turns in it: they arrive as sound and as a
    transcript, and join the history as the transcript. Left out, the model writes its
    turns as text.

    One connection is made, when the first turn is generated, and kept between turns:
    the endpoint holds the conversation while it lasts, so each turn sends only what was
    added since. The history is kept here too, and is what counts: whenever the
    connection is let go of, by `aclose` or by a turn that fails or is abandoned, the
    next turn sends all of it over a new one. A conversation that is done with should
    be closed.

    Images are sent to the model, but only those carried inline: one given as a URL is
    replaced by a short text note saying it was omitted. Audio is sent only as 16-bit
    mono wav at 24 kHz, the one form the endpoint takes without converting; any other
    clip is replaced by such a note.

    An instance is a single conversation, so one turn is generated at a time.
    """

    def __init__(
        self,
        connect: RealtimeConnect,
        model: str,
        *,
        system: str | None = None,
        tools: Sequence[ToolSpec] = (),
        context: Sequence[ContextEntry] = (),
        voice: str | None = None,
    ) -> None:
        self._connect = connect
        self._model = model
        # Kept in wire form: the history is only ever read back by the endpoint.
        self._items: list[ConversationItemParam] = []
        # How many of the items the endpoint has: it holds the conversation while the
        # connection lasts, so only what it lacks is sent.
        self._sent = 0
        self._connection: RealtimeConnection | None = None
        self._events: AsyncIterator[RealtimeServerEvent] | None = None
        self._open = AsyncExitStack()
        self._session: RealtimeSessionCreateRequestParam = {
            "type": "realtime",
            "output_modalities": ["text"],
        }
        if voice is not None:
            self._session["output_modalities"] = ["audio"]
            self._session["audio"] = {"output": {"voice": voice}}
        if system is not None:
            self._session["instructions"] = system
        if tools:
            self._session["tools"] = [
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": dict(tool.parameters),
                }
                for tool in tools
            ]
        for entry in context:
            match entry:
                case UserMessage():
                    self.add_user_message(entry.content)
                case AssistantMessage():
                    self._items.extend(_assistant_turn_on_the_wire(entry))
                case ToolResultMessage():
                    self.add_tool_result(entry.tool_call_id, entry.text)
                case _:
                    assert_never(entry)

    def add_user_message(self, content: Sequence[UserPart]) -> None:
        """Append a user turn; it is sent to the model on the next `generate`."""
        self._items.append(
            {"type": "message", "role": "user", "content": [_on_the_wire(p) for p in content]}
        )

    def add_tool_result(self, tool_call_id: str, text: str) -> None:
        """Append the result of a tool call the model asked for in its last turn."""
        self._items.append(
            {"type": "function_call_output", "call_id": tool_call_id, "output": text}
        )

    async def generate(self) -> AsyncGenerator[RealtimeEvent, None]:
        """Have the model take its turn, yielding each piece of it as it is produced.

        The last thing yielded is a `TurnDone` holding the whole turn, which by then has
        joined the history. Nothing is sent, and no connection made, until the stream is
        read. The conversation is sent as it stands: one the endpoint cannot accept,
        such as a tool call left without a result, is the endpoint's to reject.

        If the connection cannot be made or fails, the endpoint reports an error or that
        the model failed (a `RuntimeError`), the connection closes before the turn is
        done (a `RuntimeError`), or the model's turn cannot be read (tool arguments that
        are not valid JSON raise `json.JSONDecodeError`), the error propagates and the
        history is left as it was. Closing the stream before `TurnDone` abandons the
        turn: the model stops, and the history is left as it was. Either way the
        connection is let go of, and the next `generate` makes a new one.
        """
        done = False
        try:
            connection, events = await self._connected()
            for item in self._items[self._sent :]:
                await connection.send({"type": "conversation.item.create", "item": item})
            await connection.send({"type": "response.create"})
            async for event in events:
                if event.type == "response.output_text.delta":
                    yield TextDelta(event.delta)
                elif event.type == "response.output_audio.delta":
                    yield AudioDelta(base64.b64decode(event.delta))
                elif event.type == "response.output_audio_transcript.delta":
                    yield TranscriptDelta(event.delta)
                elif event.type == "error":
                    raise RuntimeError(f"the model failed: {event.error.message}")
                elif event.type == "response.done":
                    message = _turn_of(event.response)
                    # The endpoint already holds the turn it produced.
                    self._items.extend(_assistant_turn_on_the_wire(message))
                    self._sent = len(self._items)
                    done = True
                    yield TurnDone(message)
                    return
            raise RuntimeError("the connection closed before the model finished its turn")
        finally:
            # The endpoint's copy of the conversation can no longer be trusted to match
            # the history: it may hold part of a turn, or items the history never took.
            if not done:
                await self.aclose()

    async def _connected(self) -> tuple[RealtimeConnection, AsyncIterator[RealtimeServerEvent]]:
        if self._connection is None or self._events is None:
            self._connection = await self._open.enter_async_context(self._connect(self._model))
            self._events = aiter(self._connection)
            await self._connection.send({"type": "session.update", "session": self._session})
        return self._connection, self._events

    async def aclose(self) -> None:
        """Close the connection, if one is open. The conversation can still be used:
        the next `generate` sends the whole history over a new connection.
        """
        # Forgotten before it is closed, so a connection that fails to close is not
        # used again.
        opened, self._open = self._open, AsyncExitStack()
        self._connection = self._events = None
        self._sent = 0
        await opened.aclose()


def _turn_of(response: RealtimeResponse) -> AssistantMessage:
    if response.status == "failed":
        failure = response.status_details and response.status_details.error
        reason = (failure and (failure.code or failure.type)) or "no reason given"
        raise RuntimeError(f"the model failed: {reason}")
    content: list[AssistantPart] = []
    for item in response.output or []:
        if item.type == "message" and item.role == "assistant":
            content.extend(
                # What the model said aloud is kept as its transcript.
                TextPart(part.text or part.transcript or "")
                for part in item.content
            )
        elif item.type == "function_call":
            content.append(
                ToolCall(
                    id=item.call_id or "", name=item.name, arguments=json.loads(item.arguments)
                )
            )
    return AssistantMessage(tuple(content))


_AUDIO_OMITTED = "[audio omitted: this model hears only 16-bit mono 24 kHz wav audio]"


def _on_the_wire(part: UserPart) -> UserContentParam:
    match part:
        case TextPart():
            return {"type": "input_text", "text": part.text}
        case ImagePart():
            return {
                "type": "input_image",
                "image_url": f"data:{part.media_type};base64,{part.data}",
            }
        case ImageUrlPart():
            return {
                "type": "input_text",
                "text": "[image omitted: this model takes images inline, not from a URL]",
            }
        case AudioPart():
            samples = _samples_of(part)
            if samples is None:
                return {"type": "input_text", "text": _AUDIO_OMITTED}
            return {"type": "input_audio", "audio": base64.b64encode(samples).decode()}
        case _:
            assert_never(part)


def _samples_of(audio: AudioPart) -> bytes | None:
    """The samples of a clip already in the one form the endpoint takes, or None."""
    if audio.format != "wav":
        return None
    try:
        with wave.open(io.BytesIO(base64.b64decode(audio.data))) as clip:
            fits = (clip.getnchannels(), clip.getsampwidth(), clip.getframerate()) == (1, 2, 24000)
            return clip.readframes(clip.getnframes()) if fits else None
    except (wave.Error, EOFError, ValueError):
        return None


def _assistant_turn_on_the_wire(message: AssistantMessage) -> list[ConversationItemParam]:
    items: list[ConversationItemParam] = []
    for part in message.content:
        match part:
            case TextPart():
                items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": part.text}],
                    }
                )
            case ToolCall():
                items.append(
                    {
                        "type": "function_call",
                        "call_id": part.id,
                        "name": part.name,
                        "arguments": json.dumps(part.arguments),
                    }
                )
            case ThinkingPart():
                # The endpoint has no place for reasoning it did not produce itself.
                pass
            case _:
                assert_never(part)
    return items
