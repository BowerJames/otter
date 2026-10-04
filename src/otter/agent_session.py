"""What an ongoing agent session is to its callers, whichever kind of model it runs on."""

from collections.abc import AsyncGenerator, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from otter.messages import AssistantMessage, AudioPart, ImagePart, ImageUrlPart, UserPart


class AgentTool(Protocol):
    """A tool a model may ask for, and how it is run.

    `name`, `description` and `parameters` (a JSON Schema object) are what the model is
    told about the tool.
    """

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def parameters(self) -> Mapping[str, object]: ...

    async def execute(self, args: Mapping[str, object]) -> str:
        """Run the tool with the arguments the model supplied; return the text it is shown."""
        ...


@dataclass(frozen=True)
class UserTurn:
    """A queued prompt has joined the conversation."""

    content: tuple[UserPart, ...]


@dataclass(frozen=True)
class AssistantTurn:
    """The model produced a turn."""

    message: AssistantMessage


@dataclass(frozen=True)
class ToolResult:
    """A tool the model asked for has run; `text` is the result the model is shown."""

    tool_call_id: str
    text: str


@dataclass(frozen=True)
class Idle:
    """The session has come to rest: nothing is queued and the model is owed nothing."""


type SessionEvent = UserTurn | AssistantTurn | ToolResult | Idle


class AgentSession(Protocol):
    """One ongoing agent session: prompts are queued, and `stream` does the work.

    Nothing happens unless `stream` is being read: the session advances only as its
    events are taken.
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
        Raises `RuntimeError` if the session has ended.
        """
        ...

    def stream(self) -> AsyncGenerator[SessionEvent, None]:
        """Run the session, yielding each thing that happens in it as it happens.

        The stream does not finish when the model does: it yields `Idle` and waits for
        the next prompt. It finishes once the session has ended. A session has one
        stream at a time: reading a second while the first is live raises `RuntimeError`.

        If the model fails to produce a turn, the error propagates and the session is as
        it was, so streaming again retries. If a tool fails, the error propagates and the
        session has ended. The same holds if the stream is abandoned or cancelled
        part-way through a turn's tool calls; use `end` to stop cleanly.
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
