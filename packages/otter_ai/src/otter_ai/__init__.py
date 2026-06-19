"""Otter AI — LLM context data model.

This package provides a Pydantic v2 model for representing LLM conversation
context (``Context``, messages, content blocks, tools, usage) and the streaming
events used to build it. It is data-only: no LLMs, providers, APIs, transports,
or ``stream()`` dispatch.
"""

from __future__ import annotations

from otter_ai.content import (
    AssistantContent,
    ImageContent,
    TextContent,
    ThinkingContent,
    ToolCall,
    UserContent,
)
from otter_ai.context import Context
from otter_ai.diagnostics import (
    AssistantMessageDiagnostic,
    DiagnosticErrorInfo,
)
from otter_ai.events import (
    AssistantDoneEvent,
    AssistantDoneReason,
    AssistantErrorEvent,
    AssistantMessageEvent,
    AssistantStartEvent,
    AssistantTextDeltaEvent,
    AssistantTextEndEvent,
    AssistantTextStartEvent,
    AssistantThinkingDeltaEvent,
    AssistantThinkingEndEvent,
    AssistantThinkingStartEvent,
    AssistantToolCallDeltaEvent,
    AssistantToolCallEndEvent,
    AssistantToolCallStartEvent,
    ContextItemEvent,
    EventErrorReason,
    ToolResultDoneEvent,
    ToolResultErrorEvent,
    ToolResultMessageEvent,
    ToolResultStartEvent,
    ToolResultTextDeltaEvent,
    ToolResultTextEndEvent,
    ToolResultTextStartEvent,
    UserDoneEvent,
    UserErrorEvent,
    UserMessageEvent,
    UserStartEvent,
    UserTextDeltaEvent,
    UserTextEndEvent,
    UserTextStartEvent,
)
from otter_ai.messages import (
    AssistantMessage,
    Message,
    ToolResultMessage,
    UserMessage,
)
from otter_ai.normalize import (
    drop_unreplayable_assistant_turns,
    fill_missing_tool_results,
    normalize_messages,
)
from otter_ai.tools import Tool, tool_from_pydantic
from otter_ai.types import Api, Provider, StopReason
from otter_ai.usage import Usage, UsageCost

__version__ = "0.1.0"

__all__ = [
    # version
    "__version__",
    # metadata / literals
    "Api",
    "Provider",
    "StopReason",
    # usage
    "Usage",
    "UsageCost",
    # diagnostics
    "AssistantMessageDiagnostic",
    "DiagnosticErrorInfo",
    # events
    "AssistantDoneEvent",
    "AssistantDoneReason",
    "AssistantErrorEvent",
    "AssistantMessageEvent",
    "AssistantStartEvent",
    "AssistantTextDeltaEvent",
    "AssistantTextEndEvent",
    "AssistantTextStartEvent",
    "AssistantThinkingDeltaEvent",
    "AssistantThinkingEndEvent",
    "AssistantThinkingStartEvent",
    "AssistantToolCallDeltaEvent",
    "AssistantToolCallEndEvent",
    "AssistantToolCallStartEvent",
    "ContextItemEvent",
    "EventErrorReason",
    "ToolResultDoneEvent",
    "ToolResultErrorEvent",
    "ToolResultMessageEvent",
    "ToolResultStartEvent",
    "ToolResultTextDeltaEvent",
    "ToolResultTextEndEvent",
    "ToolResultTextStartEvent",
    "UserDoneEvent",
    "UserErrorEvent",
    "UserMessageEvent",
    "UserStartEvent",
    "UserTextDeltaEvent",
    "UserTextEndEvent",
    "UserTextStartEvent",
    # content
    "AssistantContent",
    "ImageContent",
    "TextContent",
    "ThinkingContent",
    "ToolCall",
    "UserContent",
    # tools
    "Tool",
    "tool_from_pydantic",
    # messages
    "AssistantMessage",
    "Message",
    "ToolResultMessage",
    "UserMessage",
    # context
    "Context",
    # normalize (opt-in)
    "drop_unreplayable_assistant_turns",
    "fill_missing_tool_results",
    "normalize_messages",
]
