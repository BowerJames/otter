"""Agent-side types: the tool/executor pairing, hook contracts, and config.

otter's :class:`~otter_ai_core.context.Tool` is **declarative-only** (name,
description, JSON-schema ``parameters``) — it has no ``execute``. This module
defines the runtime pairing of *schema-for-the-model* (:class:`Tool`) with an
*executor* (:data:`AgentExecute`) plus the hook contracts
(``before_tool_call`` / ``after_tool_call`` / ``should_stop_after_turn`` /
``prepare_next_turn``) and the :class:`AgentConfig` bundle.

These are runtime objects (callables, class objects) and so are plain
``@dataclass`` types / :class:`typing.Protocol` / ``type`` aliases — **not**
Pydantic models (they are not serialized). The serializable event family lives
in :mod:`otter_ai_agent.events`.

The shapes mirror ``@earendil-works/pi-agent-core``'s
``AgentTool`` / hook interfaces, adapted to otter's reactive session model:
context shaping (``convertToLlm`` / ``transformContext``) is absent because the
backend owns the conversation, and the model/thinking swap from pi's
``prepareNextTurn`` is absent because a session is bound to one model at
connect. ``prepare_next_turn`` is therefore **context-view-only** (see
:class:`PrepareNextTurnResult`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from otter_ai_core.context import (
    AssistantMessage,
    Context,
    ContextItem,
    ToolCall,
    ToolResultMessage,
    UserContent,
)
from otter_ai_core.tools import Tool

# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #

ToolExecutionMode = Literal["sequential", "parallel"]
"""How multiple tool calls in one assistant message are executed.

* ``"sequential"`` — prepare, execute, and finalize each call before the next.
* ``"parallel"`` — prepare all calls, then execute allowed tools concurrently;
  ``tool_execution_end`` fires in completion order while result items are
  emitted in source order.
"""

QueueMode = Literal["all", "one-at-a-time"]
"""How many queued items a single drain removes (steering / follow-up)."""


@dataclass
class AgentToolResult:
    """Final or partial result produced by a tool.

    Mirrors pi's ``AgentToolResult``. ``content`` is what the model sees;
    ``details`` is arbitrary structured data for logs/UI; ``terminate`` is an
    early-stop hint honoured only when *every* result in a batch sets it.
    """

    content: list[UserContent]
    details: Any = None
    terminate: bool = False


type AgentToolUpdateCallback = Callable[[AgentToolResult], None]
"""Sync callback a tool calls to stream partial execution updates.

