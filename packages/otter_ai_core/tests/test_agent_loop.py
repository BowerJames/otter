"""AgentLoop: the turn/tool-execution cycle over a ModelController.

Tests exercise ``agent_loop.AgentLoop``'s minimal port onto the async
:class:`~otter_ai_core.model_controller.ModelController`:

* the turn/tool cycle (generate -> execute tool calls -> add tool results ->
  repeat until the model stops);
* ``ToolExecMode`` sequential vs concurrent dispatch;
* ``_max_turns`` cap (counted as completed turns; tools never dropped);
* unknown-tool synthesis (``is_error`` result naming available tools);
* ``terminate`` / ``is_error`` propagation;
* abort honoured between turns (the abort signal is the one passed to tools);
* steering injected before each turn; follow-ups driving multiple inner loops.

A lightweight fake controller (duck-typed to ``add_message`` / ``generate``)
drives the FSM.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, cast

import pytest
from pydantic import BaseModel

from otter_ai_core import (
    AssistantContextItem,
    AssistantMessage,
    StopReason,
    TextContent,
    ToolCall,
    ToolResultContextItem,
    Usage,
    UsageCost,
    UserContextItem,
    UserMessage,
)
from otter_ai_core.agent_loop import BEFORE_TOOL_CALL, TOOL_RESULT, ToolResultHookParams
from otter_ai_core.agent_loop.agent_loop import AgentLoop, QueueMode, ToolExecMode
from otter_ai_core.agent_loop.agent_tool import AgentToolResult, DefaultAgentTool
from otter_ai_core.context import Role
from otter_ai_core.hook_runner import Hook, HookRunner
from otter_ai_core.interfaces import AgentTool, ModelController
from otter_ai_core.model_connection import AddToolResultMessage, AddUserMessage

# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _Ping:
    msg: str


@dataclass(frozen=True, slots=True)
class _Pong:
    echoed: str


#: Module-level hook singleton — the intended usage pattern.
_PING: Hook[_Ping, _Pong] = Hook("ping")


def _usage() -> Usage:
    return Usage(
        input=10,
        output=5,
        cache_read=0,
        cache_write=0,
        total_tokens=15,
        cost=UsageCost(input=0.0, output=0.0, cache_read=0.0, cache_write=0.0, total=0.0),
    )


def _user_message(text: str = "hi") -> UserMessage:
    return UserMessage(role=Role.User, content=text, timestamp=0)


def _tool_call(name: str, *, id: str = "c1", arguments: dict[str, Any] | None = None) -> ToolCall:
    return ToolCall(type="tool_call", id=id, name=name, arguments=arguments or {})


def _assistant_message(tool_calls: list[ToolCall] | None = None) -> AssistantMessage:
    content: list[Any] = [TextContent(type="text", text="ok")]
    if tool_calls:
        content.extend(tool_calls)
    return AssistantMessage(
        role=Role.Assistant,
        content=content,
        api="test",
        provider="test",
        model="test",
        usage=_usage(),
        stop_reason=StopReason.ToolUse if tool_calls else StopReason.Stop,
        timestamp=0,
    )


class _EchoParams(BaseModel):
    text: str = ""


async def _echo_execute(
    tool_call_id: str, params: _EchoParams, signal: asyncio.Event
) -> AgentToolResult[Any]:
    return AgentToolResult(
        result=[TextContent(type="text", text=params.text)],
        details=None,
    )


def _echo_tool() -> AgentTool[_EchoParams, Any]:
    return DefaultAgentTool("echo", "echo the text back", _EchoParams, _echo_execute)


def _tools(*tools: AgentTool[Any, Any]) -> list[AgentTool[BaseModel, Any]]:
    """Upcast a heterogeneous tool list to the loop's invariant field type."""
    return cast("list[AgentTool[BaseModel, Any]]", list(tools))


