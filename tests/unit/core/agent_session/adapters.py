"""Test adapters for the agent session's port."""

import asyncio
from collections.abc import Callable, Sequence

from otter.core.agent_session import AgentSessionPort, SessionControls, SessionEvent
from otter.core.domain.messages import AssistantMessage, ContextEntry, ToolCall


class FakeAgentSessionAdapter(AgentSessionPort):
    """The world of one session, scripted and recorded.

    The session starts with `context`. Each turn is the next of `script`, or the
    exception there raised in its place, and each tool call is answered with
    `tool_outcome`, or raises it. `shown` is each context the model was asked to answer,
    `runs` each tool call run, `recorded` each entry recorded, `told` each event, and
    `calls` each other call of the port, in order.

    A `fail_*` exception is raised at the call it names, and `failing_to_record` at
    every record while it is set. `acting_at` maps the name of a call of the port to
    something done to the session the first time that call is made. While
    `stalling_at_run` is set, the run of that number never finishes.
    """

    def __init__(self, context: Sequence[ContextEntry] = ()) -> None:
        self.context = list(context)
        self.script: list[AssistantMessage | Exception] = []
        self.tool_outcome: str | Exception = "file contents"
        self.shown: list[tuple[ContextEntry, ...]] = []
        self.runs: list[ToolCall] = []
        self.recorded: list[ContextEntry] = []
        self.told: list[SessionEvent] = []
        self.calls: list[str] = []
        self.fail_to_start: Exception | None = None
        self.fail_to_stop: Exception | None = None
        self.fail_before_idle: Exception | None = None
        self.failing_to_record: Exception | None = None
        self.acting_at: dict[str, Callable[[SessionControls], None]] = {}
        self.stalling_at_run: int | None = None
        self.stalled = asyncio.Event()
        self._session: SessionControls | None = None

    def _act_at(self, call: str) -> None:
        act = self.acting_at.pop(call, None)
        if act is not None and self._session is not None:
            act(self._session)

    async def start(self, session: SessionControls) -> Sequence[ContextEntry]:
        if self.fail_to_start is not None:
            raise self.fail_to_start
        self.calls.append("start")
        self._session = session
        self._act_at("start")
        return tuple(self.context)

    async def stop(self) -> None:
        self.calls.append("stop")
        if self.fail_to_stop is not None:
            raise self.fail_to_stop

    async def generate(self, context: Sequence[ContextEntry]) -> AssistantMessage:
        self.shown.append(tuple(context))
        self._act_at("generate")
        turn = self.script.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn

    async def run_tool(self, call: ToolCall) -> str:
        self.runs.append(call)
        self._act_at("run_tool")
        if len(self.runs) == self.stalling_at_run:
            self.stalled.set()
            await asyncio.Event().wait()  # an event nothing ever sets: the run never finishes
        if isinstance(self.tool_outcome, Exception):
            raise self.tool_outcome
        return self.tool_outcome

    def record(self, entry: ContextEntry) -> None:
        if self.failing_to_record is not None:
            raise self.failing_to_record
        self.recorded.append(entry)
        self._act_at("record")

    async def before_idle(self) -> None:
        self.calls.append("before_idle")
        if self.fail_before_idle is not None:
            error, self.fail_before_idle = self.fail_before_idle, None
            raise error
        self._act_at("before_idle")

    async def on_event(self, event: SessionEvent) -> None:
        self.told.append(event)
        self._act_at("on_event")
