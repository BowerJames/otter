"""Test adapters for what the plugin host is made with: a model, a session log, the session it
serves, tools and plugins.
"""

from collections.abc import Mapping, Sequence
from types import TracebackType
from typing import Self

from otter.core.agent_session import SessionControls, SessionEvent
from otter.core.domain.messages import (
    AssistantMessage,
    AudioPart,
    ContextEntry,
    ImagePart,
    ImageUrlPart,
    TextPart,
    ToolCall,
)
from otter.core.model import Model, ModelInput
from otter.core.session_log import SessionLog
from otter.infrastructure.adapters.agent_session.plugin_host import (
    Deny,
    Plugin,
    SessionSetup,
    ToolOutcome,
)


class FakeModel(Model):
    """Answers every turn with `reply`; `shown` is each input it was given, and `calls` each
    time it was opened or closed. While `fail_to_open` is set, opening raises it.
    """

    def __init__(self) -> None:
        self.reply = AssistantMessage((TextPart("Hi!"),))
        self.shown: list[ModelInput] = []
        self.calls: list[str] = []
        self.fail_to_open: Exception | None = None

    async def generate(self, model_input: ModelInput) -> AssistantMessage:
        self.shown.append(model_input)
        return self.reply

    async def __aenter__(self) -> Self:
        if self.fail_to_open is not None:
            raise self.fail_to_open
        self.calls.append("open")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.calls.append("close")


class FakeSessionLog(SessionLog):
    """Holds the entries it starts with, then those appended to it, in `held`."""

    def __init__(self, held: Sequence[ContextEntry] = ()) -> None:
        self.held = list(held)

    def append(self, entry: ContextEntry) -> None:
        self.held.append(entry)

    def entries(self) -> Sequence[ContextEntry]:
        return tuple(self.held)


class FakeSession(SessionControls):
    """Records the prompts made to it, and whether it was ended."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.ended = False

    def prompt(
        self,
        text: str,
        *,
        images: Sequence[ImagePart | ImageUrlPart] = (),
        audio: Sequence[AudioPart] = (),
    ) -> None:
        self.prompts.append(text)

    def end(self) -> None:
        self.ended = True


class FakeFiles:
    """A tool that records the arguments of each run, and answers with fixed text."""

    name = "read_file"
    description = "Read a file"
    parameters: Mapping[str, object] = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
    }

    def __init__(self) -> None:
        self.runs: list[Mapping[str, object]] = []

    async def execute(self, args: Mapping[str, object]) -> str:
        self.runs.append(args)
        return "file contents"


class UnreadableFiles(FakeFiles):
    """A tool whose every run fails."""

    async def execute(self, args: Mapping[str, object]) -> str:
        raise PermissionError("a.txt is not readable")


class Recorder(Plugin):
    """Records each hook it is asked at, under `name`, in a log it may share with others."""

    def __init__(self, name: str = "plugin", log: list[tuple[object, ...]] | None = None) -> None:
        self.name = name
        self.log: list[tuple[object, ...]] = [] if log is None else log

    def asked_at(self, hook: str) -> list[tuple[object, ...]]:
        return [entry for entry in self.log if entry[1] == hook]

    async def before_start(self, session: SessionControls, setup: SessionSetup) -> SessionSetup:
        self.log.append((self.name, "before_start", setup))
        return setup

    async def before_tool(self, session: SessionControls, call: ToolCall) -> Deny | None:
        self.log.append((self.name, "before_tool", call))
        return None

    async def after_tool(
        self, session: SessionControls, call: ToolCall, outcome: ToolOutcome
    ) -> ToolOutcome:
        self.log.append((self.name, "after_tool", call, outcome))
        return outcome

    async def before_idle(self, session: SessionControls) -> None:
        self.log.append((self.name, "before_idle", session))

    async def on_event(self, session: SessionControls, event: SessionEvent) -> None:
        self.log.append((self.name, "on_event", session, event))

    async def after_end(self, session: SessionControls) -> None:
        self.log.append((self.name, "after_end", session))