class _FakeController:
    """Duck-typed stand-in for the two methods ``AgentLoop`` calls."""

    def __init__(self, responses: list[AssistantMessage]) -> None:
        self._responses = list(responses)
        self.add_calls: list[AddUserMessage | AddToolResultMessage] = []
        self.generate_calls: int = 0

    async def add_message(
        self, message: AddUserMessage | AddToolResultMessage
    ) -> UserContextItem | ToolResultContextItem:
        self.add_calls.append(message)
        n = len(self.add_calls)
        if isinstance(message, AddUserMessage):
            return UserContextItem(id=f"u{n}", message=message.message)
        return ToolResultContextItem(id=f"t{n}", message=message.message)

    async def generate(self) -> AssistantContextItem:
        self.generate_calls += 1
        assert self._responses, "FakeController.generate called more times than scripted"
        return AssistantContextItem(id=f"a{self.generate_calls}", message=self._responses.pop(0))


def _build(
    fake: _FakeController,
    *,
    tools: list[AgentTool[BaseModel, Any]] | None = None,
    tool_exec_mode: ToolExecMode = ToolExecMode.SEQUENTIAL,
    max_turns: int | None = None,
    follow_ups: list[UserMessage] | None = None,
    steering: list[UserMessage] | None = None,
    follow_up_mode: QueueMode = QueueMode.ALL_AT_ONCE,
    steering_mode: QueueMode = QueueMode.ALL_AT_ONCE,
) -> AgentLoop:
    loop = AgentLoop(
        _controller=cast(ModelController, fake),
        _follow_up_mode=follow_up_mode,
        _steering_mode=steering_mode,
        _tools=tools or [],
        _tool_exec_mode=tool_exec_mode,
        _max_turns=max_turns,
    )
    for msg in follow_ups or []:
        loop.follow_up(msg)
    for msg in steering or []:
        loop.steer(msg)
    return loop


async def _await(loop: AgentLoop) -> None:
    """Await the loop's run task (always set by ``__post_init__``)."""
    assert loop._task is not None
    await loop._task


def _tool_result_adds(fake: _FakeController) -> list[AddToolResultMessage]:
    return [c for c in fake.add_calls if isinstance(c, AddToolResultMessage)]


def _user_adds(fake: _FakeController) -> list[AddUserMessage]:
    return [c for c in fake.add_calls if isinstance(c, AddUserMessage)]


# --------------------------------------------------------------------------- #
# Turn/tool cycle
# --------------------------------------------------------------------------- #


async def test_stops_when_no_tool_calls() -> None:
    fake = _FakeController([_assistant_message()])

    loop = _build(fake, follow_ups=[_user_message()])
    await _await(loop)

    assert fake.generate_calls == 1
    assert len(_user_adds(fake)) == 1  # the follow-up only
    assert _tool_result_adds(fake) == []


async def test_executes_tool_then_stops() -> None:
    fake = _FakeController(
        [_assistant_message([_tool_call("echo", arguments={"text": "ping"})]), _assistant_message()]
    )

    loop = _build(fake, tools=_tools(_echo_tool()), follow_ups=[_user_message()])
    await _await(loop)

    assert fake.generate_calls == 2
    results = _tool_result_adds(fake)
    assert len(results) == 1
    assert results[0].message.tool_name == "echo"
    assert results[0].message.is_error is False
    # The follow-up user message precedes the tool result.
    assert isinstance(fake.add_calls[0], AddUserMessage)
    assert fake.add_calls[1] is results[0]


async def test_unknown_tool_synthesizes_error_listing_available() -> None:
    fake = _FakeController([_assistant_message([_tool_call("nope")]), _assistant_message()])

    loop = _build(fake, tools=_tools(_echo_tool()), follow_ups=[_user_message()])
    await _await(loop)

    # The loop continues after the synthesized error result -> 2 generates.
    assert fake.generate_calls == 2
    results = _tool_result_adds(fake)
    assert len(results) == 1
    msg = results[0].message
    assert msg.is_error is True
    assert msg.tool_call_id == "c1"
    text = msg.content[0]
    assert isinstance(text, TextContent)
    assert "Unknown tool 'nope'" in text.text
    assert "echo" in text.text  # available tool is named


