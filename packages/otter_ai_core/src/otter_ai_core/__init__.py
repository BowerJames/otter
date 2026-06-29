"""Otter AI — LLM context data model and generic stream/connection runtimes.

This package provides:

* a Pydantic v2 model for representing LLM conversation context (``Context``,
  messages, content blocks, tools, usage);
* a provider-agnostic async stream runtime (``Stream`` / ``StreamWriter`` /
  ``create_stream``); and
* a provider-agnostic async bidirectional connection runtime
  (``Connection`` / ``ConnectionBackend`` / ``create_connection``), the
  bidirectional peer of the stream runtime for APIs that maintain a live
  connection (Realtime / Responses).

The assistant-message-stream **event protocol** (the ``AssistantMessageEvent``
family) and the **typed stream aliases** (``AssistantMessageStream`` /
``AssistantMessageWriter`` / the ``AssistantMessageStreamFnBuilder`` seam) live under
the :mod:`otter_ai_core.assistant_message_stream` subpackage, not at the
top level. The ``ConnectionFn`` seam type — the bidirectional peer of
``AssistantMessageStreamFnBuilder`` — is defined alongside the connection runtime in
:mod:`otter_ai_core.connection`.

It defines **no LLMs, providers, APIs, transports, API registry, or
``stream()`` dispatch** — only the data model and the generic runtimes.
"""

from __future__ import annotations

from otter_ai_core.connection import (
    Connection,
    ConnectionBackend,
    ConnectionFn,
    create_connection,
)
from otter_ai_core.context import (
    AssistantContent,
    AssistantContextItem,
    AssistantMessage,
    AssistantMessageDiagnostic,
    Context,
    ContextItem,
    DiagnosticErrorInfo,
    ImageContent,
    Message,
    StopReason,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultContextItem,
    ToolResultMessage,
    Usage,
    UsageCost,
    UserContent,
    UserContextItem,
    UserMessage,
    context_item,
)
from otter_ai_core.hook import Hook
from otter_ai_core.normalize import (
    drop_unreplayable_assistant_turns,
    fill_missing_tool_results,
    normalize_messages,
)
from otter_ai_core.stream import (
    Stream,
    StreamWriter,
    create_stream,
)
from otter_ai_core.tools import Tool, tool_from_pydantic

__version__ = "0.1.0"

__all__ = [
    # version
    "__version__",
    # hooks
    "Hook",
    # usage
    "Usage",
    "UsageCost",
    # diagnostics
    "AssistantMessageDiagnostic",
    "DiagnosticErrorInfo",
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
    "StopReason",
    "ToolResultMessage",
    "UserMessage",
    # context
    "AssistantContextItem",
    "Context",
    "ContextItem",
    "ToolResultContextItem",
    "UserContextItem",
    "context_item",
    # normalize (opt-in)
    "drop_unreplayable_assistant_turns",
    "fill_missing_tool_results",
    "normalize_messages",
    # stream runtime
    "Stream",
    "StreamWriter",
    "create_stream",
    # connection runtime
    "Connection",
    "ConnectionBackend",
    "ConnectionFn",
    "create_connection",
]
