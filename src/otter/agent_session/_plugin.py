"""What a plugin is to an agent session: the hooks it is asked at, and what it may do there."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from otter.core.domain.messages import AudioPart, ImagePart, ImageUrlPart, ToolCall

from ._agent_session import AgentTool, SessionEvent


@dataclass(frozen=True)
class SessionSetup:
    """What a session's model is started with: its system prompt and the tools it may ask for.

    A valid setup has no two tools of the same name.
    """

    system_prompt: str | None
    tools: tuple[AgentTool, ...]


@dataclass(frozen=True)
class Deny:
    """A plugin's refusal to let a tool call run; `reason` is shown to the model."""

    reason: str


class UnknownTool(LookupError):
    """The model asked for a tool the session does not have; `name` is what it asked for."""

    def __init__(self, name: str) -> None:
        super().__init__(f"the session has no tool named {name!r}")
        self.name = name


type ToolOutcome = str | Exception
"""How a tool call came out: the text the model is shown, or the error the call raised."""


class SessionControls(Protocol):
    """What a plugin's hook may do to the session it is asked by."""

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


class Plugin(Protocol):
    """Hooks an agent session asks as it runs, through which a plugin shapes what it does.

    A plugin holds the state of one session, shared between its hooks: make one for each
    session. Subclass `Plugin` and override the hooks wanted; the rest do nothing.

    A session asks its plugins in the order it was given them, and every plugin is asked
    at every hook, whatever the others answered. A hook that raises is not answered for
    by the plugins after it: the error propagates from the session at once.
    """

    async def before_start(self, session: SessionControls, setup: SessionSetup) -> SessionSetup:
        """Return the setup the session's model is to be started with.

        Asked as the session is entered, before its model is started. `setup` is what
        the plugin before returned, or what the session was made with; what the last
        plugin returns is used. If it raises, the session has not been entered.
        """
        return setup

    async def before_tool(self, session: SessionControls, call: ToolCall) -> Deny | None:
        """Refuse a tool call the model asked for by returning `Deny`, or let it be.

        A call any plugin denies is not run: the model is shown every plugin's reason
        as the call's result. If it raises, the session has ended.
        """
        return None

    async def after_tool(
        self, session: SessionControls, call: ToolCall, outcome: ToolOutcome
    ) -> ToolOutcome:
        """Return how a tool call that was run is to come out.

        `outcome` is what the plugin before returned, or what the tool did: the text it
        returned, the `Exception` it raised, or `UnknownTool` if the session has no such
        tool. Return text in place of an error to recover from it. If the last plugin
        returns text, the model is shown it; if an error, it is raised from the session,
        which has ended. Not asked for a call that was denied. If it raises, the
        session has ended.
        """
        return outcome

    async def before_idle(self, session: SessionControls) -> None:
        """Asked when the session is about to come to rest: prompt it to have it carry on.

        If any plugin queues a prompt, the session does not come to rest, and is asked
        again the next time it is about to. If it raises, the session is as it was.
        """
        return None

    async def on_event(self, session: SessionControls, event: SessionEvent) -> None:
        """Told each thing that happens in the session, just before its stream yields it.

        If it raises, the session is as it would be had the stream been abandoned there.
        """
        return None

    async def after_end(self, session: SessionControls) -> None:
        """Asked as a session that was entered is left: let go of anything the plugin holds.

        If it raises, the session's conversation is left all the same.
        """
        return None