async def test_terminate_stops_loop() -> None:
    class _P(BaseModel):
        pass

    async def execute(tool_call_id: str, params: _P, signal: asyncio.Event) -> AgentToolResult[Any]:
        return AgentToolResult(
            result=[TextContent(type="text", text="done")], details=None, terminate=True
        )

    tool = DefaultAgentTool("stopping", "terminate the loop", _P, execute)
    fake = _FakeController([_assistant_message([_tool_call("stopping")])])

    loop = _build(fake, tools=_tools(tool), follow_ups=[_user_message()])
    await _await(loop)

    assert fake.generate_calls == 1  # no second generate despite a tool call
    assert len(_tool_result_adds(fake)) == 1


async def test_is_error_propagates_to_tool_result() -> None:
    class _P(BaseModel):
        pass

    async def execute(tool_call_id: str, params: _P, signal: asyncio.Event) -> AgentToolResult[Any]:
        return AgentToolResult(
            result=[TextContent(type="text", text="boom")], details=None, is_error=True
        )

    tool = DefaultAgentTool("failing", "always errors", _P, execute)
    fake = _FakeController([_assistant_message([_tool_call("failing")]), _assistant_message()])

    loop = _build(fake, tools=_tools(tool), follow_ups=[_user_message()])
    await _await(loop)

    results = _tool_result_adds(fake)
    assert len(results) == 1
    assert results[0].message.is_error is True


async def test_max_turns_caps_completed_turns_without_dropping_tools() -> None:
    fake = _FakeController(
        [
            _assistant_message([_tool_call("echo", arguments={"text": "a"})]),
            _assistant_message([_tool_call("echo", arguments={"text": "b"})]),
        ]
    )

    loop = _build(
        fake,
        tools=_tools(_echo_tool()),
        max_turns=2,
        follow_ups=[_user_message()],
    )
    await _await(loop)

    # Both turns completed (generate + tool results) before the cap stops us.
    assert fake.generate_calls == 2
    assert len(_tool_result_adds(fake)) == 2


async def test_max_turns_one_executes_tool_calls_without_dropping() -> None:
    fake = _FakeController([_assistant_message([_tool_call("echo", arguments={"text": "only"})])])

    loop = _build(
        fake,
        tools=_tools(_echo_tool()),
        max_turns=1,
        follow_ups=[_user_message()],
    )
    await _await(loop)

    assert fake.generate_calls == 1
    # The single turn's tool call was executed and its result added (not dropped).
    results = _tool_result_adds(fake)
    assert len(results) == 1
    assert results[0].message.tool_name == "echo"


async def test_abort_between_turns_stops_loop() -> None:
    class _P(BaseModel):
        pass

    async def execute(tool_call_id: str, params: _P, signal: asyncio.Event) -> AgentToolResult[Any]:
        # The signal passed in IS the loop's _abort_signal; setting it here
        # is honoured at the following turn boundary.
        signal.set()
        return AgentToolResult(result=[TextContent(type="text", text="ok")], details=None)

    tool = DefaultAgentTool("aborter", "sets the abort signal", _P, execute)
    fake = _FakeController([_assistant_message([_tool_call("aborter")]), _assistant_message()])

    loop = _build(fake, tools=_tools(tool), follow_ups=[_user_message()])
    with pytest.raises(asyncio.CancelledError):
        await _await(loop)

    assert fake.generate_calls == 1  # stopped before the second generate


async def test_abort_preset_before_first_turn_stops_after_turn() -> None:
    fake = _FakeController(
        [_assistant_message([_tool_call("echo", arguments={"text": "x"})]), _assistant_message()]
    )

    loop = _build(fake, tools=_tools(_echo_tool()), follow_ups=[_user_message()])
    loop._abort_signal.set()  # pre-set before the run task gets CPU

    with pytest.raises(asyncio.CancelledError):
        await _await(loop)

    # The first turn still ran to completion (generate + tool result) before
    # the abort fired at the turn boundary.
    assert fake.generate_calls == 1
    assert len(_tool_result_adds(fake)) == 1


# --------------------------------------------------------------------------- #
# ToolExecMode
# --------------------------------------------------------------------------- #


