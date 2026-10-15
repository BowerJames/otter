"""What an agent session needs from outside itself."""

from collections.abc import Sequence
from typing import Protocol

from otter.core.domain.messages import (
    AssistantMessage,
    AudioPart,
    ContextEntry,
    ImagePart,
    ImageUrlPart,
    ToolCall,
)

from .data import SessionEvent


class SessionControls(Protocol):
    """What the port may do to the session it serves, at any of its calls after `start`."""

    def prompt(
        self,
        text: str,
        *,
        images: Sequence[ImagePart | ImageUrlPart] = (),
        audio: Sequence[AudioPart] = (),
    ) -> None:
        """Queue a user turn, as `AgentSession.prompt` does."""
        ...

    def end(self) -> None:
        """End the session, as `AgentSession.end` does."""
        ...


class AgentSessionPort(Protocol):
    """The world one agent session runs in: its model, its tools, its record, and its hooks.

    The session calls `start` as it is entered, `stop` as it is left if `start`
    succeeded, and the rest only in between. Whatever a method raises propagates from
    the session, which says how it then stands.
    """

    async def start(self, session: SessionControls) -> Sequence[ContextEntry]:
        """Take hold of everything the session needs; return the context it starts with.

        The context is the session's conversation so far, oldest first. `session` is
        the session being started.
        """
        ...

    async def stop(self) -> None:
        """Let go of everything `start` took hold of."""
        ...

    async def generate(self, context: Sequence[ContextEntry]) -> AssistantMessage:
        """Return the model's next turn in the conversation `context`, oldest first."""
        ...

    async def run_tool(self, call: ToolCall) -> str:
        """Have the tool call the model asked for run; return the text it is shown."""
        ...

    def record(self, entry: ContextEntry) -> None:
        """Keep `entry`, which is about to join the conversation, for a later session.

        The entries recorded follow on from the context `start` returned.
        """
        ...

    async def before_idle(self) -> None:
        """Called when the session is about to come to rest.

        The session does not come to rest if a prompt has been queued by the time this
        returns, or if it has been ended.
        """
        ...

    async def on_event(self, event: SessionEvent) -> None:
        """Called with each thing that happens in the session, just before it is yielded."""
        ...
