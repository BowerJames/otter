"""otter-ai-agent — the agent loop over a :class:`ModelSession`.

This package is the *turn* / *tool-execution* layer that sits above
``otter_ai_core``'s reactive :class:`~otter_ai_core.model_session.ModelSession`.

It ports the agent-loop semantics of pi's ``@earendil-works/pi-agent-core``
(turn loop, sequential/parallel tool execution, steering/follow-up queues,
``before_tool_call`` / ``after_tool_call`` hooks) onto otter's **reactive**
session model — and runs unchanged over a Realtime WebSocket *or* a wrapped
chat-completions stream, because it depends only on the session abstraction.
"""

from __future__ import annotations

from otter_ai_agent.agent import Agent
from otter_ai_agent.bus import AgentBus
from otter_ai_agent.events import (
    AgentEndEvent,
    AgentEvent,
    AgentEventType,
    AgentStartEvent,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    ToolExecutionUpdateEvent,
    TurnEndEvent,
    TurnStartEvent,
)
from otter_ai_agent.tools import execute_tool_calls
from otter_ai_agent.types import (
    AfterToolCallContext,
    AfterToolCallHook,
    AfterToolCallResult,
    AgentConfig,
    AgentExecute,
    AgentTool,
    AgentToolResult,
    AgentToolUpdateCallback,
    BeforeToolCallContext,
    BeforeToolCallHook,
    BeforeToolCallResult,
    PrepareNextTurnContext,
    PrepareNextTurnHook,
    QueueMode,
    ShouldStopAfterTurnContext,
    ShouldStopAfterTurnHook,
    ToolExecutionMode,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # agent + bus
    "Agent",
    "AgentBus",
    # events
    "AgentEvent",
    "AgentEventType",
    "AgentStartEvent",
    "AgentEndEvent",
    "TurnStartEvent",
    "TurnEndEvent",
    "MessageStartEvent",
    "MessageUpdateEvent",
    "MessageEndEvent",
    "ToolExecutionStartEvent",
    "ToolExecutionUpdateEvent",
    "ToolExecutionEndEvent",
    # queues
    "QueueMode",
    # tools
    "execute_tool_calls",
    # types
    "AgentTool",
    "AgentToolResult",
    "AgentToolUpdateCallback",
    "AgentExecute",
    "AgentConfig",
    "ToolExecutionMode",
    "BeforeToolCallContext",
    "BeforeToolCallResult",
    "BeforeToolCallHook",
    "AfterToolCallContext",
    "AfterToolCallResult",
    "AfterToolCallHook",
    "ShouldStopAfterTurnContext",
    "ShouldStopAfterTurnHook",
    "PrepareNextTurnContext",
    "PrepareNextTurnHook",
]