def _make_overlap_tracker_tool(name: str, tracker: dict[str, int]) -> AgentTool[Any, Any]:
    class _P(BaseModel):
        pass

    async def execute(tool_call_id: str, params: _P, signal: asyncio.Event) -> AgentToolResult[Any]:
        tracker["active"] += 1
        tracker["peak"] = max(tracker["peak"], tracker["active"])
        await asyncio.sleep(0)  # yield so a sibling can overlap
        tracker["active"] -= 1
        return AgentToolResult(result=[TextContent(type="text", text="ok")], details=None)

    return DefaultAgentTool(name, "records concurrency", _P, execute)


async def test_concurrent_mode_overlaps_executions() -> None:
    tracker: dict[str, int] = {"active": 0, "peak": 0}
    tool = _make_overlap_tracker_tool("track", tracker)
    fake = _FakeController(
        [
            _assistant_message([_tool_call("track", id="c1"), _tool_call("track", id="c2")]),
            _assistant_message(),
        ]
    )

    loop = _build(
        fake,
        tools=_tools(tool),
        tool_exec_mode=ToolExecMode.CONCURRENT,
        follow_ups=[_user_message()],
    )
    await _await(loop)

    assert tracker["peak"] == 2


async def test_sequential_mode_does_not_overlap() -> None:
    tracker: dict[str, int] = {"active": 0, "peak": 0}
    tool = _make_overlap_tracker_tool("track", tracker)
    fake = _FakeController(
        [
            _assistant_message([_tool_call("track", id="c1"), _tool_call("track", id="c2")]),
            _assistant_message(),
        ]
    )

    loop = _build(
        fake,
        tools=_tools(tool),
        tool_exec_mode=ToolExecMode.SEQUENTIAL,
        follow_ups=[_user_message()],
    )
    await _await(loop)

    assert tracker["peak"] == 1


# --------------------------------------------------------------------------- #
# Steering & follow-ups
# --------------------------------------------------------------------------- #


async def test_steering_injected_before_first_generate() -> None:
    fake = _FakeController([_assistant_message([_tool_call("echo")]), _assistant_message()])

    loop = _build(
        fake,
        tools=_tools(_echo_tool()),
        follow_ups=[_user_message("prompt")],
        steering=[_user_message("steer!")],
    )
    await _await(loop)

    # Order: follow-up user add, steering user add, then generate (tool result).
    assert isinstance(fake.add_calls[0], AddUserMessage)
    assert isinstance(fake.add_calls[1], AddUserMessage)
    assert fake.add_calls[0].message.content == "prompt"
    assert fake.add_calls[1].message.content == "steer!"
    assert fake.generate_calls == 2


async def test_follow_ups_drive_multiple_inner_loops() -> None:
    fake = _FakeController([_assistant_message(), _assistant_message()])

    loop = _build(
        fake,
        follow_ups=[_user_message("first"), _user_message("second")],
        follow_up_mode=QueueMode.ONE_BY_ONE,
    )
    await _await(loop)

    assert fake.generate_calls == 2  # one inner loop (one generate) per follow-up
    assert len(_user_adds(fake)) == 2


async def test_follow_up_before_await_starts_loop() -> None:
    # The run task scheduled in __post_init__ does not start until the first
    # await, so follow_up() called synchronously after construction reaches the
    # queue before _run_outer_loop's ``while not empty`` check runs.
    fake = _FakeController([_assistant_message()])

    loop = _build(fake)  # no follow-ups at construction
    loop.follow_up(_user_message())
    await _await(loop)

    assert fake.generate_calls == 1
    assert len(_user_adds(fake)) == 1


async def test_follow_up_raises_after_run_task_done() -> None:
    loop = _build(_FakeController([_assistant_message()]), follow_ups=[_user_message()])
    await _await(loop)

    with pytest.raises(RuntimeError):
        loop.follow_up(_user_message())


async def test_steer_raises_after_run_task_done() -> None:
    loop = _build(_FakeController([_assistant_message()]), follow_ups=[_user_message()])
    await _await(loop)

    with pytest.raises(RuntimeError):
        loop.steer(_user_message())


# --------------------------------------------------------------------------- #
# HookRunner surface
# --------------------------------------------------------------------------- #


