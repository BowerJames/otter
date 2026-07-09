"""Integration tests for ``otter_ai_agent.Agent`` over a scripted ``ModelSession``."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from _support import (
    TurnScript,
    assistant,
    collect_stream,
    new_session,
    run_backend,
    text_block,
    tool_call,
)

from otter_ai_agent import events as ev
from otter_ai_agent.agent import Agent
from otter_ai_agent.types import (
    AfterToolCallContext,
    AfterToolCallResult,
    AgentConfig,
    AgentTool,
    AgentToolResult,
    BeforeToolCallContext,
    BeforeToolCallResult,
    PrepareNextTurnContext,
    PrepareNextTurnResult,
    ShouldStopAfterTurnContext,
)
from otter_ai_core import StopReason
from otter_ai_core.context import Context, ContextItem, Role, UserMessage
from otter_ai_core.model_connection.client_events import (
    ClientEvent,
    ContextItemAddEvent,
    ResponseCreate,
)
from otter_ai_core.model_connection.server_events import (
    ResponseStartedEvent,
    ServerEventTypes,
)
from otter_ai_core.model_session import ModelSession
from otter_ai_core.tools import Tool

Prompt = "str | UserMessage | list[Any]"


def echo_tool(
    record: list[tuple[str, Any]] | None = None,
    *,
    delay: float = 0.0,
    abortable: bool = False,
    name: str = "echo",
    result: AgentToolResult | None = None,
) -> AgentTool:
    async def execute(
        tool_call_id: str,
        args: Any,
        abort: asyncio.Event,
        on_update: Any,
    ) -> AgentToolResult:
        if record is not None:
            record.append((tool_call_id, args))
        if abortable:
            try:
                await asyncio.wait_for(abort.wait(), timeout=2.0)
                return AgentToolResult(content=[text_block("aborted-early")])
            except TimeoutError:
                return AgentToolResult(content=[text_block("completed")])
        if delay:
            await asyncio.sleep(delay)
        return result or AgentToolResult(content=[text_block(f"{name}-ok")])

    return AgentTool(
        tool=Tool(
            name=name, description="d", parameters={"type": "object", "properties": {}}
        ),
        execute=execute,
    )


async def build_and_run(
    scripts: list[TurnScript],
    config: AgentConfig,
    *,
    prompt: str | UserMessage | list[Any] = "hi",
    pre: Callable[[Agent], None] | None = None,
) -> tuple[Agent, list[ContextItem], list[ClientEvent]]:
    conn, backend = new_session()
    session = ModelSession(conn)
    agent = Agent(session, config)
    if pre is not None:
        pre(agent)
    received: list[ClientEvent] = []
    driver = asyncio.create_task(run_backend(backend, scripts, received))
    items = await agent.run(prompt)
    session.close()
    await driver
    return agent, items, received


def _collector(
    bucket: list[ev.AgentEvent],
) -> Callable[[ev.AgentEvent], Awaitable[None]]:
    async def handler(event: ev.AgentEvent) -> None:
        bucket.append(event)

    return handler


def _by_type(items: list[ContextItem], role: Role) -> list[ContextItem]:
    return [i for i in items if i.role == role]


# --------------------------------------------------------------------------- #


async def test_tool_use_then_stop() -> None:
    record: list[tuple[str, Any]] = []
    config = AgentConfig(tools=[echo_tool(record)])
    scripts = [
        TurnScript(
            content=[tool_call("c1", "echo", {"x": 1})], stop_reason=StopReason.ToolUse
        ),
        TurnScript(content=[text_block("done")], stop_reason=StopReason.Stop),
    ]
    agent, items, received = await build_and_run(scripts, config)

    # user prompt, assistant(tool_use), tool result, assistant(stop)
    assert len(items) == 4
    assert [i.role for i in items] == [
        Role.User,
        Role.Assistant,
        Role.ToolResult,
        Role.Assistant,
    ]
    assert record == [("c1", {"x": 1})]
    # Two responses requested; two items added (user prompt + tool result).
    assert len([e for e in received if isinstance(e, ResponseCreate)]) == 2
    assert len([e for e in received if isinstance(e, ContextItemAddEvent)]) == 2
    assert [i.id for i in agent.context.items] == [i.id for i in items]


async def test_stream_and_on_both_receive_events() -> None:
    config = AgentConfig(tools=[echo_tool()])
    scripts = [
        TurnScript(
            content=[tool_call("c1", "echo", {})], stop_reason=StopReason.ToolUse
        ),
        TurnScript(content=[text_block("done")], stop_reason=StopReason.Stop),
    ]
    conn, backend = new_session()
    session = ModelSession(conn)
    agent = Agent(session, config)

    seen: list[ev.AgentEvent] = []
    agent.on(ev.AgentEventType.AgentEnd, _collector(seen))

    received: list[ClientEvent] = []
    driver = asyncio.create_task(run_backend(backend, scripts, received))
    streamed = await collect_stream(agent.stream("hi"))
    session.close()
    await driver

    types = [e.type for e in streamed]
    assert types[0] is ev.AgentEventType.AgentStart
    assert types[-1] is ev.AgentEventType.AgentEnd
    assert ev.AgentEventType.ToolExecutionEnd in types
    assert len(seen) == 1
    assert seen[0].type is ev.AgentEventType.AgentEnd


async def test_before_tool_call_block_integration() -> None:
    async def before(
        ctx: BeforeToolCallContext, abort: asyncio.Event
    ) -> BeforeToolCallResult:
        return BeforeToolCallResult(block=True, reason="denied")

    config = AgentConfig(tools=[echo_tool()], before_tool_call=before)
    scripts = [
        TurnScript(
            content=[tool_call("c1", "echo", {})], stop_reason=StopReason.ToolUse
        ),
        TurnScript(content=[text_block("done")], stop_reason=StopReason.Stop),
    ]
    _, items, _ = await build_and_run(scripts, config)
    tool_result = _by_type(items, Role.ToolResult)[0]
    assert tool_result.is_error  # type: ignore[union-attr]
    assert "denied" in tool_result.content[0].text  # type: ignore[union-attr]


async def test_after_tool_call_override_integration() -> None:
    async def after(
        ctx: AfterToolCallContext, abort: asyncio.Event
    ) -> AfterToolCallResult:
        return AfterToolCallResult(is_error=True)

    config = AgentConfig(tools=[echo_tool()], after_tool_call=after)
    scripts = [
        TurnScript(
            content=[tool_call("c1", "echo", {})], stop_reason=StopReason.ToolUse
        ),
        TurnScript(content=[text_block("done")], stop_reason=StopReason.Stop),
    ]
    _, items, _ = await build_and_run(scripts, config)
    assert _by_type(items, Role.ToolResult)[0].is_error  # type: ignore[union-attr]


async def test_terminate_early_stop() -> None:
    stop_tool = echo_tool(
        result=AgentToolResult(content=[text_block("stop-now")], terminate=True)
    )
    config = AgentConfig(tools=[stop_tool])
    scripts = [
        TurnScript(
            content=[tool_call("c1", "echo", {})], stop_reason=StopReason.ToolUse
        ),
    ]
    _, items, received = await build_and_run(scripts, config)
    assert len(_by_type(items, Role.Assistant)) == 1
    assert len([e for e in received if isinstance(e, ResponseCreate)]) == 1


async def test_length_truncation_fail_all() -> None:
    config = AgentConfig(tools=[echo_tool()])
    scripts = [
        TurnScript(
            content=[tool_call("c1", "echo", {})], stop_reason=StopReason.Length
        ),
        TurnScript(content=[text_block("done")], stop_reason=StopReason.Stop),
    ]
    _, items, _ = await build_and_run(scripts, config)
    tool_result = _by_type(items, Role.ToolResult)[0]
    assert tool_result.is_error  # type: ignore[union-attr]
    assert "token limit" in tool_result.content[0].text  # type: ignore[union-attr]


async def test_error_terminal_ends_run() -> None:
    config = AgentConfig()
    scripts = [TurnScript(kind="error", error_message="model blew up")]
    _, items, _ = await build_and_run(scripts, config)
    assert len(items) == 1  # only the user prompt; failed assistant not committed
    assert items[0].role == Role.User


async def test_aborted_terminal_ends_run() -> None:
    config = AgentConfig()
    scripts = [TurnScript(kind="aborted")]
    _, items, _ = await build_and_run(scripts, config)
    assert len(items) == 1


async def test_abort_during_tool_execution_is_honoured() -> None:
    config = AgentConfig(tools=[echo_tool(abortable=True)])
    scripts = [
        TurnScript(
            content=[tool_call("c1", "echo", {})], stop_reason=StopReason.ToolUse
        ),
    ]
    conn, backend = new_session()
    session = ModelSession(conn)
    agent = Agent(session, config)
    received: list[ClientEvent] = []
    driver = asyncio.create_task(run_backend(backend, scripts, received))

    task = asyncio.create_task(agent.run("hi"))
    await asyncio.sleep(0.05)  # let the tool_use turn reach tool execution
    agent.abort()
    items = await task
    session.close()
    await driver

    tool_results = _by_type(items, Role.ToolResult)
    assert len(tool_results) == 1
    assert tool_results[0].content[0].text == "aborted-early"  # type: ignore[union-attr]
    assert len([e for e in received if isinstance(e, ResponseCreate)]) == 1


async def test_steering_injected_before_first_turn() -> None:
    config = AgentConfig(tools=[echo_tool()])
    scripts = [
        TurnScript(content=[text_block("ok")], stop_reason=StopReason.Stop),
    ]

    def pre(agent: Agent) -> None:
        agent.steer(UserMessage(role=Role.User, content="steer!", timestamp=0))

    _, items, _ = await build_and_run(scripts, config, pre=pre)
    user_items = _by_type(items, Role.User)
    assert len(user_items) == 2
    assert user_items[1].content == "steer!"


async def test_follow_up_continues_after_stop() -> None:
    config = AgentConfig()
    scripts = [
        TurnScript(content=[text_block("first")], stop_reason=StopReason.Stop),
        TurnScript(content=[text_block("second")], stop_reason=StopReason.Stop),
    ]

    def pre(agent: Agent) -> None:
        agent.follow_up(UserMessage(role=Role.User, content="again", timestamp=0))

    _, items, _ = await build_and_run(scripts, config, pre=pre)
    assert [i.role for i in items] == [
        Role.User,
        Role.Assistant,
        Role.User,
        Role.Assistant,
    ]


async def test_single_active_run_guard() -> None:
    config = AgentConfig(tools=[echo_tool(delay=0.05)])
    scripts = [
        TurnScript(
            content=[tool_call("c1", "echo", {})], stop_reason=StopReason.ToolUse
        ),
        TurnScript(content=[text_block("done")], stop_reason=StopReason.Stop),
    ]
    conn, backend = new_session()
    session = ModelSession(conn)
    agent = Agent(session, config)
    received: list[ClientEvent] = []
    driver = asyncio.create_task(run_backend(backend, scripts, received))
    first = asyncio.create_task(agent.run("hi"))
    await asyncio.sleep(0.01)
    try:
        await agent.run("again")
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass
    await first
    session.close()
    await driver


async def test_should_stop_after_turn() -> None:
    async def stop_after_two(ctx: ShouldStopAfterTurnContext) -> bool:
        return True  # stop immediately after the first tool turn

    config = AgentConfig(tools=[echo_tool()], should_stop_after_turn=stop_after_two)
    scripts = [
        TurnScript(
            content=[tool_call("c1", "echo", {})], stop_reason=StopReason.ToolUse
        ),
        TurnScript(content=[text_block("never")], stop_reason=StopReason.Stop),
    ]
    _, _, received = await build_and_run(scripts, config)
    assert len([e for e in received if isinstance(e, ResponseCreate)]) == 1


# --------------------------------------------------------------------------- #
# Regression tests for code-review findings (I-1, I-2) + coverage gaps
# --------------------------------------------------------------------------- #


async def _stream_events(
    scripts: list[TurnScript], config: AgentConfig
) -> list[ev.AgentEvent]:
    conn, backend = new_session()
    session = ModelSession(conn)
    agent = Agent(session, config)
    received: list[ClientEvent] = []
    driver = asyncio.create_task(run_backend(backend, scripts, received))
    streamed = await collect_stream(agent.stream("hi"))
    session.close()
    await driver
    return streamed


def _idx(events: list[ev.AgentEvent], t: ev.AgentEventType) -> int:
    return next(i for i, e in enumerate(events) if e.type == t)


async def test_error_terminal_emits_one_start_one_end() -> None:
    """I-1: an error response emits exactly one MessageStart and one MessageEnd."""
    events = await _stream_events(
        [TurnScript(kind="error", error_message="boom")], AgentConfig()
    )
    starts = [
        e
        for e in events
        if e.type == ev.AgentEventType.MessageStart and e.item.role == Role.Assistant
    ]
    ends = [
        e
        for e in events
        if e.type == ev.AgentEventType.MessageEnd and e.item.role == Role.Assistant
    ]
    assert len(starts) == 1, "double MessageStart for error response"
    assert len(ends) == 1
    assert _idx(events, ev.AgentEventType.MessageStart) < _idx(
        events, ev.AgentEventType.MessageEnd
    )
    assert events[-1].type is ev.AgentEventType.AgentEnd
    assert events[-1].error is True


async def test_aborted_terminal_emits_one_start_one_end() -> None:
    """I-1: an aborted response emits exactly one MessageStart and one MessageEnd."""
    events = await _stream_events([TurnScript(kind="aborted")], AgentConfig())
    starts = [
        e
        for e in events
        if e.type == ev.AgentEventType.MessageStart and e.item.role == Role.Assistant
    ]
    ends = [
        e
        for e in events
        if e.type == ev.AgentEventType.MessageEnd and e.item.role == Role.Assistant
    ]
    assert len(starts) == 1, "double MessageStart for aborted response"
    assert len(ends) == 1
    assert _idx(events, ev.AgentEventType.MessageStart) < _idx(
        events, ev.AgentEventType.MessageEnd
    )


async def test_abort_during_generation_emits_paired_message_end() -> None:
    """I-2: when abort wins the race before a terminal, the in-progress
    response's MessageStart still gets a paired MessageEnd."""
    from otter_ai_core.model_connection.client_events import AbortResponseEvent

    async def gen_then_ignore_abort(backend: Any, received: list[ClientEvent]) -> None:
        async for client_event in backend:
            received.append(client_event)
            if isinstance(client_event, ResponseCreate):
                backend.push(
                    ResponseStartedEvent(
                        type=ServerEventTypes.ResponseStarted,
                        role=Role.Assistant,
                        partial=assistant([], StopReason.Stop),
                    )
                )
            # AbortResponseEvent is deliberately ignored -- no ResponseAborted is
            # delivered, so the abort must win the race in _await_turn.
        backend.end()

    conn, backend = new_session()
    session = ModelSession(conn)
    agent = Agent(session, AgentConfig())
    received: list[ClientEvent] = []
    driver = asyncio.create_task(gen_then_ignore_abort(backend, received))
    task = asyncio.create_task(collect_stream(agent.stream("hi")))
    await asyncio.sleep(0.05)  # let create_response + ResponseStarted land
    agent.abort()
    events = await task
    session.close()
    await driver

    starts = [
        e
        for e in events
        if e.type == ev.AgentEventType.MessageStart and e.item.role == Role.Assistant
    ]
    ends = [
        e
        for e in events
        if e.type == ev.AgentEventType.MessageEnd and e.item.role == Role.Assistant
    ]
    assert len(starts) == 1
    assert len(ends) == 1, "abort-during-generation left an unpaired MessageStart"
    assert _idx(events, ev.AgentEventType.MessageStart) < _idx(
        events, ev.AgentEventType.MessageEnd
    )
    assert any(e.type is ev.AgentEventType.AgentEnd and e.error for e in events)
    assert any(isinstance(e, AbortResponseEvent) for e in received)


