"""Unit tests for ``otter_ai_agent.tools`` (execution engine)."""

from __future__ import annotations

import asyncio
from typing import Any

from _support import assistant, text_block, tool_call
from pydantic import BaseModel

from otter_ai_agent import events as ev
from otter_ai_agent.tools import ToolBatch, execute_tool_calls
from otter_ai_agent.types import (
    AfterToolCallContext,
    AfterToolCallResult,
    AgentConfig,
    AgentTool,
    AgentToolResult,
    AgentToolUpdateCallback,
    BeforeToolCallContext,
    BeforeToolCallResult,
)
from otter_ai_core import Context, StopReason
from otter_ai_core.context import TextContent
from otter_ai_core.context.content import ContentType
from otter_ai_core.tools import Tool


def make_tool(
    name: str = "calc",
    *,
    execution_mode: str | None = None,
    parameters_model: type[BaseModel] | None = None,
    delay: float = 0.0,
    fail: bool = False,
    updates: list[AgentToolResult] | None = None,
    record: list[tuple[str, Any]] | None = None,
    result: AgentToolResult | None = None,
) -> AgentTool:
    async def execute(
        tool_call_id: str,
        args: Any,
        abort: asyncio.Event,
        on_update: AgentToolUpdateCallback,
    ) -> AgentToolResult:
        if record is not None:
            record.append((tool_call_id, args))
        if delay:
            await asyncio.sleep(delay)
        if updates:
            for u in updates:
                on_update(u)
        if fail:
            raise RuntimeError("boom")
        return result or AgentToolResult(content=[text_block(f"{name}-ok")])

    return AgentTool(
        tool=Tool(
            name=name, description="d", parameters={"type": "object", "properties": {}}
        ),
        execute=execute,
        parameters_model=parameters_model,
        execution_mode=execution_mode,  # type: ignore[arg-type]
    )


async def _run(
    calls: list[Any],
    tools: list[AgentTool],
    message_stop: StopReason = StopReason.ToolUse,
    **kw: Any,
) -> tuple[list[ev.AgentEvent], ToolBatch]:
    """Execute ``calls`` and return ``(events, batch)``."""
    events: list[ev.AgentEvent] = []

    async def emit(event: ev.AgentEvent) -> None:
        events.append(event)

    msg = assistant(calls, message_stop)
    batch = await execute_tool_calls(
        msg, AgentConfig(tools=tools, **kw), Context(), asyncio.Event(), emit
    )
    return events, batch


def _starts(events: list[ev.AgentEvent]) -> list[str]:
    return [
        e.tool_call_id for e in events if e.type == ev.AgentEventType.ToolExecutionStart
    ]


def _ends(events: list[ev.AgentEvent]) -> list[str]:
    return [
        e.tool_call_id for e in events if e.type == ev.AgentEventType.ToolExecutionEnd
    ]


async def test_basic_execution_returns_results() -> None:
    events, batch = await _run(
        [tool_call("a", "calc", {}), tool_call("b", "calc", {})], [make_tool()]
    )
    assert len(batch.messages) == 2
    assert not batch.terminate
    assert {m.tool_call_id for m in batch.messages} == {"a", "b"}
    assert all(not m.is_error for m in batch.messages)
    assert _starts(events) == ["a", "b"]


async def test_unknown_tool_is_error_result() -> None:
    _, batch = await _run([tool_call("a", "missing", {})], [make_tool()])
    assert len(batch.messages) == 1
    assert batch.messages[0].is_error
    assert "not found" in batch.messages[0].content[0].text  # type: ignore[union-attr]


async def test_execute_exception_becomes_error_result() -> None:
    _, batch = await _run([tool_call("a", "boom", {})], [make_tool("boom", fail=True)])
    assert batch.messages[0].is_error
    assert "failed" in batch.messages[0].content[0].text  # type: ignore[union-attr]


