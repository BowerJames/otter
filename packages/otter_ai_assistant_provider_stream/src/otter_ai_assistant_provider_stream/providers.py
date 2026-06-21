"""Provider-config registry.

A small ``dict`` keyed on provider name. Built-in entries (``openai``,
``zai``) are seeded by :func:`register_built_ins`; additional entries are
added at runtime via :func:`register_provider`.

This is the provider-level "template" layer (identity + env var + default
api), distinct from the model catalog (per-model facts) and the api
stream-fn registry (dispatch). It mirrors the static per-provider facts
pi-ai bakes into its generated catalog + ``env-api-keys.ts``.
"""

from __future__ import annotations

from otter_ai_assistant_provider_stream.types import (
    BUILT_IN_PROVIDERS,
    DEFAULT_API,
    ProviderConfig,
)

#: Module-level registry: provider name -> config.
_providers: dict[str, ProviderConfig] = {}


def register_provider(config: ProviderConfig) -> None:
    """Register (or overwrite) a provider config."""
    _providers[config.name] = config


def get_provider(name: str) -> ProviderConfig | None:
    """Look up a provider config by name."""
    return _providers.get(name)


def unregister_provider(name: str) -> None:
    """Remove a provider config (no-op if absent)."""
    _providers.pop(name, None)


def list_providers() -> list[str]:
    """Names of all registered providers."""
    return list(_providers)


def built_in_provider_configs() -> dict[str, ProviderConfig]:
    """The built-in provider configs (used by :func:`register_built_ins`)."""
    return {
        "openai": ProviderConfig(
            name="openai", env_key="OPENAI_API_KEY", api=DEFAULT_API
        ),
        "zai": ProviderConfig(name="zai", env_key="ZAI_API_KEY", api=DEFAULT_API),
    }


def clear_providers() -> None:
    """Remove every provider config."""
    _providers.clear()


# Sanity: the built-in config map and BUILT_IN_PROVIDERS must agree.
assert set(built_in_provider_configs()) == set(BUILT_IN_PROVIDERS)


__all__ = [
    "built_in_provider_configs",
    "clear_providers",
    "get_provider",
    "list_providers",
    "register_provider",
    "unregister_provider",
]
