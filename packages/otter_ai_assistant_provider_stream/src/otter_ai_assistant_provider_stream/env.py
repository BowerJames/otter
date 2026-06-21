"""API-key env-var resolution.

Mirrors the string-key branch of pi-ai's ``env-api-keys.ts``. Only the two
built-in providers ship a default env var; additional providers get env
resolution via the :class:`~.types.ProviderConfig.env_key` they register.

Ambient-credential sources (AWS profiles, Google ADC) from pi-ai are
intentionally **not** ported — out of scope for the chat-completions-only
providers this package ships.
"""

from __future__ import annotations

import os

from otter_ai_assistant_provider_stream.providers import get_provider

#: Built-in provider -> env-var map. Mirrors pi-ai's ``getApiKeyEnvVars`` for
#: the two providers this package supports. Registered providers declare their
#: own ``env_key`` on their :class:`~.types.ProviderConfig`.
_BUILT_IN_ENV_KEYS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "zai": "ZAI_API_KEY",
}


def find_env_keys(provider: str) -> list[str] | None:
    """Env vars configured (present in ``os.environ``) for ``provider``.

    Returns the list of env vars that are both declared for the provider and
    currently set, or ``None`` if none apply. Built-in providers use
    :data:`_BUILT_IN_ENV_KEYS`; registered providers use their ``env_key``.
    """
    declared: list[str] = []
    if provider in _BUILT_IN_ENV_KEYS:
        declared.append(_BUILT_IN_ENV_KEYS[provider])
    config = get_provider(provider)
    if config is not None and config.env_key is not None:
        if config.env_key not in declared:
            declared.append(config.env_key)

    found = [key for key in declared if os.environ.get(key)]
    return found or None


def get_env_api_key(provider: str) -> str | None:
    """Resolve an API key for ``provider`` from the environment.

    Returns the value of the first declared env var that is set, or ``None``
    if none are set. Built-in providers use :data:`_BUILT_IN_ENV_KEYS`;
    registered providers use their ``env_key``.
    """
    keys = find_env_keys(provider)
    if not keys:
        return None
    return os.environ.get(keys[0])


__all__ = ["find_env_keys", "get_env_api_key"]
