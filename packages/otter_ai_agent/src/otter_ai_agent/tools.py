"""Tool execution for the agent loop.

A near-verbatim Python port of pi's ``executeToolCalls`` machinery
(``packages/agent/src/agent-loop.ts``), adapted to otter types. The entry point
is :func:`execute_tool_calls`, which the driver calls with the assistant
message, the :class:`~otter_ai_agent.AgentConfig`, the live context view, the
run's abort signal, and an emit sink.

Responsibilities (all mirroring pi):

* pick sequential vs parallel dispatch (config default, per-tool override);
* validate arguments (otter-native: a pydantic ``parameters_model`` when the
  :class:`~otter_ai_agent.AgentTool` carries one);
* run ``before_tool_call`` (may block -> error result);
* execute, streaming ``tool_execution_update`` events;
* run ``after_tool_call`` (field-merge override, including ``is_error``);
* honour the per-result ``terminate`` hint (early-stop only when *every* result
  in the batch sets it);
* fail every call as an error when the response was truncated
  (``stop_reason == "length"``) -- streamed tool args may be silently incomplete.

This module emits only ``tool_execution.*`` events. The driver owns
``message.start`` / ``message.end`` for the resulting tool-result items (it
creates their ids and sends them to the session).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from otter_ai_core.context import (
    AssistantMessage,
    Context,
    Role,
    StopReason,
    TextContent,
    ToolCall,
    ToolResultMessage,
)
from otter_ai_core.context.content import ContentType

from .events import (
    AgentEvent,
    AgentEventType,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    ToolExecutionUpdateEvent,
)
from .types import (
    AfterToolCallContext,
    AfterToolCallResult,
    AgentConfig,
    AgentTool,
    AgentToolResult,
    BeforeToolCallContext,
    Unset,
)

#: Async sink the executor emits ``tool_execution.*`` events through. Typed
#: as a coroutine-returning callable so emitted events can be scheduled as
#: asyncio tasks (for ``tool_execution.update``).
EventSink = Callable[[AgentEvent], Coroutine[Any, Any, None]]


@dataclass
class _Finalized:
    """A tool call that has been executed (or short-circuited) to a result."""

    tool_call: ToolCall
    result: AgentToolResult
    is_error: bool


@dataclass
class ToolBatch:
    """Outcome of executing one assistant message's tool calls."""

    messages: list[ToolResultMessage]
    #: ``True`` only when every finalized result set ``terminate`` (early-stop).
    terminate: bool


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _error_result(message: str) -> AgentToolResult:
    return AgentToolResult(content=[TextContent(type=ContentType.Text, text=message)])


def _now_ms() -> int:
    return int(asyncio.get_event_loop().time() * 1000)


def _to_message(finalized: _Finalized) -> ToolResultMessage:
    return ToolResultMessage(
        role=Role.ToolResult,
        tool_call_id=finalized.tool_call.id,
        tool_name=finalized.tool_call.name,
        content=list(finalized.result.content),
        details=finalized.result.details,
        is_error=finalized.is_error,
        timestamp=_now_ms(),
    )


def _should_terminate(finalized: list[_Finalized]) -> bool:
    return bool(finalized) and all(f.result.terminate for f in finalized)


def _find_tool(config: AgentConfig, name: str) -> AgentTool | None:
    return next((t for t in config.tools if t.name == name), None)


def _validate_args(tool: AgentTool, raw_args: dict[str, Any]) -> Any:
    """Validate raw call args. Returns a pydantic instance if the tool carries
    a ``parameters_model``, else the raw dict. Raises on invalid args."""
    if tool.parameters_model is None:
        return raw_args
    model_cls: type[BaseModel] = tool.parameters_model
    return model_cls.model_validate(raw_args)


def _prepare_args(tool: AgentTool, tool_call: ToolCall) -> dict[str, Any]:
    if tool.prepare_arguments is None:
        return dict(tool_call.arguments)
    return tool.prepare_arguments(dict(tool_call.arguments))


def _merge_override(
    result: AgentToolResult, is_error: bool, override: AfterToolCallResult
) -> tuple[AgentToolResult, bool]:
    """Apply an :class:`AfterToolCallResult` field-merge. Returns the merged
    ``(result, is_error)``."""
    merged = AgentToolResult(
        content=(
            result.content
            if isinstance(override.content, Unset)
            else list(override.content)
        ),
        details=result.details
        if isinstance(override.details, Unset)
        else override.details,
        terminate=(
            result.terminate
            if isinstance(override.terminate, Unset)
            else bool(override.terminate)
        ),
    )
    merged_is_error = (
        is_error if isinstance(override.is_error, Unset) else bool(override.is_error)
    )
    return merged, merged_is_error


# --------------------------------------------------------------------------- #
# Prepare / execute / finalize
# --------------------------------------------------------------------------- #


