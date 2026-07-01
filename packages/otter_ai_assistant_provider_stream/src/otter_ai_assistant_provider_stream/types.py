"""Public types for the assistant-provider-stream package.

Defines the provider-registry entry (:class:`ProviderConfig`) and the
built-in provider names. The caller-facing selection bundle
(:class:`~otter_ai_core.ProviderModelOption`) and the thinking-level enum
(:class:`~otter_ai_core.ThinkingLevel`) live in
:mod:`otter_ai_core` and are re-exported by this package.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from otter_ai_core import KnownApis

#: The built-in provider names this package ships model-catalog data and
#: env-key resolution for. Additional providers are registered at runtime via
#: :func:`otter_ai_assistant_provider_stream.register_provider`.
BUILT_IN_PROVIDERS: list[str] = ["zai", "openai"]


class ProviderConfig(BaseModel):
    """Registry entry for a provider: identity + env-key + default api.

    Built-in entries are seeded by :func:`register_built_ins`; additional
    entries are added via :func:`register_provider`. The ``env_key`` is read
    by :func:`get_env_api_key`; the ``api`` documents the provider's default
    api (dispatch itself routes on the caller's
    :class:`~otter_ai_core.ProviderModelOption.api`).
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    #: Environment variable read by :func:`get_env_api_key` when the caller
    #: does not pass an explicit ``api_key``. ``None`` disables env resolution.
    env_key: str | None = None
    #: The provider's default api. Defaults to chat-completions.
    api: KnownApis = KnownApis.ChatCompletion