async def test_hook_runner_property_returns_a_hook_runner() -> None:
    loop = _build(_FakeController([_assistant_message()]), follow_ups=[_user_message()])
    await _await(loop)

    assert isinstance(loop.hook_runner, HookRunner)


async def test_each_loop_gets_an_independent_hook_runner() -> None:
    loop_a = _build(_FakeController([_assistant_message()]), follow_ups=[_user_message()])
    loop_b = _build(_FakeController([_assistant_message()]), follow_ups=[_user_message()])

    async def handler(ping: _Ping) -> _Pong:
        return _Pong(echoed=ping.msg)

    loop_a.on(_PING, handler)
    await _await(loop_a)
    await _await(loop_b)

    # Registering on loop A must not be visible on loop B (default_factory
    # gives each loop its own runner).
    assert await loop_a.hook_runner.emit(_PING, _Ping(msg="hi")) == _Pong(echoed="hi")
    assert await loop_b.hook_runner.emit(_PING, _Ping(msg="hi")) is None


async def test_on_registers_handler_observed_via_emit() -> None:
    loop = _build(_FakeController([_assistant_message()]), follow_ups=[_user_message()])

    async def handler(ping: _Ping) -> _Pong:
        return _Pong(echoed=ping.msg.upper())

    unsub = loop.on(_PING, handler)
    await _await(loop)

    assert await loop.hook_runner.emit(_PING, _Ping(msg="hi")) == _Pong(echoed="HI")

    unsub()
    assert await loop.hook_runner.emit(_PING, _Ping(msg="hi")) is None


async def test_on_unsubscribe_is_idempotent() -> None:
    loop = _build(_FakeController([_assistant_message()]), follow_ups=[_user_message()])

    async def handler(ping: _Ping) -> _Pong:
        return _Pong(echoed=ping.msg)

    unsub = loop.on(_PING, handler)
    await _await(loop)

    unsub()
    unsub()  # second call is a no-op, must not raise

    assert await loop.hook_runner.emit(_PING, _Ping(msg="hi")) is None


# --------------------------------------------------------------------------- #
# before_tool_call hook
# --------------------------------------------------------------------------- #


async def test_before_tool_call_receives_each_tool_call() -> None:
    fake = _FakeController(
        [
            _assistant_message(
                [
                    _tool_call("echo", id="c1", arguments={"text": "a"}),
                    _tool_call("echo", id="c2", arguments={"text": "b"}),
                ]
            ),
            _assistant_message(),
        ]
    )
    loop = _build(fake, tools=_tools(_echo_tool()), follow_ups=[_user_message()])

    seen: list[ToolCall] = []

    async def handler(call: ToolCall) -> AgentToolResult[Any] | None:
        seen.append(call)
        return None  # defer to normal execution

    loop.on(BEFORE_TOOL_CALL, handler)
    await _await(loop)

    # The handler saw both calls with their id / name / arguments.
    assert [c.id for c in seen] == ["c1", "c2"]
    assert [c.name for c in seen] == ["echo", "echo"]
    assert [c.arguments for c in seen] == [{"text": "a"}, {"text": "b"}]

    # Deferred to normal execution: both tools ran and fed results back.
    assert fake.generate_calls == 2
    assert len(_tool_result_adds(fake)) == 2


async def test_before_tool_call_none_defers_to_execution() -> None:
    executed: list[str] = []

    class _P(BaseModel):
        text: str = ""

    async def execute(tool_call_id: str, params: _P, signal: asyncio.Event) -> AgentToolResult[Any]:
        executed.append(params.text)
        return AgentToolResult(result=[TextContent(type="text", text=params.text)], details=None)

    tool = DefaultAgentTool("echo", "echo back", _P, execute)
    fake = _FakeController(
        [_assistant_message([_tool_call("echo", arguments={"text": "hi"})]), _assistant_message()]
    )
    loop = _build(fake, tools=_tools(tool), follow_ups=[_user_message()])

    async def handler(call: ToolCall) -> AgentToolResult[Any] | None:
        return None

    loop.on(BEFORE_TOOL_CALL, handler)
    await _await(loop)

    assert executed == ["hi"]  # the tool's execute() actually ran
    results = _tool_result_adds(fake)
    assert len(results) == 1
    text = results[0].message.content[0]
    assert isinstance(text, TextContent)
    assert text.text == "hi"


