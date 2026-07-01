"""Realtime model-catalog registry.

A registry of :class:`~otter_ai_realtime.RealtimeModel` entries keyed on
``(provider, model_id)``. Built-in entries are loaded from the committed
:mod:`_realtime_catalog_generated` module (hand-curated — see
``scripts/generate_models.py``; models.dev carries no first-party realtime
models for ``openai``/``zai``); additional entries are registered at runtime
via :func:`register_realtime_model`.

This is the realtime peer of :mod:`catalog` (which holds
:class:`~otter_ai_chat_completions.ChatCompletionsModel` entries). As in
:mod:`catalog`, a later registration overwrites an earlier one — generated
built-ins can be overridden by runtime callers.
"""

from __future__ import annotations

from otter_ai_realtime import RealtimeModel

#: Module-level registry: (provider, model_id) -> realtime model.
_catalog: dict[tuple[str, str], RealtimeModel] = {}


def register_realtime_model(model: RealtimeModel) -> None:
    """Register (or overwrite) a realtime catalog model.

    Keyed on ``(provider, id)``; a later call for the same key wins.
    """
    _catalog[(model.provider, model.id)] = model


def get_realtime_model(provider: str, model_id: str) -> RealtimeModel | None:
    """Look up a realtime catalog model by ``(provider, model_id)``."""
    return _catalog.get((provider, model_id))


def list_realtime_models(provider: str) -> list[RealtimeModel]:
    """All realtime catalog models for ``provider``."""
    return [model for (p, _), model in _catalog.items() if p == provider]


def all_realtime_models() -> list[RealtimeModel]:
    """Every registered realtime catalog model."""
    return list(_catalog.values())


def clear_realtime_catalog() -> None:
    """Remove every realtime catalog entry."""
    _catalog.clear()


def load_generated_realtime_catalog() -> int:
    """Validate and register every entry from :mod:`_realtime_catalog_generated`.

    Returns the number of models registered. Called once by
    :func:`register_built_ins`; idempotent if the registry is cleared first.
    """
    # Imported lazily so test fixtures that swap the generated data do not
    # pay the import cost unless the catalog is (re)loaded.
    from otter_ai_assistant_provider_stream._realtime_catalog_generated import (
        REALTIME_CATALOG,
    )

    count = 0
    for entry in REALTIME_CATALOG:
        register_realtime_model(RealtimeModel.model_validate(entry))
        count += 1
    return count


__all__ = [
    "all_realtime_models",
    "clear_realtime_catalog",
    "get_realtime_model",
    "list_realtime_models",
    "load_generated_realtime_catalog",
    "register_realtime_model",
]
