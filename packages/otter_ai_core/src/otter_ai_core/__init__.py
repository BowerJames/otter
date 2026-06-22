"""Otter AI — LLM context data model and generic stream runtime.

This package provides:

* a Pydantic v2 model for representing LLM conversation context (``Context``,
  messages, content blocks, tools, usage) and the streaming events used to
  build it; and
* a provider-agnostic async stream runtime (``Stream`` / ``StreamWriter`` /
  ``create_stream``) plus the typed message-stream aliases a provider package
  built on top will import.

It defines **no LLMs, providers, APIs, transports, API registry, or
``stream()`` dispatch** — only the data model, the event protocol, and the
generic stream runtime.
"""

from __future__ import annotations

from otter_ai_core.content import (
    AssistantContent,
    ImageContent,
    TextContent,
    ThinkingContent,
    ToolCall,
    UserContent,
)
from otter_ai_core.context import Context
from otter_ai_core.diagnostics import (
    AssistantMessageDiagnostic,
    DiagnosticErrorInfo,
)
from otter_ai_core.events import (
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
    MessageEvent,
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
from otter_ai_core.hook import Hook
from otter_ai_core.messages import (
    AssistantMessage,
    Message,
    ToolResultMessage,
    UserMessage,
)
from otter_ai_core.normalize import (
    drop_unreplayable_assistant_turns,
    fill_missing_tool_results,
    normalize_messages,
)
from otter_ai_core.stream import (
    AssistantMessageStream,
    AssistantMessageStreamFn,
    AssistantMessageWriter,
    ContextItemStream,
    ContextItemWriter,
    MessageEventStream,
    MessageEventWriter,
    Stream,
    StreamWriter,
    UserMessageStream,
    UserMessageWriter,
    create_stream,
)
from otter_ai_core.tools import Tool, tool_from_pydantic
from otter_ai_core.types import Api, Provider, StopReason
from otter_ai_core.usage import Usage, UsageCost

__version__ = "0.1.0"

__all__ = [
    # version
    "__version__",
    # metadata / literals
    "Api",
    "Provider",
    "StopReason",
    # hooks
    "Hook",
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
    "MessageEvent",
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
    # stream runtime + aliases
    "Stream",
    "StreamWriter",
    "create_stream",
    "AssistantMessageStream",
    "AssistantMessageStreamFn",
    "UserMessageStream",
    "MessageEventStream",
    "ContextItemStream",
    "AssistantMessageWriter",
    "UserMessageWriter",
    "MessageEventWriter",
    "ContextItemWriter",
]
