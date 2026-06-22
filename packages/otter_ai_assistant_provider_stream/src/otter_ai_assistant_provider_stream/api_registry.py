"""Api stream-function registry.

Dispatch layer keyed on the ``api`` string. Mirrors pi-ai's
``api-registry.ts`` (single-function variant — otter has no ``streamSimple``
split yet). Seeded with ``"chat-completions"`` ->
:func:`otter_ai_chat_completions.create_chat_completions_assistant_message_stream`
by :func:`register_built_ins`.

A future provider package (e.g. an otter ``anthropic`` package) would
register its own ``AssistantMessageStreamFn`` here under a new api string,
without this package changing.
"""

from __future__ import annotations

from typing import Any

from otter_ai_core import AssistantMessageStreamFn

#: Module-level registry: api -> stream fn.
# ``AssistantMessageStreamFn`` is generic in ``TOptions``; the registry holds fns
# for heterogeneous option bundles, so the option slot is ``Any``.
_api_fns: dict[str, AssistantMessageStreamFn[Any]] = {}


def register_api_stream_fn(
    api: str,
    fn: AssistantMessageStreamFn[Any],
) -> None:
    """Register (or overwrite) the stream fn for an api string."""
    _api_fns[api] = fn


def get_api_stream_fn(
    api: str,
) -> AssistantMessageStreamFn[Any] | None:
    """Look up the stream fn registered for ``api``."""
    return _api_fns.get(api)


def list_apis() -> list[str]:
    """All registered api strings."""
    return list(_api_fns)


def clear_api_fns() -> None:
    """Remove every api stream fn."""
    _api_fns.clear()


__all__ = [
    "clear_api_fns",
    "get_api_stream_fn",
    "list_apis",
    "register_api_stream_fn",
]