@dataclass
class _Prepared:
    kind: str  # "prepared" | "immediate"
    tool_call: ToolCall
    tool: AgentTool | None
    args: Any
    result: AgentToolResult | None  # set for immediate
    is_error: bool | None  # set for immediate


async def _prepare(
    assistant_message: AssistantMessage,
    tool_call: ToolCall,
    config: AgentConfig,
    context: Context,
    abort: asyncio.Event,
) -> _Prepared:
    tool = _find_tool(config, tool_call.name)
    if tool is None:
        return _Prepared(
            "immediate",
            tool_call,
            None,
            None,
            _error_result(f"Tool {tool_call.name!r} not found"),
            True,
        )
    try:
        validated = _validate_args(tool, _prepare_args(tool, tool_call))
    except (ValidationError, ValueError, TypeError) as exc:
        return _Prepared(
            "immediate",
            tool_call,
            tool,
            None,
            _error_result(f"Invalid arguments for {tool_call.name!r}: {exc}"),
            True,
        )
    if config.before_tool_call is not None:
        before = await config.before_tool_call(
            BeforeToolCallContext(
                assistant_message=assistant_message,
                tool_call=tool_call,
                args=validated,
                context=context,
            ),
            abort,
        )
        if abort.is_set():
            return _Prepared(
                "immediate",
                tool_call,
                tool,
                None,
                _error_result("Operation aborted"),
                True,
            )
        if before is not None and before.block:
            return _Prepared(
                "immediate",
                tool_call,
                tool,
                None,
                _error_result(before.reason or "Tool execution was blocked"),
                True,
            )
    if abort.is_set():
        return _Prepared(
            "immediate",
            tool_call,
            tool,
            None,
            _error_result("Operation aborted"),
            True,
        )
    return _Prepared("prepared", tool_call, tool, validated, None, None)


async def _execute_prepared(
    prepared: _Prepared, abort: asyncio.Event, emit: EventSink
) -> tuple[AgentToolResult, bool]:
    assert prepared.tool is not None
    update_tasks: list[asyncio.Task[None]] = []
    accepting = True

    def on_update(partial: AgentToolResult) -> None:
        nonlocal accepting
        if not accepting:
            return
        update_tasks.append(
            asyncio.create_task(
                emit(
                    ToolExecutionUpdateEvent(
                        type=AgentEventType.ToolExecutionUpdate,
                        tool_call_id=prepared.tool_call.id,
                        tool_name=prepared.tool_call.name,
                        args=prepared.tool_call.arguments,
                        partial_result=partial,
                    )
                )
            )
        )

    try:
        result = await prepared.tool.execute(
            prepared.tool_call.id, prepared.args, abort, on_update
        )
        return result, False
    except Exception as exc:  # noqa: BLE001 — encode execution failures as results.
        return (
            _error_result(
                f"Tool {prepared.tool_call.name!r} failed: {type(exc).__name__}: {exc}"
            ),
            True,
        )
    finally:
        accepting = False
        if update_tasks:
            await asyncio.gather(*update_tasks, return_exceptions=True)


async def _finalize(
    assistant_message: AssistantMessage,
    prepared: _Prepared,
    result: AgentToolResult,
    is_error: bool,
    config: AgentConfig,
    context: Context,
    abort: asyncio.Event,
) -> _Finalized:
    if config.after_tool_call is not None:
        try:
            override = await config.after_tool_call(
                AfterToolCallContext(
                    assistant_message=assistant_message,
                    tool_call=prepared.tool_call,
                    args=prepared.args,
                    result=result,
                    is_error=is_error,
                    context=context,
                ),
                abort,
            )
        except Exception as exc:  # noqa: BLE001 — hook failure -> error result.
            return _Finalized(
                prepared.tool_call,
                _error_result(
                    f"after_tool_call for {prepared.tool_call.name!r} raised: "
                    f"{type(exc).__name__}: {exc}"
                ),
                True,
            )
        if override is not None:
            result, is_error = _merge_override(result, is_error, override)
    return _Finalized(prepared.tool_call, result, is_error)


async def _emit_start(tool_call: ToolCall, emit: EventSink) -> None:
    await emit(
        ToolExecutionStartEvent(
            type=AgentEventType.ToolExecutionStart,
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            args=tool_call.arguments,
        )
    )


async def _emit_end(finalized: _Finalized, emit: EventSink) -> None:
    await emit(
        ToolExecutionEndEvent(
            type=AgentEventType.ToolExecutionEnd,
            tool_call_id=finalized.tool_call.id,
            tool_name=finalized.tool_call.name,
            result=finalized.result,
            is_error=finalized.is_error,
        )
    )


