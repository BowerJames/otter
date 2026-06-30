"""otter-ai-assistant-stream-model-connection — pure-local adapter.

Defines the single seam
:func:`create_assistant_stream_model_connection`, a concrete implementation of
:data:`otter_ai_core.model_connection.ModelConnectionFnBuilder` whose
``TOptions`` is
:data:`~otter_ai_core.assistant_message_stream.AssistantMessageStreamFn`.

It wraps any assistant-stream producer as a fully-functional, request-driven,
multi-turn :data:`~otter_ai_core.model_connection.ModelConnection`: a caller
iterates inbound :data:`~otter_ai_core.model_connection.ServerEvent` s and
sends :data:`~otter_ai_core.model_connection.ClientEvent` s to drive
generations, exactly as against a Realtime connection — but the backend is the
supplied ``stream_fn`` running locally. No transport, provider, registry, or
dispatch (consistent with otter's layering).
"""

from __future__ import annotations

from otter_ai_assistant_stream_model_connection.connection import (
    create_assistant_stream_model_connection,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "create_assistant_stream_model_connection",
]
