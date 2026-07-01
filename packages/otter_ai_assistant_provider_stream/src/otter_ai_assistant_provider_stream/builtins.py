"""Built-in registration: seeds all registries.

Mirrors pi-ai's ``register-builtins.ts`` (the auto-registration half — otter
has no lazy dynamic-import provider modules yet). Called once at the bottom
of :mod:`__init__` so importing the package makes ``openai`` and ``zai`` work
immediately, and exposed as :func:`reset` for tests that need to restore a
clean built-in-only state.

Five registries are seeded:

* providers (openai, zai) — identity + env key + default api;
* the chat-completions model catalog (committed models.dev snapshot);
* the realtime model catalog (hand-curated);
* the connection-builder registry
  (:data:`~otter_ai_core.KnownApis.ChatCompletion` -> the chat-completions
  builder and :data:`~otter_ai_core.KnownApis.Realtime` -> the realtime
  builder).
"""

from __future__ import annotations

from otter_ai_assistant_provider_stream.catalog import (
    clear_catalog,
    load_generated_catalog,
)
from otter_ai_assistant_provider_stream.connection import (
    _chat_completions_connection_builder,
    _realtime_connection_builder,
)
from otter_ai_assistant_provider_stream.connection_registry import (
    clear_model_connection_builders,
    get_model_connection_builder,
    register_model_connection_builder,
)
from otter_ai_assistant_provider_stream.providers import (
    built_in_provider_configs,
    clear_providers,
    register_provider,
)
from otter_ai_assistant_provider_stream.realtime_catalog import (
    clear_realtime_catalog,
    load_generated_realtime_catalog,
)
from otter_ai_core import KnownApis


def register_built_ins() -> None:
    """Seed the provider, catalog, and connection-builder registries with
    built-ins.

    Idempotent: each registry is populated with the built-in values, with
    later registrations overwriting earlier ones. Safe to call repeatedly.
    """
    # Provider configs (openai, zai).
    for config in built_in_provider_configs().values():
        register_provider(config)

    # Chat-completions model catalog (committed models.dev snapshot).
    load_generated_catalog()

    # Realtime model catalog (hand-curated).
    load_generated_realtime_catalog()

    # Connection builders: chat-completions (via the local adapter) + realtime.
    register_model_connection_builder(
        KnownApis.ChatCompletion, _chat_completions_connection_builder
    )
    register_model_connection_builder(KnownApis.Realtime, _realtime_connection_builder)


def get_chat_completions_builder() -> object | None:
    """The connection builder currently registered for chat-completions."""
    return get_model_connection_builder(KnownApis.ChatCompletion)


def get_realtime_builder() -> object | None:
    """The connection builder currently registered for realtime."""
    return get_model_connection_builder(KnownApis.Realtime)


def reset() -> None:
    """Clear every registry and re-register built-ins only.

    Restores the package to a clean built-in-only state (used by tests).
    """
    clear_model_connection_builders()
    clear_catalog()
    clear_realtime_catalog()
    clear_providers()
    register_built_ins()


__all__ = [
    "get_chat_completions_builder",
    "get_realtime_builder",
    "register_built_ins",
    "reset",
]
