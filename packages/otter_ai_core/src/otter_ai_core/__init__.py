"""Otter AI — LLM context data model and generic channel runtimes.

This package provides:

* a Pydantic v2 model for representing LLM conversation context (``Context``,
  messages, content blocks, tools, usage);
* a provider-agnostic async channel runtime (``ChannelReader`` /
  ``ChannelWriter`` / ``create_channel``);
* a provider-agnostic async **abortable stream** runtime layered over the
  channel (``StreamClient`` / ``StreamBackend`` / ``create_stream``) — a
  consumer handle that can *iterate* **and** *abort*; and
* a provider-agnostic async bidirectional-channel runtime
  (``BidirectionalChannel`` / ``BidirectionalChannelBackend`` /
  ``create_bidirectional_channel``), the bidirectional peer of the one-way
  channel runtime for APIs that maintain a live connection (Realtime / Responses).

The assistant-message-stream **event protocol** (the ``AssistantMessageEvent``
family) and the **typed stream aliases** (``AssistantMessageStreamClient`` /
``AssistantMessageStreamBackend`` / the ``AssistantMessageStreamFnBuilder`` seam)
live under the :mod:`otter_ai_core.assistant_message_stream` subpackage, not at
the top level. The ``BidirectionalChannelFn`` seam type — the bidirectional peer
of ``AssistantMessageStreamFnBuilder`` — is defined alongside the
bidirectional-channel runtime in :mod:`otter_ai_core.bidirectional_channel`.
The generic :data:`BuilderFn` alias — the common
options-binding shape that both producer seams specialize — lives in
:mod:`otter_ai_core.builder`.

It defines **no LLMs, providers, APIs, transports, API registry, or
``stream()`` dispatch** — only the data model and the generic runtimes.
"""

from __future__ import annotations

from otter_ai_core.bidirectional_channel import (
    BidirectionalChannel,
    BidirectionalChannelBackend,
    BidirectionalChannelFn,
    BidirectionalChannelWiring,
    create_bidirectional_channel,
)
from otter_ai_core.builder import BuilderFn
from otter_ai_core.channel import (
    ChannelPair,
    ChannelReader,
    ChannelWriter,
    create_channel,
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
    Tool,
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
from otter_ai_core.provider_api_model_options import (
    KnownApis,
    KnownProviders,
    ProviderModelOption,
    ThinkingLevel,
)
from otter_ai_core.stream import (
    StreamBackend,
    StreamClient,
    StreamPair,
    create_stream,
)

__version__ = "0.1.0"

__all__ = [
    # version
    "__version__",
    # hooks
    "Hook",
    # builder
    "BuilderFn",
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
    # provider/api/model options
    "KnownApis",
    "KnownProviders",
    "ProviderModelOption",
    "ThinkingLevel",
    # channel runtime (one-way)
    "ChannelPair",
    "ChannelReader",
    "ChannelWriter",
    "create_channel",
    # stream runtime (abortable one-way facade over the channel)
    "StreamBackend",
    "StreamClient",
    "StreamPair",
    "create_stream",
    # channel runtime (bidirectional)
    "BidirectionalChannel",
    "BidirectionalChannelBackend",
    "BidirectionalChannelFn",
    "BidirectionalChannelWiring",
    "create_bidirectional_channel",
]