async def test_message_update_streamed_for_text() -> None:
    """A streamed text response delivers MessageUpdate carrying the snapshot."""
    events = await _stream_events(
        [
            TurnScript(
                content=[text_block("hello")],
                stop_reason=StopReason.Stop,
                stream_text=True,
            )
        ],
        AgentConfig(),
    )
    updates = [e for e in events if e.type == ev.AgentEventType.MessageUpdate]
    assert len(updates) >= 1
    assert updates[0].message.content[0].text == "hello"  # type: ignore[union-attr]


async def test_prepare_next_turn_swaps_context_view() -> None:
    seen: list[PrepareNextTurnContext] = []

    async def prepare(ctx: PrepareNextTurnContext) -> PrepareNextTurnResult:
        seen.append(ctx)
        return PrepareNextTurnResult(
            context=Context(system_prompt="swapped", items=ctx.context.items)
        )

    config = AgentConfig(tools=[echo_tool()], prepare_next_turn=prepare)
    scripts = [
        TurnScript(
            content=[tool_call("c1", "echo", {})], stop_reason=StopReason.ToolUse
        ),
        TurnScript(content=[text_block("done")], stop_reason=StopReason.Stop),
    ]
    conn, backend = new_session()
    session = ModelSession(conn)
    agent = Agent(session, config)
    received: list[ClientEvent] = []
    driver = asyncio.create_task(run_backend(backend, scripts, received))
    await agent.run("hi")
    session.close()
    await driver

    assert len(seen) == 2  # prepare_next_turn runs after every turn (incl. last)
    assert agent.context.system_prompt == "swapped"


async def test_steering_mode_all_drains_everything() -> None:
    """QueueMode='all' injects every queued steering message before the turn."""
    config = AgentConfig(steering_mode="all")
    scripts = [TurnScript(content=[text_block("ok")], stop_reason=StopReason.Stop)]

    def pre(agent: Agent) -> None:
        agent.steer(UserMessage(role=Role.User, content="one", timestamp=0))
        agent.steer(UserMessage(role=Role.User, content="two", timestamp=0))

    _, items, _ = await build_and_run(scripts, config, pre=pre)
    user_contents = [i.content for i in _by_type(items, Role.User)]
    assert user_contents == ["hi", "one", "two"]