async def test_before_tool_call_short_circuits_execution() -> None:
    executed: list[str] = []

    class _P(BaseModel):
        text: str = ""

    async def execute(tool_call_id: str, params: _P, signal: asyncio.Event) -> AgentToolResult[Any]:
        executed.append("should-not-run")
        return AgentToolResult(result=[TextContent(type="text", text=params.text)], details=None)

    tool = DefaultAgentTool("echo", "echo back", _P, execute)
    fake = _FakeController(
        [
            _assistant_message([_tool_call("echo", id="c1", arguments={"text": "real"})]),
            _assistant_message(),
        ]
    )
    loop = _build(fake, tools=_tools(tool), follow_ups=[_user_message()])

    async def handler(call: ToolCall) -> AgentToolResult[Any]:
        # Substitute a different result; the tool must not run.
        return AgentToolResult(
            result=[TextContent(type="text", text="intercepted")],
            details={"from": "hook"},
            is_error=False,
        )

    loop.on(BEFORE_TOOL_CALL, handler)
    await _await(loop)

    assert executed == []  # execute() was never called
    results = _tool_result_adds(fake)
    assert len(results) == 1
    msg = results[0].message
    # content / details / is_error come from the hook result...
    text = msg.content[0]
    assert isinstance(text, TextContent)
    assert text.text == "intercepted"
    assert msg.details == {"from": "hook"}
    assert msg.is_error is False
    # ...but tool_call_id / tool_name still come from the call.
    assert msg.tool_call_id == "c1"
    assert msg.tool_name == "echo"


async def test_before_tool_call_terminate_terminates_loop() -> None:
    executed: list[str] = []

    class _P(BaseModel):
        pass

    async def execute(tool_call_id: str, params: _P, signal: asyncio.Event) -> AgentToolResult[Any]:
        executed.append("should-not-run")
        return AgentToolResult(result=[TextContent(type="text", text="x")], details=None)

    tool = DefaultAgentTool("stoppable", "stoppable", _P, execute)
    fake = _FakeController([_assistant_message([_tool_call("stoppable")])])
    loop = _build(fake, tools=_tools(tool), follow_ups=[_user_message()])

    async def handler(call: ToolCall) -> AgentToolResult[Any]:
        return AgentToolResult(
            result=[TextContent(type="text", text="done")], details=None, terminate=True
        )

    loop.on(BEFORE_TOOL_CALL, handler)
    await _await(loop)

    assert fake.generate_calls == 1  # no second generate despite a tool call
    assert executed == []  # tool not executed
    assert len(_tool_result_adds(fake)) == 1  # result still fed back to the model


async def test_before_tool_call_fires_for_unknown_tool_returning_none() -> None:
    # Handler defers -> the existing unknown-tool synthesis proceeds.
    fake = _FakeController([_assistant_message([_tool_call("nope")]), _assistant_message()])
    loop = _build(fake, tools=_tools(_echo_tool()), follow_ups=[_user_message()])

    async def handler(call: ToolCall) -> AgentToolResult[Any] | None:
        return None

    loop.on(BEFORE_TOOL_CALL, handler)
    await _await(loop)

    results = _tool_result_adds(fake)
    assert len(results) == 1
    msg = results[0].message
    assert msg.is_error is True  # synthesized unknown-tool error
    text = msg.content[0]
    assert isinstance(text, TextContent)
    assert "Unknown tool 'nope'" in text.text


