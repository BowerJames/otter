"""Model-catalog registry.

A registry of :class:`~otter_ai_chat_completions.ChatCompletionsModel`
entries keyed on ``(provider, model_id)``. Built-in entries are loaded from
the committed :mod:`_catalog_generated` module (regenerated on demand from
models.dev); additional entries are registered at runtime via
:func:`register_model`.

Mirrors pi-ai's ``modelRegistry`` (``models.ts``) seeded from
``models.generated.ts``. As in pi-ai, a later registration overwrites an
earlier one — generated built-ins can be overridden by runtime callers.
"""

from __future__ import annotations

from otter_ai_chat_completions import ChatCompletionsModel

#: Module-level registry: (provider, model_id) -> model.
_catalog: dict[tuple[str, str], ChatCompletionsModel] = {}


def register_model(model: ChatCompletionsModel) -> None:
    """Register (or overwrite) a catalog model.

    Keyed on ``(provider, id)``; a later call for the same key wins (pi-ai
    "models.dev has priority" / runtime-override semantics).
    """
    _catalog[(model.provider, model.id)] = model


def get_model(provider: str, model_id: str) -> ChatCompletionsModel | None:
    """Look up a catalog model by ``(provider, model_id)``."""
    return _catalog.get((provider, model_id))


def list_models(provider: str) -> list[ChatCompletionsModel]:
    """All catalog models for ``provider``."""
    return [model for (p, _), model in _catalog.items() if p == provider]


def all_models() -> list[ChatCompletionsModel]:
    """Every registered catalog model."""
    return list(_catalog.values())


def clear_catalog() -> None:
    """Remove every catalog entry."""
    _catalog.clear()


def load_generated_catalog() -> int:
    """Validate and register every entry from :mod:`_catalog_generated`.

    Returns the number of models registered. Called once by
    :func:`register_built_ins`; idempotent if the registry is cleared first.
    """
    # Imported lazily so test fixtures that swap the generated data do not
    # pay the import cost unless the catalog is (re)loaded.
    from otter_ai_assistant_provider_stream._catalog_generated import CATALOG

    count = 0
    for entry in CATALOG:
        register_model(ChatCompletionsModel.model_validate(entry))
        count += 1
    return count


__all__ = [
    "all_models",
    "clear_catalog",
    "get_model",
    "list_models",
    "load_generated_catalog",
    "register_model",
]
