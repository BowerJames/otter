"""What tools and plugins are to the plugin host: the ways a session is extended."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from otter.core.agent_session import SessionControls, SessionEvent
from otter.core.domain.messages import ToolCall


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


type ToolOutcome = str | Exception
"""How a tool call came out: the text the model is shown, or the error the call raised."""


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

        Asked as the session is entered, before its model is opened. `setup` is what the
        plugin before returned, or what the session was made with; what the last plugin
        returns is used. If it raises, the session has not been entered.
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

        If it raises, the session's model is closed all the same.
        """
        return None
