"""Model-connection-builder registry.

Dispatch layer keyed on the ``api`` enum
(:class:`~otter_ai_core.KnownApis`). The connection-side peer of the old
api stream-fn registry: instead of mapping an api string to an
:data:`~otter_ai_core.assistant_message_stream.AssistantMessageStreamFnBuilder`
it maps it to a
:data:`~otter_ai_core.model_connection.ModelConnectionFnBuilder`
parameterised by the pure-data
:class:`~otter_ai_core.ProviderModelOption` bundle.

Seeded with two built-ins by :func:`register_built_ins`:

* :data:`~otter_ai_core.KnownApis.ChatCompletion` — the chat-completions
  builder (resolves a catalog model, builds a chat-completions
  :data:`~otter_ai_core.assistant_message_stream.AssistantMessageStreamFn`,
  and adapts it to a :data:`~otter_ai_core.model_connection.ModelConnectionFn`
  via
  :func:`otter_ai_assistant_stream_model_connection.create_assistant_stream_model_connection`).
* :data:`~otter_ai_core.KnownApis.Realtime` — the realtime builder (resolves a
  realtime catalog model and delegates to
  :func:`otter_ai_realtime.create_realtime_model_connection`).

A future provider package would register its own
``ModelConnectionFnBuilder[ProviderModelOption]`` here under a new api
(extended by adding a :class:`~otter_ai_core.KnownApis` member), without this
package changing.
"""

from __future__ import annotations

from otter_ai_core import KnownApis, ProviderModelOption
from otter_ai_core.model_connection import ModelConnectionFnBuilder

#: Module-level registry: api -> connection builder.
_builders: dict[KnownApis, ModelConnectionFnBuilder[ProviderModelOption]] = {}


def register_model_connection_builder(
    api: KnownApis,
    builder: ModelConnectionFnBuilder[ProviderModelOption],
) -> None:
    """Register (or overwrite) the connection builder for an api."""
    _builders[api] = builder


def get_model_connection_builder(
    api: KnownApis,
) -> ModelConnectionFnBuilder[ProviderModelOption] | None:
    """Look up the connection builder registered for ``api``."""
    return _builders.get(api)


def list_model_connection_builders() -> list[KnownApis]:
    """All apis with a registered connection builder."""
    return list(_builders)


def clear_model_connection_builders() -> None:
    """Remove every connection builder."""
    _builders.clear()


__all__ = [
    "clear_model_connection_builders",
    "get_model_connection_builder",
    "list_model_connection_builders",
    "register_model_connection_builder",
]
