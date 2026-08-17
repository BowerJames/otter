from collections.abc import Callable
from types import TracebackType
from typing import Any, Self

import pytest
from pydantic import BaseModel

from otter_ai_core.agent_loop import (
    AgentLoop,
    AgentLoopExhausted,
    AgentLoopHooks,
    AgentLoopOptions,
    AgentLoopStranded,
    AgentLoopTurn,
    ToolCallDecision,
    ToolExecution,
)
from otter_ai_core.agent_tool import AgentToolResult, create_agent_tool
from otter_ai_core.conversation import (
    AssistantMessage,
    SessionMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from otter_ai_core.model import Model
from otter_ai_core.model.fake import FakeModel


def response(
    id: str, text: str | None = None, tool_calls: list[ToolCall] | None = None
) -> AssistantMessage:
    calls = tool_calls or []
    if text is None and not calls:
        raise ValueError("scripted response needs text or tool_calls")
    return AssistantMessage(
        id=id,
        content=[TextContent(text=text)] if text is not None else [],
        tool_calls=calls,
        stop_reason="tool_call" if calls else "final_response",
    )


async def collect_turns(loop: AgentLoop) -> list[AgentLoopTurn]:
    return [event async for event in loop if isinstance(event, AgentLoopTurn)]


class TimeParams(BaseModel):
    pass


class EchoParams(BaseModel):
    payload: str


class AddParams(BaseModel):
    a: int
    b: int


class FailParams(BaseModel):
    pass


class StopParams(BaseModel):
    stop: bool


class OkParams(BaseModel):
    pass


class ProbeParams(BaseModel):
    n: int


class StampParams(BaseModel):
    pass


class ReportParams(BaseModel):
    pass


class PingParams(BaseModel):
    pass


class NoteParams(BaseModel):
    pass


class CountParams(BaseModel):
    pass


class _SteerOnGenerate:
    def __init__(self, inner: Model, steer: Callable[[str], None]) -> None:
        self._inner = inner
        self._steer = steer
        self._armed = True

    async def __aenter__(self) -> Self:
        await self._inner.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._inner.__aexit__(exc_type, exc_value, traceback)

    async def add_user_message(self, text: str) -> UserMessage:
        return await self._inner.add_user_message(text)

    async def add_tool_result_message(self, tool_call_id: str, text: str) -> ToolResultMessage:
        return await self._inner.add_tool_result_message(tool_call_id, text)

    async def generate(self) -> AssistantMessage:
        if self._armed:
            self._armed = False
            self._steer("too late")
        return await self._inner.generate()


class BoomModel:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> Self:
        self.entered = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exited = True

    async def add_user_message(self, text: str) -> UserMessage:
        raise RuntimeError("provider 500")

    async def add_tool_result_message(self, tool_call_id: str, text: str) -> ToolResultMessage:
        raise AssertionError("not reached")

    async def generate(self) -> AssistantMessage:
        raise AssertionError("not reached")


async def test_single_text_turn() -> None:
    model = FakeModel([response("a1", text="hello there")])
    async with model:
        loop = AgentLoop(model)
        loop.follow_up("hi")

        turns = await collect_turns(loop)

    assert len(turns) == 1
    turn = turns[0]
    assert turn.termination == "final_response"
    assert turn.generations == 1
    assert turn.tool_executions == []
    assert turn.assistant_message.id == "a1"
    assert turn.assistant_message.content[0].text == "hello there"
    assert [type(m) for m in turn.messages] == [UserMessage, AssistantMessage]
    assert turn.messages[0].content[0].text == "hi"
    assert turn.messages[-1] == turn.assistant_message
    assert [type(m) for m in model.history] == [UserMessage, AssistantMessage]


async def test_aiter_is_single_use() -> None:
    fresh_model = FakeModel([])
    fresh = AgentLoop(fresh_model)
    aiter(fresh)
    with pytest.raises(RuntimeError, match="single-use"):
        aiter(fresh)

    finished_model = FakeModel([response("a1", text="hi")])
    async with finished_model:
        finished = AgentLoop(finished_model)
        finished.follow_up("hello")
        async for _ in finished:
            pass
        with pytest.raises(RuntimeError, match="single-use"):
            aiter(finished)


async def test_input_methods_rejected_after_run_finishes() -> None:
    model = FakeModel([response("a1", text="hi")])
    async with model:
        loop = AgentLoop(model)
        loop.follow_up("hello")
        async for _ in loop:
            pass

        with pytest.raises(RuntimeError, match="finished"):
            loop.follow_up("late")
        with pytest.raises(RuntimeError, match="finished"):
            loop.steer("late")


async def test_turn_messages_concatenate_to_model_history() -> None:
    loop_ref: list[AgentLoop] = []

    async def get_time(_: TimeParams) -> AgentToolResult:
        loop_ref[0].steer("say it in UTC")
        return AgentToolResult(text="12:00")

    tool = create_agent_tool("get_time", "returns the time", TimeParams, get_time)
    model = FakeModel(
        [
            response(
                "a1",
                text="checking",
                tool_calls=[ToolCall(id="c1", tool_name="get_time", parameters={})],
            ),
            response("a2", text="it is 12:00"),
            response("a3", text="you're welcome"),
        ]
    )
    async with model:
        loop = AgentLoop(model, tools=[tool])
        loop_ref.append(loop)
        loop.follow_up("what time is it?")
        loop.follow_up("thanks")

        turns = await collect_turns(loop)

    flat = [message for turn in turns for message in turn.messages]
    assert flat == list(model.history)
    assert [type(m) for m in turns[0].messages] == [
        UserMessage,
        AssistantMessage,
        ToolResultMessage,
        UserMessage,
        AssistantMessage,
    ]
    assert [type(m) for m in turns[1].messages] == [UserMessage, AssistantMessage]
    assert turns[0].messages[3].content[0].text == "say it in UTC"


async def test_tool_call_round_trip() -> None:
    received: list[dict[str, Any]] = []

    async def echo(params: EchoParams) -> AgentToolResult:
        received.append(params.model_dump())
        return AgentToolResult(text=f"echo:{params.payload}")

    tool = create_agent_tool("echo", "echoes the payload back", EchoParams, echo)
    model = FakeModel(
        [
            response(
                "a1",
                text="checking",
                tool_calls=[
                    ToolCall(id="c1", tool_name="echo", parameters={"payload": "hello"}),
                ],
            ),
            response("a2", text="done"),
        ]
    )
    async with model:
        loop = AgentLoop(model, tools=[tool])
        loop.follow_up("run the tool")

        turns = await collect_turns(loop)

    turn = turns[0]
    assert received == [{"payload": "hello"}]
    assert turn.tool_executions == [
        ToolExecution(
            tool_call_id="c1", tool_name="echo", result=AgentToolResult(text="echo:hello")
        )
    ]
    assert turn.generations == 2
    assert turn.termination == "final_response"
    feedback = model.history[2]
    assert isinstance(feedback, ToolResultMessage)
    assert feedback.tool_call_id == "c1"
    assert feedback.content[0].text == "echo:hello"


async def test_multiple_tool_calls_in_one_turn() -> None:
    calls: list[str] = []

    async def add(params: AddParams) -> AgentToolResult:
        calls.append(f"{params.a}+{params.b}")
        return AgentToolResult(text=str(params.a + params.b))

    tool = create_agent_tool("add", "adds two integers", AddParams, add)
    model = FakeModel(
        [
            response(
                "a1",
                text="running two",
                tool_calls=[
                    ToolCall(id="c1", tool_name="add", parameters={"a": 2, "b": 3}),
                    ToolCall(id="c2", tool_name="add", parameters={"a": 10, "b": 20}),
                ],
            ),
            response("a2", text="done"),
        ]
    )
    async with model:
        loop = AgentLoop(model, tools=[tool])
        loop.follow_up("add twice")

        turns = await collect_turns(loop)

    turn = turns[0]
    assert calls == ["2+3", "10+20"]
    assert [execution.tool_call_id for execution in turn.tool_executions] == ["c1", "c2"]
    assert [execution.result.text for execution in turn.tool_executions] == ["5", "30"]
    assert [m.tool_call_id for m in turn.messages if isinstance(m, ToolResultMessage)] == [
        "c1",
        "c2",
    ]
    assert turn.termination == "final_response"


async def test_unknown_tool_synthesizes_error_result() -> None:
    model = FakeModel(
        [
            response(
                "a1",
                text="trying",
                tool_calls=[ToolCall(id="c1", tool_name="nonexistent", parameters={})],
            ),
            response("a2", text="gave up gracefully"),
        ]
    )
    async with model:
        loop = AgentLoop(model)
        loop.follow_up("use the mystery tool")

        turns = await collect_turns(loop)

    turn = turns[0]
    execution = turn.tool_executions[0]
    assert execution.tool_call_id == "c1"
    assert execution.tool_name == "nonexistent"
    assert execution.result.is_error is True
    assert "nonexistent" in execution.result.text

    feedback = model.history[2]
    assert isinstance(feedback, ToolResultMessage)
    assert feedback.tool_call_id == "c1"
    assert feedback.content[0].text == execution.result.text
    assert turn.termination == "final_response"


async def test_tool_exception_contained_as_error_result() -> None:
    async def explode(_: FailParams) -> AgentToolResult:
        raise RuntimeError("disk on fire")

    tool = create_agent_tool("explode", "always raises", FailParams, explode)
    model = FakeModel(
        [
            response(
                "a1",
                text="trying",
                tool_calls=[ToolCall(id="c1", tool_name="explode", parameters={})],
            ),
            response("a2", text="handled it"),
        ]
    )
    async with model:
        loop = AgentLoop(model, tools=[tool])
        loop.follow_up("trigger the failure")

        turns = await collect_turns(loop)

    turn = turns[0]
    execution = turn.tool_executions[0]
    assert execution.result.is_error is True
    assert "disk on fire" in execution.result.text

    feedback = model.history[2]
    assert isinstance(feedback, ToolResultMessage)
    assert feedback.tool_call_id == "c1"
    assert feedback.content[0].text == execution.result.text
    assert turn.termination == "final_response"


async def test_tool_terminate_ends_run_with_all_calls_answered() -> None:
    executed: list[dict[str, Any]] = []

    async def maybe_stop(params: StopParams) -> AgentToolResult:
        executed.append(params.model_dump())
        return AgentToolResult(
            text="stopping" if params.stop else "continuing", terminate=params.stop
        )

    tool = create_agent_tool("maybe_stop", "stops when asked", StopParams, maybe_stop)
    model = FakeModel(
        [
            response(
                "a1",
                text="running two",
                tool_calls=[
                    ToolCall(id="c1", tool_name="maybe_stop", parameters={"stop": True}),
                    ToolCall(id="c2", tool_name="maybe_stop", parameters={"stop": False}),
                ],
            ),
        ]
    )
    async with model:
        loop = AgentLoop(model, tools=[tool])
        loop.follow_up("try both")

        turns = await collect_turns(loop)

    turn = turns[0]
    assert executed == [{"stop": True}, {"stop": False}]
    assert turn.termination == "tool_terminated"
    assert turn.generations == 1
    assert [(e.tool_call_id, e.result.text) for e in turn.tool_executions] == [
        ("c1", "stopping"),
        ("c2", "continuing"),
    ]
    assert turn.tool_executions[0].result.terminate is True
    assert [m.tool_call_id for m in turn.messages if isinstance(m, ToolResultMessage)] == [
        "c1",
        "c2",
    ]


def test_duplicate_tool_names_rejected_at_construction() -> None:
    async def noop(_: OkParams) -> AgentToolResult:
        return AgentToolResult(text="ok")

    first = create_agent_tool("dup", "first variant", OkParams, noop)
    second = create_agent_tool("dup", "second variant", OkParams, noop)

    with pytest.raises(ValueError, match="dup"):
        AgentLoop(FakeModel([]), tools=[first, second])


async def test_before_tool_call_deny_skips_execution_and_informs_model() -> None:
    executed: list[int] = []

    async def probe(params: ProbeParams) -> AgentToolResult:
        executed.append(params.n)
        return AgentToolResult(text=f"probe {params.n} ran")

    tool = create_agent_tool("probe", "a probe", ProbeParams, probe)

    async def deny_first(call: ToolCall) -> ToolCallDecision:
        if call.id == "c1":
            return ToolCallDecision(action="deny", reason=f"denied {call.tool_name}")
        return ToolCallDecision(action="run")

    model = FakeModel(
        [
            response(
                "a1",
                text="trying",
                tool_calls=[
                    ToolCall(id="c1", tool_name="probe", parameters={"n": 1}),
                    ToolCall(id="c2", tool_name="probe", parameters={"n": 2}),
                ],
            ),
            response("a2", text="understood"),
        ]
    )
    async with model:
        loop = AgentLoop(model, tools=[tool], hooks=AgentLoopHooks(before_tool_call=deny_first))
        loop.follow_up("try both")

        turns = await collect_turns(loop)

    turn = turns[0]
    assert executed == [2]
    assert [(e.tool_call_id, e.result.is_error) for e in turn.tool_executions] == [
        ("c1", True),
        ("c2", False),
    ]
    assert "denied probe" in turn.tool_executions[0].result.text
    assert turn.tool_executions[1].result.text == "probe 2 ran"
    denied_feedback = model.history[2]
    assert isinstance(denied_feedback, ToolResultMessage)
    assert denied_feedback.tool_call_id == "c1"
    assert denied_feedback.content[0].text == turn.tool_executions[0].result.text
    assert turn.termination == "final_response"


async def test_before_tool_call_fires_for_unknown_tools() -> None:
    observed: list[str] = []

    async def observe(call: ToolCall) -> ToolCallDecision:
        observed.append(f"{call.id}:{call.tool_name}")
        return ToolCallDecision(action="run")

    model = FakeModel(
        [
            response(
                "a1",
                text="trying",
                tool_calls=[ToolCall(id="c1", tool_name="ghost", parameters={})],
            ),
            response("a2", text="understood"),
        ]
    )
    async with model:
        loop = AgentLoop(model, hooks=AgentLoopHooks(before_tool_call=observe))
        loop.follow_up("try it")

        turns = await collect_turns(loop)

    turn = turns[0]
    assert observed == ["c1:ghost"]
    assert turn.tool_executions[0].result.is_error is True
    assert "ghost" in turn.tool_executions[0].result.text
    assert turn.termination == "final_response"


async def test_tool_result_hook_rewrites_recorded_result() -> None:
    hook_inputs: list[tuple[str, str]] = []

    async def stamp(_: StampParams) -> AgentToolResult:
        return AgentToolResult(text="original")

    async def rewrite(call: ToolCall, result: AgentToolResult) -> AgentToolResult:
        hook_inputs.append((call.id, result.text))
        return result.model_copy(update={"text": "REWRITTEN"})

    tool = create_agent_tool("stamp", "returns a marker", StampParams, stamp)
    model = FakeModel(
        [
            response(
                "a1",
                text="trying",
                tool_calls=[ToolCall(id="c1", tool_name="stamp", parameters={})],
            ),
            response("a2", text="done"),
        ]
    )
    async with model:
        loop = AgentLoop(model, tools=[tool], hooks=AgentLoopHooks(tool_result=rewrite))
        loop.follow_up("go")

        turns = await collect_turns(loop)

    turn = turns[0]
    assert hook_inputs == [("c1", "original")]
    assert turn.tool_executions[0].result.text == "REWRITTEN"
    feedback = model.history[2]
    assert isinstance(feedback, ToolResultMessage)
    assert feedback.tool_call_id == "c1"
    assert feedback.content[0].text == "REWRITTEN"
    assert turn.termination == "final_response"


async def test_tool_result_hook_can_escalate_termination() -> None:
    async def report(_: ReportParams) -> AgentToolResult:
        return AgentToolResult(text="finished normally")

    async def escalate(call: ToolCall, result: AgentToolResult) -> AgentToolResult:
        return result.model_copy(update={"terminate": True})

    tool = create_agent_tool("report", "reports", ReportParams, report)
    model = FakeModel(
        [
            response(
                "a1",
                text="reporting",
                tool_calls=[ToolCall(id="c1", tool_name="report", parameters={})],
            ),
        ]
    )
    async with model:
        loop = AgentLoop(model, tools=[tool], hooks=AgentLoopHooks(tool_result=escalate))
        loop.follow_up("go")

        turns = await collect_turns(loop)

    turn = turns[0]
    assert turn.termination == "tool_terminated"
    assert turn.tool_executions[0].result.terminate is True
    assert turn.tool_executions[0].result.text == "finished normally"


async def test_hook_exceptions_propagate() -> None:
    async def ping(_: PingParams) -> AgentToolResult:
        return AgentToolResult(text="pong")

    tool = create_agent_tool("ping", "pings", PingParams, ping)
    script = [
        response(
            "a1", text="trying", tool_calls=[ToolCall(id="c1", tool_name="ping", parameters={})]
        ),
    ]

    async def before_boom(call: ToolCall) -> ToolCallDecision:
        raise RuntimeError("before hook exploded")

    first_model = FakeModel(script)
    async with first_model:
        first = AgentLoop(
            first_model, tools=[tool], hooks=AgentLoopHooks(before_tool_call=before_boom)
        )
        first.follow_up("go")
        with pytest.raises(RuntimeError, match="before hook exploded"):
            async for _ in first:
                pass

    async def result_boom(call: ToolCall, result: AgentToolResult) -> AgentToolResult:
        raise RuntimeError("result hook exploded")

    second_model = FakeModel(script)
    async with second_model:
        second = AgentLoop(
            second_model, tools=[tool], hooks=AgentLoopHooks(tool_result=result_boom)
        )
        second.follow_up("go")
        with pytest.raises(RuntimeError, match="result hook exploded"):
            async for _ in second:
                pass


async def test_steering_drains_all_at_once_before_next_generate() -> None:
    loop_ref: list[AgentLoop] = []

    async def note(_: NoteParams) -> AgentToolResult:
        loop_ref[0].steer("first correction")
        loop_ref[0].steer("second correction")
        return AgentToolResult(text="noted")

    tool = create_agent_tool("note", "notes things", NoteParams, note)
    model = FakeModel(
        [
            response(
                "a1",
                text="working",
                tool_calls=[ToolCall(id="c1", tool_name="note", parameters={})],
            ),
            response("a2", text="done"),
        ]
    )
    async with model:
        loop = AgentLoop(model, tools=[tool])
        loop_ref.append(loop)
        loop.follow_up("go")

        turns = await collect_turns(loop)

    turn = turns[0]
    assert [type(m) for m in turn.messages] == [
        UserMessage,
        AssistantMessage,
        ToolResultMessage,
        UserMessage,
        UserMessage,
        AssistantMessage,
    ]
    steered = [m.content[0].text for m in turn.messages if isinstance(m, UserMessage)][1:]
    assert steered == ["first correction", "second correction"]


async def test_steering_drain_one_by_one_spreads_across_generations() -> None:
    loop_ref: list[AgentLoop] = []

    async def note(_: NoteParams) -> AgentToolResult:
        return AgentToolResult(text="noted")

    async def enqueue_both_on_first(call: ToolCall) -> ToolCallDecision:
        if call.id == "c1":
            loop_ref[0].steer("first correction")
            loop_ref[0].steer("second correction")
        return ToolCallDecision(action="run")

    tool = create_agent_tool("note", "notes things", NoteParams, note)
    model = FakeModel(
        [
            response(
                "a1",
                text="working",
                tool_calls=[ToolCall(id="c1", tool_name="note", parameters={})],
            ),
            response(
                "a2",
                text="still working",
                tool_calls=[ToolCall(id="c2", tool_name="note", parameters={})],
            ),
            response("a3", text="done"),
        ]
    )
    async with model:
        loop = AgentLoop(
            model,
            tools=[tool],
            options=AgentLoopOptions(steering_drain="one-by-one"),
            hooks=AgentLoopHooks(before_tool_call=enqueue_both_on_first),
        )
        loop_ref.append(loop)
        loop.follow_up("go")

        turns = await collect_turns(loop)

    turn = turns[0]
    assert [type(m) for m in turn.messages] == [
        UserMessage,
        AssistantMessage,
        ToolResultMessage,
        UserMessage,
        AssistantMessage,
        ToolResultMessage,
        UserMessage,
        AssistantMessage,
    ]
    assert turn.messages[3].content[0].text == "first correction"
    assert turn.messages[6].content[0].text == "second correction"


async def test_undrained_steering_raises_stranded() -> None:
    void_model = FakeModel([])
    async with void_model:
        void_loop = AgentLoop(void_model)
        void_loop.steer("into the void")
        with pytest.raises(AgentLoopStranded):
            await anext(aiter(void_loop))

    loop_ref: list[AgentLoop] = []
    model = _SteerOnGenerate(
        FakeModel([response("a1", text="done")]),
        lambda text: loop_ref[0].steer(text),
    )
    async with model:
        loop = AgentLoop(model)
        loop_ref.append(loop)
        loop.follow_up("go")

        iterator = aiter(loop)
        events: list[SessionMessage | AgentLoopTurn] = []
        with pytest.raises(AgentLoopStranded):
            async for event in iterator:
                events.append(event)
        turns = [event for event in events if isinstance(event, AgentLoopTurn)]
        assert [turn.termination for turn in turns] == ["final_response"]


async def test_follow_ups_drain_one_by_one() -> None:
    model = FakeModel(
        [
            response("a1", text="first answer"),
            response("a2", text="second answer"),
            response("a3", text="third answer"),
        ]
    )
    async with model:
        loop = AgentLoop(model)
        loop.follow_up("one")
        loop.follow_up("two")
        loop.follow_up("three")

        turns = await collect_turns(loop)

    assert len(turns) == 3
    assert [turn.assistant_message.id for turn in turns] == ["a1", "a2", "a3"]
    assert [turn.messages[0].content[0].text for turn in turns] == ["one", "two", "three"]
    assert all(turn.generations == 1 for turn in turns)


async def test_follow_ups_drain_all_at_once() -> None:
    model = FakeModel([response("a1", text="combined answer")])
    async with model:
        loop = AgentLoop(model, options=AgentLoopOptions(follow_up_drain="all-at-once"))
        loop.follow_up("first part")
        loop.follow_up("second part")
        loop.follow_up("third part")

        turns = await collect_turns(loop)

    assert len(turns) == 1
    assert [type(m) for m in turns[0].messages] == [
        UserMessage,
        UserMessage,
        UserMessage,
        AssistantMessage,
    ]
    assert [m.content[0].text for m in turns[0].messages if isinstance(m, UserMessage)] == [
        "first part",
        "second part",
        "third part",
    ]
    assert turns[0].generations == 1


async def test_empty_run_ends_cleanly_with_zero_turns() -> None:
    model = FakeModel([])
    async with model:
        loop = AgentLoop(model)

        turns = await collect_turns(loop)

    assert turns == []
    assert list(model.history) == []


async def test_model_exceptions_propagate() -> None:
    model = BoomModel()
    async with model:
        loop = AgentLoop(model)
        loop.follow_up("go")
        with pytest.raises(RuntimeError, match="provider 500"):
            async for _ in loop:
                pass
        assert model.exited is False
    assert model.exited is True


async def test_max_generations_exhaustion_raises_after_yielding_prior_turns() -> None:
    async def count(_: CountParams) -> AgentToolResult:
        return AgentToolResult(text="counted")

    tool = create_agent_tool("count", "counts", CountParams, count)
    script = [
        response("a1", text="first answer"),
        response(
            "a2", text="more", tool_calls=[ToolCall(id="c2", tool_name="count", parameters={})]
        ),
        response(
            "a3", text="more", tool_calls=[ToolCall(id="c3", tool_name="count", parameters={})]
        ),
        response(
            "a4", text="more", tool_calls=[ToolCall(id="c4", tool_name="count", parameters={})]
        ),
    ]
    model = FakeModel(script)
    async with model:
        loop = AgentLoop(model, tools=[tool], options=AgentLoopOptions(max_generations=3))
        loop.follow_up("first")
        loop.follow_up("second")

        collected: list[AgentLoopTurn] = []
        with pytest.raises(AgentLoopExhausted):
            async for event in loop:
                if isinstance(event, AgentLoopTurn):
                    collected.append(event)

    assert [turn.assistant_message.id for turn in collected] == ["a1"]
    assert [turn.generations for turn in collected] == [1]
    assert len([m for m in model.history if isinstance(m, AssistantMessage)]) == 3
    assert [m.tool_call_id for m in model.history if isinstance(m, ToolResultMessage)] == [
        "c2",
        "c3",
    ]