Scoped to the current ``execute`` invocation; calls after the tool's
awaitable settles are ignored by the driver."""


#: Executor signature: ``(tool_call_id, args, abort, on_update) -> result``.
#:
#: ``args`` is the raw ``dict`` from the :class:`ToolCall`, unless the
#: :class:`AgentTool` carries a ``parameters_model``, in which case it is the
#: validated pydantic instance. ``abort`` is the run's cooperative-cancel
#: signal (an :class:`asyncio.Event`); executors **should** honour it.
#: ``on_update`` streams partial :class:`AgentToolResult` snapshots.
type AgentExecute = Callable[
    [str, Any, asyncio.Event, AgentToolUpdateCallback],
    Awaitable[AgentToolResult],
]


@dataclass
class AgentTool:
    """Pairs a declarative :class:`Tool` (the schema sent to the model) with a
    runtime :data:`AgentExecute`.

    ``parameters_model`` (optional) enables otter-native argument validation:
    when set, the driver validates the call's ``arguments`` via
    ``parameters_model.model_validate(...)`` before executing (and before
    ``before_tool_call``), passing the validated instance to the executor.
    ``execution_mode`` overrides :attr:`AgentConfig.tool_execution` per tool.
    """

    tool: Tool
    execute: AgentExecute
    parameters_model: type[Any] | None = None
    execution_mode: ToolExecutionMode | None = None
    prepare_arguments: Callable[[dict[str, Any]], dict[str, Any]] | None = None

    @property
    def name(self) -> str:
        return self.tool.name


# --------------------------------------------------------------------------- #
# Hooks: before / after tool call
# --------------------------------------------------------------------------- #


@dataclass
class BeforeToolCallContext:
    """Context passed to :data:`BeforeToolCallHook`."""

    assistant_message: AssistantMessage
    tool_call: ToolCall
    #: Validated args (pydantic instance if ``parameters_model`` set, else the
    #: raw ``dict``).
    args: Any
    #: Live conversation view at the time the call is prepared (includes the
    #: assistant turn; tool results are added after execution).
    context: Context


@dataclass
class BeforeToolCallResult:
    """Return from :data:`BeforeToolCallHook`.

    ``block=True`` prevents execution; the driver emits an error tool result
    carrying ``reason`` instead. Returning ``None`` is equivalent to
    ``block=False``.
    """

    block: bool = False
    reason: str | None = None


@dataclass
class AfterToolCallContext:
    """Context passed to :data:`AfterToolCallHook`."""

    assistant_message: AssistantMessage
    tool_call: ToolCall
    args: Any
    result: AgentToolResult
    is_error: bool
    context: Context


class Unset:
    """Sentinel for "field not overridden" in :class:`AfterToolCallResult`.

    Distinct from ``None`` (which is a valid ``details`` value), so every field
    supports an explicit "keep the original" default. Test with ``isinstance``.
    """


#: Module-level sentinel instance. Compare with ``is`` / test with
#: ``isinstance(value, Unset)`` (the latter narrows for mypy).
UNSET: Final[Unset] = Unset()


@dataclass
class AfterToolCallResult:
    """Partial override returned from :data:`AfterToolCallHook`.

    Merge semantics are field-by-field; any field left as :data:`UNSET` keeps
    the executed tool's original value. There is no deep merge for ``content``
    or ``details``.
    """

    content: list[UserContent] | Unset = UNSET
    details: Any = UNSET
    is_error: bool | Unset = UNSET
    terminate: bool | Unset = UNSET


#: ``before_tool_call`` hook. Receives the run's abort signal so it can honour
#: cancellation. Return ``None`` or ``block=False`` to allow; ``block=True`` to
#: prevent execution (an error tool result is emitted instead).
type BeforeToolCallHook = Callable[
    [BeforeToolCallContext, asyncio.Event],
    Awaitable[BeforeToolCallResult | None],
]

#: ``after_tool_call`` hook. Return an :class:`AfterToolCallResult` to override
#: parts of the executed result, or ``None`` to keep it unchanged.
type AfterToolCallHook = Callable[
    [AfterToolCallContext, asyncio.Event],
    Awaitable[AfterToolCallResult | None],
]


# --------------------------------------------------------------------------- #
# Hooks: per-turn decisions
# --------------------------------------------------------------------------- #


@dataclass
class ShouldStopAfterTurnContext:
    """Context passed to :data:`ShouldStopAfterTurnHook` and
    :data:`PrepareNextTurnHook` (they share a shape, like pi's
    ``PrepareNextTurnContext`` extends ``ShouldStopAfterTurnContext``)."""

    #: The assistant message that completed the turn.
    message: AssistantMessage
    #: Tool-result messages produced by the turn (empty if none).
    tool_results: list[ToolResultMessage]
    #: Live conversation view after the turn's message and tool results.
    context: Context
    #: Items added during this run so far (the slice ``AgentEndEvent`` reports
    #: if the run exits now).
    new_items: list[ContextItem]


#: Alias keeping the pi-style name for the prepare hook's context argument.
PrepareNextTurnContext = ShouldStopAfterTurnContext


@dataclass
class PrepareNextTurnResult:
    """Return from :data:`PrepareNextTurnHook`.

    **Context-view-only.** If ``context`` is provided the agent adopts it as
    its conversation view for subsequent hook contexts and ``agent.context``;
    subsequent :class:`~otter_ai_core.model_session.ContextItemAddedEvent`
    observations keep appending to it. This cannot alter what a Realtime server
    has stored (the server owns the conversation) — its realistic use is
    agent-side transcript management (e.g. compacting the local view) for the
    local-adapter case. Per-turn model/thinking swap is intentionally absent
    (a session is bound to one model at connect).
    """

    context: Context | None = None


#: Return ``True`` from ``should_stop_after_turn`` to end the run after the
#: current turn (before polling steering/follow-up queues). Fast decision
#: function; does not receive the abort signal.
type ShouldStopAfterTurnHook = Callable[[ShouldStopAfterTurnContext], Awaitable[bool]]

#: Return a :class:`PrepareNextTurnResult` to swap the agent's context view
#: before the next turn, or ``None`` to keep it.
type PrepareNextTurnHook = Callable[
    [PrepareNextTurnContext], Awaitable[PrepareNextTurnResult | None]
]


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


@dataclass
class AgentConfig:
    """Configuration handed to an :class:`~otter_ai_agent.Agent`.

    Tools, the batch execution strategy, and the optional hooks. Steering and
    follow-up queue drain modes are configured here and realized by the
    :class:`~otter_ai_agent.Agent`.
    """

    tools: list[AgentTool] = field(default_factory=list)
    tool_execution: ToolExecutionMode = "parallel"
    before_tool_call: BeforeToolCallHook | None = None
    after_tool_call: AfterToolCallHook | None = None
    should_stop_after_turn: ShouldStopAfterTurnHook | None = None
    prepare_next_turn: PrepareNextTurnHook | None = None
    steering_mode: QueueMode = "one-at-a-time"
    follow_up_mode: QueueMode = "one-at-a-time"
