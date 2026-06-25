"""Public types for the assistant-provider-stream package.

Defines the caller-facing config (``ModelProviderConfig`` /
``ModelProviderOptions``) plus the small registry entry types
(``ProviderConfig``) and the ``ThinkingLevel`` literal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from otter_ai_chat_completions import ChatCompletionsCompat, ChatCompletionsHooks

#: pi-ai's ``ModelThinkingLevel``: the union of the off switch and the five
#: reasoning-effort levels. ``off`` means "do not send any reasoning field".
ThinkingLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh"]

#: The built-in provider names this package ships model catalog data and
#: env-key resolution for. Additional providers are registered at runtime via
#: :func:`otter_ai_assistant_provider_stream.register_provider`.
BUILT_IN_PROVIDERS: list[str] = ["zai", "openai"]

#: The single api this package dispatches by default. A future provider
#: package may register additional api stream fns.
DEFAULT_API: str = "chat-completions"


class ProviderConfig(BaseModel):
    """Registry entry for a provider: identity + env-key + default api.

    Built-in entries are seeded by :func:`register_built_ins`; additional
    entries are added via :func:`register_provider`.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    #: Environment variable read by :func:`get_env_api_key` when the caller
    #: does not pass an explicit ``api_key``. ``None`` disables env resolution.
    env_key: str | None = None
    #: Default api used to dispatch models for this provider when the caller's
    #: :class:`ModelProviderConfig` omits ``api``.
    api: str = DEFAULT_API


class ModelProviderOverrides(BaseModel):
    """Optional per-call overrides applied onto the catalog model.

    Every field maps 1:1 onto a mutable request-shaping field of
    :class:`~otter_ai_chat_completions.ChatCompletionsModel`. ``None`` means
    "keep the catalog value". ``compat`` is special: it is **field-merged**
    onto the catalog compat (caller wins per-field), not replaced.

    ``api_key`` is intentionally absent — it lives on
    :class:`ModelProviderConfig`, not here, to keep key resolution
    (explicit > env > raise) in one place.
    """

    model_config = ConfigDict(extra="forbid")

    temperature: float | None = None
    request_max_tokens: int | None = None
    headers: dict[str, str] | None = None
    timeout_ms: int | None = None
    max_retries: int | None = None
    max_retry_delay_ms: int | None = None
    cache_retention: Literal["none", "short", "long"] | None = None
    session_id: str | None = None
    metadata: dict[str, Any] | None = None
    tool_choice: str | dict[str, Any] | None = None
    base_url: str | None = None
    #: Field-merged onto the catalog compat (caller wins per-field).
    compat: ChatCompletionsCompat | None = None


class ModelProviderConfig(BaseModel):
    """The caller's selection of a model + per-call reasoning config.

    ``provider`` + ``model`` resolve a catalog
    :class:`~otter_ai_chat_completions.ChatCompletionsModel`; ``thinking_level``
    is clamped against that model's supported levels; ``api_key`` is resolved
    (explicit > env > raise); and ``overrides`` are applied onto the catalog
    model. The result is a fully-populated
    :class:`~otter_ai_chat_completions.ChatCompletionsModelOptions` ready for
    the api stream fn.
    """

    model_config = ConfigDict(extra="forbid")

    model: str
    provider: str
    #: Dispatch key. Defaults to the provider's configured api (built-ins
    #: default to ``"chat-completions"``).
    api: str = DEFAULT_API
    #: Default ``"low"``. Clamped via
    #: :func:`~otter_ai_assistant_provider_stream.clamp_thinking_level`
    #: before being mapped to a ``reasoning_effort``.
    thinking_level: ThinkingLevel = "low"
    #: Explicit API key. When ``None`` the env var registered for the
    #: provider is consulted; if that is also unset the seam raises (encoded
    #: as an :class:`~otter_ai_core.AssistantErrorEvent`).
    api_key: str | None = None
    overrides: ModelProviderOverrides | None = None


@dataclass
class ModelProviderOptions:
    """Bundle passed to :func:`create_assistant_message_stream_by_provider`.

    Mirrors :class:`~otter_ai_chat_completions.ChatCompletionsModelOptions`:
    the pure-data config lives on :attr:`model`; runtime handles (hooks) sit
    alongside it because they cannot live on a serializable Pydantic model.
    The defaults let a "no hooks" caller construct this with just the model.

    The abort signal is **not** part of this bundle: it is supplied as the
    seam's third argument (an :class:`asyncio.Event`) and is the single source
    of truth for cooperative abort, threaded through to the dispatched
    provider stream fn.
    """

    model: ModelProviderConfig
    hooks: ChatCompletionsHooks = field(default_factory=ChatCompletionsHooks)
