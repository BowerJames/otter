"""What an agent session is to its callers."""

from collections.abc import AsyncGenerator, Sequence
from types import TracebackType
from typing import Protocol, Self

from otter.core.domain.messages import AudioPart, ContextEntry, ImagePart, ImageUrlPart

from .data import SessionEvent


class AgentSession(Protocol):
    """One ongoing agent session: prompts are queued, and `stream` does the work.

    Nothing happens unless `stream` is being read: the session advances only as its
    events are taken.

    A session is an async context manager, and may hold something open for as long as
    it is entered, such as a connection to its model: use it in `async with`, so that it
    is ended and let go of. It runs only while entered: a stream read sooner waits.
    """

    def prompt(
        self,
        text: str,
        *,
        images: Sequence[ImagePart | ImageUrlPart] = (),
        audio: Sequence[AudioPart] = (),
    ) -> None:
        """Queue a user turn: `text`, then `images`, then `audio`. Returns at once.

        The turn joins the conversation at the next point the model can take it: straight
        away if the session is at rest, otherwise once every tool call of the model's
        current turn has its result. Queued turns join in the order they were made.
        Raises `SessionEnded` if the session has ended.
        """
        ...

    def stream(self) -> AsyncGenerator[SessionEvent, None]:
        """Run the session, yielding each thing that happens in it as it happens.

        Each entry is yielded as it joins the conversation: a queued prompt as a
        `UserMessage`, the model's turn as an `AssistantMessage`, and the result of each
        tool it asked for as a `ToolResultMessage`. The stream does not finish when the
        model does: it yields `Idle` and waits for the next prompt. It finishes once the
        session has ended. A session has one stream at a time: reading a second while
        the first is live raises `AlreadyStreaming`.

        Until the session is entered the stream yields nothing and waits. If entering
        fails while it waits, it raises what entering raised.

        If the model fails to produce a turn, the error propagates and the session is as
        it was, so streaming again retries. If a tool call fails, the error propagates
        and the session has ended: the model's turn is left asking for a result it never
        got. The same holds if the stream is abandoned or cancelled part-way through a
        turn's tool calls; use `end` to stop cleanly.
        """
        ...

    def history(self) -> Sequence[ContextEntry]:
        """Return every entry of the session's conversation so far, oldest first.

        That is the context the session was entered with, then each entry that has
        joined since. Empty until the session is entered. What is returned does not
        change as more entries join.
        """
        ...

    async def wait_for_idle(self) -> None:
        """Wait until the session is at rest: nothing queued and the model owed nothing.

        Returns at once if it already is, and also once the session has ended. A prompt
        just made counts as work outstanding. The session only advances while `stream`
        is being read, so this is for a task other than the one reading it.
        """
        ...

    def end(self) -> None:
        """End the session. Returns at once; ending an ended session does nothing.

        A turn the model is part-way through is finished, its tool calls included, and
        then the stream finishes without the model being asked again. Prompts still
        queued are dropped.
        """
        ...

    async def __aenter__(self) -> Self:
        """Enter the session, which is returned: `async with session:` scopes its life.

        Anything it needs open is taken hold of. If that fails, the error propagates
        and the session has not been entered: it is as it was, and may be entered again.
        """
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Leave the session: it is ended, and anything it holds open is let go of.

        If letting go fails, the error propagates and the session has ended all the same.
        """
        ...
