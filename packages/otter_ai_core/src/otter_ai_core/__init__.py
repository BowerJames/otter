"""Otter AI — LLM context data model and generic channel runtimes.

This package provides:

* a Pydantic v2 model for representing LLM conversation context (``Context``,
  messages, content blocks, tools, usage);
* a provider-agnostic async channel runtime (``ChannelReader`` /
  ``ChannelWriter`` / ``create_channel``);
* a provider-agnostic async **abortable stream** runtime layered over the
  channel (``StreamClient`` / ``StreamBackend`` / ``create_stream``) — a
  one-way consumer handle that can *iterate* **and** *abort*;
* a provider-agnostic async **bidirectional-channel** runtime
  (``BidirectionalChannelClient`` / ``BidirectionalChannelBackend`` /
  ``create_bidirectional_channel``) — the two-way queue primitive for APIs
  that maintain a live connection (Realtime / Responses); and
* a provider-agnostic async **abortable connection** runtime layered over the
  bidirectional channel (``ConnectionClient`` / ``ConnectionBackend`` /
  ``create_connection``) — a two-way consumer handle that can *iterate*,
  *push*, **and** *abort*, the bidirectional peer of the one-way stream.

The assistant-message-stream **event protocol** (the ``AssistantMessageEvent``
family) and the **typed one-way stream aliases** (``AssistantMessageStreamClient``
/ ``AssistantMessageStreamBackend`` / the ``AssistantMessageStreamFnBuilder``
seam) live under the :mod:`otter_ai_core.assistant_message_stream` subpackage,
not at the top level. Their bidirectional peers — the model-connection **event
protocol** (``ClientContextEvent`` / ``ServerContextEvent``) and the **typed
two-way connection aliases** (``ModelConnectionClient`` /
``ModelConnectionBackend``) — live under the
:mod:`otter_ai_core.model_connection` subpackage. The generic
:data:`BuilderFn` alias — the common options-binding shape a producer seam
specializes — lives in :mod:`otter_ai_core.builder`.

It defines **no LLMs, providers, APIs, transports, API registry, or
``stream()`` dispatch** — only the data model and the generic runtimes. No
producer-side seam type is defined for the bidirectional/connection runtime
yet; a connection-level seam will be added in a future dispatch package.
"""

from __future__ import annotations

from otter_ai_core.bidirectional_channel import (
    BidirectionalChannelBackend,
    BidirectionalChannelClient,
    BidirectionalChannelPair,
    create_bidirectional_channel,
)
from otter_ai_core.builder import BuilderFn
from otter_ai_core.channel import (
    ChannelPair,
    ChannelReader,
    ChannelWriter,
    create_channel,
)
from otter_ai_core.connection import (
    ConnectionBackend,
    ConnectionClient,
    ConnectionPair,
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
from otter_ai_core.model_controller import ModelController, State
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
    # channel runtime (bidirectional primitive)
    "BidirectionalChannelClient",
    "BidirectionalChannelBackend",
    "BidirectionalChannelPair",
    "create_bidirectional_channel",
    # connection runtime (abortable bidirectional facade over the channel)
    "ConnectionClient",
    "ConnectionBackend",
    "ConnectionPair",
    "create_connection",
    # model controller (high-level conversation driver over a connection;
    # re-exported at the top level, unlike the subpackage-only model_connection)
    "ModelController",
    "State",
]