async def test_parameters_model_validation() -> None:
    class Args(BaseModel):
        x: int

    tool = make_tool("calc", parameters_model=Args, record=[])
    _, batch = await _run([tool_call("a", "calc", {"x": "not-an-int"})], [tool])
    assert batch.messages[0].is_error
    assert "Invalid arguments" in batch.messages[0].content[0].text  # type: ignore[union-attr]

    # Valid case passes the validated model instance to execute.
    record: list[tuple[str, Any]] = []
    tool2 = make_tool("calc", parameters_model=Args, record=record)
    _, batch2 = await _run([tool_call("a", "calc", {"x": 5})], [tool2])
    assert not batch2.messages[0].is_error
    assert record[0][1] == Args(x=5)


async def test_before_tool_call_block() -> None:
    async def before(
        ctx: BeforeToolCallContext, abort: asyncio.Event
    ) -> BeforeToolCallResult:
        return BeforeToolCallResult(block=True, reason="nope")

    _, batch = await _run(
        [tool_call("a", "calc", {})], [make_tool()], before_tool_call=before
    )
    assert batch.messages[0].is_error
    assert "nope" in batch.messages[0].content[0].text  # type: ignore[union-attr]


async def test_after_tool_call_override() -> None:
    async def after(
        ctx: AfterToolCallContext, abort: asyncio.Event
    ) -> AfterToolCallResult:
        return AfterToolCallResult(
            content=[TextContent(type=ContentType.Text, text="rewritten")],
            is_error=True,
        )

    _, batch = await _run(
        [tool_call("a", "calc", {})], [make_tool()], after_tool_call=after
    )
    assert batch.messages[0].is_error
    assert batch.messages[0].content[0].text == "rewritten"  # type: ignore[union-attr]


async def test_terminate_hint_only_when_all_set_it() -> None:
    ok = make_tool("ok")
    stop = make_tool(
        "stop", result=AgentToolResult(content=[text_block("x")], terminate=True)
    )
    _, batch = await _run(
        [tool_call("a", "ok", {}), tool_call("b", "stop", {})], [ok, stop]
    )
    assert not batch.terminate  # one result did not terminate

    _, batch2 = await _run(
        [tool_call("a", "stop", {}), tool_call("b", "stop", {})], [stop]
    )
    assert batch2.terminate  # every result terminated


async def test_length_truncation_fails_all() -> None:
    events, batch = await _run(
        [tool_call("a", "calc", {})], [make_tool()], message_stop=StopReason.Length
    )
    assert len(batch.messages) == 1
    assert batch.messages[0].is_error
    assert "token limit" in batch.messages[0].content[0].text  # type: ignore[union-attr]
    # Start + End emitted even though nothing executed.
    assert _starts(events) == ["a"]
    assert _ends(events) == ["a"]


async def test_sequential_executes_in_order() -> None:
    record: list[tuple[str, Any]] = []
    tool = make_tool("calc", delay=0.01, record=record)
    calls = [tool_call(f"c{i}", "calc", {}) for i in range(4)]
    events, batch = await _run(calls, [tool], tool_execution="sequential")
    assert [r[0] for r in record] == ["c0", "c1", "c2", "c3"]
    assert _ends(events) == ["c0", "c1", "c2", "c3"]
    assert len(batch.messages) == 4


async def test_parallel_prepare_then_execute() -> None:
    record: list[tuple[str, Any]] = []
    tool = make_tool("calc", delay=0.01, record=record)
    calls = [tool_call(f"c{i}", "calc", {}) for i in range(4)]
    events, batch = await _run(calls, [tool], tool_execution="parallel")
    assert {r[0] for r in record} == {"c0", "c1", "c2", "c3"}
    assert _starts(events) == ["c0", "c1", "c2", "c3"]
    # Result messages are in source order even though ends may complete out of order.
    assert [m.tool_call_id for m in batch.messages] == ["c0", "c1", "c2", "c3"]


async def test_update_events_emitted() -> None:
    updates = [AgentToolResult(content=[text_block("partial")])]
    tool = make_tool("calc", updates=updates)
    events, batch = await _run([tool_call("a", "calc", {})], [tool])
    update_events = [
        e for e in events if e.type == ev.AgentEventType.ToolExecutionUpdate
    ]
    assert len(update_events) == 1
    assert batch.messages[0].content[0].text == "calc-ok"  # type: ignore[union-attr]
