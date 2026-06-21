"""Built-in registration: seeds all three registries.

Mirrors pi-ai's ``register-builtins.ts`` (the auto-registration half — otter
has no lazy dynamic-import provider modules yet). Called once at the bottom
of :mod:`__init__` so importing the package makes ``openai`` and ``zai``
work immediately, and exposed as :func:`reset` for tests that need to
restore a clean built-in-only state.
"""

from __future__ import annotations

from typing import Any

from otter_ai import AssistantMessageStreamFn
from otter_ai_assistant_provider_stream.api_registry import (
    clear_api_fns,
    get_api_stream_fn,
    register_api_stream_fn,
)
from otter_ai_assistant_provider_stream.catalog import (
    clear_catalog,
    load_generated_catalog,
)
from otter_ai_assistant_provider_stream.providers import (
    built_in_provider_configs,
    clear_providers,
    register_provider,
)
from otter_ai_assistant_provider_stream.types import DEFAULT_API
from otter_ai_chat_completions import create_chat_completions_assistant_message_stream

#: The default chat-completions stream fn registered under ``DEFAULT_API``.
_DEFAULT_STREAM_FN: AssistantMessageStreamFn[Any] = (
    create_chat_completions_assistant_message_stream
)


def register_built_ins() -> None:
    """Seed the provider, catalog, and api registries with built-ins.

    Idempotent: each registry is populated with the built-in values, with
    later registrations overwriting earlier ones. Safe to call repeatedly.
    """
    # Provider configs (openai, zai).
    for config in built_in_provider_configs().values():
        register_provider(config)

    # Model catalog (committed models.dev snapshot, validated into models).
    load_generated_catalog()

    # Api stream fn (chat-completions -> the chat-completions seam).
    if get_default_api_stream_fn() is None:
        register_api_stream_fn(DEFAULT_API, _DEFAULT_STREAM_FN)


def get_default_api_stream_fn() -> AssistantMessageStreamFn[Any] | None:
    """The stream fn currently registered under :data:`DEFAULT_API`."""
    return get_api_stream_fn(DEFAULT_API)


def reset() -> None:
    """Clear all three registries and re-register built-ins only.

    Restores the package to a clean built-in-only state (used by tests).
    """
    clear_api_fns()
    clear_catalog()
    clear_providers()
    register_built_ins()


__all__ = [
    "get_default_api_stream_fn",
    "register_built_ins",
    "reset",
]