async def test_before_tool_call_short_circuits_unknown_tool() -> None:
    # Handler returns a result for an unknown tool -> synthesis is skipped and
    # the hook result is used instead.
    fake = _FakeController(
        [_assistant_message([_tool_call("nope", id="c9")]), _assistant_message()]
    )
    loop = _build(fake, tools=_tools(_echo_tool()), follow_ups=[_user_message()])

    async def handler(call: ToolCall) -> AgentToolResult[Any]:
        return AgentToolResult(
            result=[TextContent(type="text", text="handled-anyway")], details=None
        )

    loop.on(BEFORE_TOOL_CALL, handler)
    await _await(loop)

    results = _tool_result_adds(fake)
    assert len(results) == 1
    msg = results[0].message
    assert msg.is_error is False  # not the synthesized unknown-tool error
    assert msg.tool_call_id == "c9"
    text = msg.content[0]
    assert isinstance(text, TextContent)
    assert text.text == "handled-anyway"


async def test_before_tool_call_fires_per_call_in_concurrent_mode() -> None:
    seen: list[str] = []
    fake = _FakeController(
        [
            _assistant_message([_tool_call("echo", id="c1"), _tool_call("echo", id="c2")]),
            _assistant_message(),
        ]
    )
    loop = _build(
        fake,
        tools=_tools(_echo_tool()),
        tool_exec_mode=ToolExecMode.CONCURRENT,
        follow_ups=[_user_message()],
    )

    async def handler(call: ToolCall) -> AgentToolResult[Any] | None:
        seen.append(call.id)
        return None

    loop.on(BEFORE_TOOL_CALL, handler)
    await _await(loop)

    assert sorted(seen) == ["c1", "c2"]  # fired once per call (order not guaranteed)


# --------------------------------------------------------------------------- #
# tool_result hook
# --------------------------------------------------------------------------- #


async def test_tool_result_receives_call_and_executed_result() -> None:
    fake = _FakeController(
        [
            _assistant_message([_tool_call("echo", id="c1", arguments={"text": "hi"})]),
            _assistant_message(),
        ]
    )
    loop = _build(fake, tools=_tools(_echo_tool()), follow_ups=[_user_message()])

    seen: list[ToolResultHookParams] = []

    async def handler(params: ToolResultHookParams) -> AgentToolResult[Any] | None:
        seen.append(params)
        return None  # defer to the executed result

    loop.on(TOOL_RESULT, handler)
    await _await(loop)

    # The handler saw the call (id/name/args) and the executed result (content).
    assert len(seen) == 1
    assert seen[0].tool_call.id == "c1"
    assert seen[0].tool_call.name == "echo"
    assert seen[0].tool_call.arguments == {"text": "hi"}
    assert seen[0].result.is_error is False
    text = seen[0].result.result[0]
    assert isinstance(text, TextContent)
    assert text.text == "hi"  # the echo tool's execute() output


async def test_tool_result_none_persists_original_result() -> None:
    fake = _FakeController(
        [
            _assistant_message([_tool_call("echo", id="c1", arguments={"text": "real"})]),
            _assistant_message(),
        ]
    )
    loop = _build(fake, tools=_tools(_echo_tool()), follow_ups=[_user_message()])

    async def handler(params: ToolResultHookParams) -> AgentToolResult[Any] | None:
        return None  # persist the original

    loop.on(TOOL_RESULT, handler)
    await _await(loop)

    results = _tool_result_adds(fake)
    assert len(results) == 1
    msg = results[0].message
    assert msg.is_error is False
    text = msg.content[0]
    assert isinstance(text, TextContent)
    assert text.text == "real"  # the executed result, unchanged
    assert msg.tool_call_id == "c1"
    assert msg.tool_name == "echo"


async def test_tool_result_override_replaces_result() -> None:
    fake = _FakeController(
        [
            _assistant_message([_tool_call("echo", id="c1", arguments={"text": "real"})]),
            _assistant_message(),
        ]
    )
    loop = _build(fake, tools=_tools(_echo_tool()), follow_ups=[_user_message()])

    async def handler(params: ToolResultHookParams) -> AgentToolResult[Any]:
        # Replace the executed result wholesale.
        return AgentToolResult(
            result=[TextContent(type="text", text="overridden")],
            details={"from": "tool_result_hook"},
            is_error=True,
        )

    loop.on(TOOL_RESULT, handler)
    await _await(loop)

    results = _tool_result_adds(fake)
    assert len(results) == 1
    msg = results[0].message
    # content / details / is_error come from the override...
    text = msg.content[0]
    assert isinstance(text, TextContent)
    assert text.text == "overridden"
    assert msg.details == {"from": "tool_result_hook"}
    assert msg.is_error is True
    # ...but tool_call_id / tool_name still come from the call.
    assert msg.tool_call_id == "c1"
    assert msg.tool_name == "echo"