async def _fail_truncated(tool_calls: list[ToolCall], emit: EventSink) -> ToolBatch:
    """Fail every tool call from a truncated (``length``) response."""
    finalized: list[_Finalized] = []
    for tool_call in tool_calls:
        await _emit_start(tool_call, emit)
        f = _Finalized(
            tool_call,
            _error_result(
                f"Tool call {tool_call.name!r} was not executed: the response hit "
                "the output token limit, so its arguments may be truncated. "
                "Re-issue the tool call with complete arguments."
            ),
            True,
        )
        await _emit_end(f, emit)
        finalized.append(f)
    return ToolBatch([_to_message(f) for f in finalized], terminate=False)


# --------------------------------------------------------------------------- #
# Sequential / parallel
# --------------------------------------------------------------------------- #


async def _run_one(
    assistant_message: AssistantMessage,
    tool_call: ToolCall,
    config: AgentConfig,
    context: Context,
    abort: asyncio.Event,
    emit: EventSink,
) -> _Finalized:
    """Prepare, execute, finalize a single tool call (used by the sequential
    path and by the parallel path's immediate short-circuits)."""
    prepared = await _prepare(assistant_message, tool_call, config, context, abort)
    if prepared.kind == "immediate":
        assert prepared.result is not None and prepared.is_error is not None
        return _Finalized(prepared.tool_call, prepared.result, prepared.is_error)
    result, is_error = await _execute_prepared(prepared, abort, emit)
    return await _finalize(
        assistant_message, prepared, result, is_error, config, context, abort
    )


async def _run_sequential(
    assistant_message: AssistantMessage,
    tool_calls: list[ToolCall],
    config: AgentConfig,
    context: Context,
    abort: asyncio.Event,
    emit: EventSink,
) -> ToolBatch:
    finalized: list[_Finalized] = []
    for tool_call in tool_calls:
        await _emit_start(tool_call, emit)
        f = await _run_one(assistant_message, tool_call, config, context, abort, emit)
        await _emit_end(f, emit)
        finalized.append(f)
        if abort.is_set():
            break
    return ToolBatch(
        [_to_message(f) for f in finalized], terminate=_should_terminate(finalized)
    )


async def _run_parallel(
    assistant_message: AssistantMessage,
    tool_calls: list[ToolCall],
    config: AgentConfig,
    context: Context,
    abort: asyncio.Event,
    emit: EventSink,
) -> ToolBatch:
    # Prepare sequentially (validation + before_tool_call); execute allowed
    # calls concurrently. tool_execution_end fires in completion order; result
    # messages are returned in source order.
    by_id: dict[str, _Finalized] = {}
    jobs: dict[asyncio.Task[tuple[AgentToolResult, bool]], _Prepared] = {}

    for tool_call in tool_calls:
        await _emit_start(tool_call, emit)
        prepared = await _prepare(assistant_message, tool_call, config, context, abort)
        if prepared.kind == "immediate":
            assert prepared.result is not None and prepared.is_error is not None
            by_id[tool_call.id] = _Finalized(
                prepared.tool_call, prepared.result, prepared.is_error
            )
            await _emit_end(by_id[tool_call.id], emit)
            if abort.is_set():
                break
            continue
        assert prepared.tool is not None
        task = asyncio.create_task(_execute_prepared(prepared, abort, emit))
        jobs[task] = prepared
        if abort.is_set():
            break

    # Drive jobs, emitting tool_execution_end in completion order.
    while jobs:
        done, _ = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            prepared = jobs.pop(task)
            result, is_error = await task
            f = await _finalize(
                assistant_message, prepared, result, is_error, config, context, abort
            )
            by_id[prepared.tool_call.id] = f
            await _emit_end(f, emit)

    finalized = [by_id[tc.id] for tc in tool_calls if tc.id in by_id]
    return ToolBatch(
        [_to_message(f) for f in finalized], terminate=_should_terminate(finalized)
    )


# --------------------------------------------------------------------------- #
# Public entry
# --------------------------------------------------------------------------- #


async def execute_tool_calls(
    assistant_message: AssistantMessage,
    config: AgentConfig,
    context: Context,
    abort: asyncio.Event,
    emit: EventSink,
) -> ToolBatch:
    """Execute every tool call in ``assistant_message``.

    Returns a :class:`ToolBatch` of result messages and an early-terminate
    hint. Truncated (``length``) responses fail every call without executing.
    """
    tool_calls = [c for c in assistant_message.content if isinstance(c, ToolCall)]
    if not tool_calls:
        return ToolBatch([], terminate=False)

    if assistant_message.stop_reason == StopReason.Length:
        return await _fail_truncated(tool_calls, emit)

    has_sequential_override = any(
        (t := _find_tool(config, tc.name)) is not None
        and t.execution_mode == "sequential"
        for tc in tool_calls
    )
    if config.tool_execution == "sequential" or has_sequential_override:
        return await _run_sequential(
            assistant_message, tool_calls, config, context, abort, emit
        )
    return await _run_parallel(
        assistant_message, tool_calls, config, context, abort, emit
    )