async def test_tool_result_override_terminate_terminates_loop() -> None:
    fake = _FakeController(
        [
            _assistant_message([_tool_call("echo", id="c1", arguments={"text": "x"})]),
            _assistant_message(),
        ]
    )
    loop = _build(fake, tools=_tools(_echo_tool()), follow_ups=[_user_message()])

    async def handler(params: ToolResultHookParams) -> AgentToolResult[Any]:
        return AgentToolResult(
            result=[TextContent(type="text", text="done")], details=None, terminate=True
        )

    loop.on(TOOL_RESULT, handler)
    await _await(loop)

    assert fake.generate_calls == 1  # override's terminate stopped the loop
    assert len(_tool_result_adds(fake)) == 1  # result still fed back to the model


async def test_tool_result_not_fired_when_before_tool_call_intercepts() -> None:
    executed: list[str] = []

    class _P(BaseModel):
        text: str = ""

    async def execute(tool_call_id: str, params: _P, signal: asyncio.Event) -> AgentToolResult[Any]:
        executed.append("should-not-run")
        return AgentToolResult(result=[TextContent(type="text", text=params.text)], details=None)

    tool = DefaultAgentTool("echo", "echo back", _P, execute)
    fake = _FakeController(
        [
            _assistant_message([_tool_call("echo", id="c1", arguments={"text": "real"})]),
            _assistant_message(),
        ]
    )
    loop = _build(fake, tools=_tools(tool), follow_ups=[_user_message()])

    seen: list[ToolResultHookParams] = []

    async def before(call: ToolCall) -> AgentToolResult[Any]:
        # Short-circuit before execution; the tool never runs.
        return AgentToolResult(result=[TextContent(type="text", text="intercepted")], details=None)

    async def after(params: ToolResultHookParams) -> AgentToolResult[Any] | None:
        seen.append(params)
        return None

    loop.on(BEFORE_TOOL_CALL, before)
    loop.on(TOOL_RESULT, after)
    await _await(loop)

    assert executed == []  # tool never executed
    assert seen == []  # tool_result did not fire (tool never ran)


async def test_tool_result_not_fired_for_unknown_tool() -> None:
    fake = _FakeController([_assistant_message([_tool_call("nope")]), _assistant_message()])
    loop = _build(fake, tools=_tools(_echo_tool()), follow_ups=[_user_message()])

    seen: list[ToolResultHookParams] = []

    async def handler(params: ToolResultHookParams) -> AgentToolResult[Any] | None:
        seen.append(params)
        return None

    loop.on(TOOL_RESULT, handler)
    await _await(loop)

    # tool_result did not fire (no tool ran); synthesized error still fed back.
    assert seen == []
    results = _tool_result_adds(fake)
    assert len(results) == 1
    msg = results[0].message
    assert msg.is_error is True
    text = msg.content[0]
    assert isinstance(text, TextContent)
    assert "Unknown tool 'nope'" in text.text


async def test_tool_result_fires_per_call_in_concurrent_mode() -> None:
    fake = _FakeController(
        [
            _assistant_message(
                [
                    _tool_call("echo", id="c1", arguments={"text": "a"}),
                    _tool_call("echo", id="c2", arguments={"text": "b"}),
                ]
            ),
            _assistant_message(),
        ]
    )
    loop = _build(
        fake,
        tools=_tools(_echo_tool()),
        tool_exec_mode=ToolExecMode.CONCURRENT,
        follow_ups=[_user_message()],
    )

    seen: list[str] = []

    async def handler(params: ToolResultHookParams) -> AgentToolResult[Any] | None:
        seen.append(params.tool_call.id)
        return None

    loop.on(TOOL_RESULT, handler)
    await _await(loop)

    assert sorted(seen) == ["c1", "c2"]  # fired once per executed call
