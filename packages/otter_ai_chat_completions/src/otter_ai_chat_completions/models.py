"""Chat Completions model definitions for the wire-format contract package.

This module is **pure data**: identity, capabilities, serializable request
config, and per-provider compat. It performs no provider/base_url detection,
no env-key resolution, and no header injection — those are the consumer's
responsibility. The stream function (:mod:`otter_ai_chat_completions.stream`)
reads these values verbatim.

Conventions follow :mod:`otter_ai_core`: Pydantic v2, ``extra="forbid"``,
snake_case, ``X | None = None`` optionals, JSON round-trippable.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from otter_ai_core import Provider

#: The single API shape this package speaks. Constant for the whole package;
#: stored on the model so it flows onto ``AssistantMessage.api`` (inert
#: provenance in otter).
ChatCompletionsApi = Literal["chat-completions"]

#: Chat Completions reasoning-effort levels (mirrors pi-ai's ``ThinkingLevel``).
#: Used for the per-call ``reasoning_effort`` request field.
ChatCompletionsReasoningEffort = Literal["minimal", "low", "medium", "high", "xhigh"]

#: Keys for a model's thinking-level map (mirrors pi-ai's
#: ``ModelThinkingLevel``). Maps each level to a provider-specific value, or
#: ``None`` to mark the level unsupported.
ChatCompletionsThinkingLevelKey = Literal[
    "off", "minimal", "low", "medium", "high", "xhigh"
]

#: ``var`` names for :class:`ChatTemplateKwargVar`. Mirrors pi-ai's
#: ``ChatTemplateKwargValue.$var``. The runtime constants below are kept for
#: comparison code; the :class:`ChatTemplateKwargVarName` literal inlines the
#: string values because mypy does not accept a variable inside ``Literal[...]``.
CHAT_TEMPLATE_THINKING_ENABLED = "thinking.enabled"
CHAT_TEMPLATE_THINKING_EFFORT = "thinking.effort"
ChatTemplateKwargVarName = Literal["thinking.enabled", "thinking.effort"]


class ChatTemplateKwargVar(BaseModel):
    """A ``pi``-controlled ``chat_template_kwargs`` value.

    Resolved at request-build time from the call's ``reasoning_effort``:

    * ``var == "thinking.enabled"`` → ``bool`` (``reasoning_effort`` is set).
    * ``var == "thinking.effort"`` → the mapped (``thinking_level_map``) or raw
      ``reasoning_effort`` string. When ``omit_when_off`` is ``True`` and no
      ``reasoning_effort`` is set, the whole entry is omitted.
    """

    model_config = ConfigDict(extra="forbid")

    var: ChatTemplateKwargVarName
    omit_when_off: bool | None = None


#: A ``chat_template_kwargs`` value: a JSON scalar or a resolved variable.
ChatTemplateKwargValue = str | int | float | bool | None | ChatTemplateKwargVar


class ChatCompletionsCost(BaseModel):
    """Pricing rates in USD per million tokens.

    Used to compute :class:`otter_ai_core.UsageCost` per turn. This is **not** a
    per-turn accounting record — it is a rate card.
    """

    model_config = ConfigDict(extra="forbid")

    input: float
    output: float
    cache_read: float
    cache_write: float


class ChatCompletionsCompat(BaseModel):
    """Per-provider wire-format deviations from standard Chat Completions.

    Every field is optional: ``None`` means "use the standard Chat
    Completions default, resolved at call time." This package performs **no**
    provider/base_url detection — the consumer (catalog/config layer)
    populates these explicitly for non-standard providers.

    The field set mirrors pi-ai's ``OpenAICompletionsCompat``.
    """

    model_config = ConfigDict(extra="forbid")

    supports_store: bool | None = None
    supports_developer_role: bool | None = None
    supports_reasoning_effort: bool | None = None
    supports_usage_in_streaming: bool | None = None
    max_tokens_field: Literal["max_completion_tokens", "max_tokens"] | None = None
    requires_tool_result_name: bool | None = None
    requires_assistant_after_tool_result: bool | None = None
    requires_thinking_as_text: bool | None = None
    requires_reasoning_content_on_assistant_messages: bool | None = None
    thinking_format: (
        Literal[
            "openai",
            "openrouter",
            "deepseek",
            "together",
            "zai",
            "qwen",
            "qwen-chat-template",
            "chat-template",
            "string-thinking",
            "ant-ling",
        ]
        | None
    ) = None
    #: Provider-defined Jinja template variables emitted as
    #: ``chat_template_kwargs`` when ``thinking_format == "chat-template"``.
    #: Values are scalars or a :class:`ChatTemplateKwargVar` resolved from the
    #: call's ``reasoning_effort``. Defaults to ``{}`` when unset.
    chat_template_kwargs: dict[str, ChatTemplateKwargValue] | None = None
    openrouter_routing: dict[str, Any] | None = None
    vercel_gateway_routing: dict[str, Any] | None = None
    zai_tool_stream: bool | None = None
    supports_strict_mode: bool | None = None
    cache_control_format: Literal["anthropic"] | None = None
    send_session_affinity_headers: bool | None = None
    supports_long_cache_retention: bool | None = None


class ChatCompletionsModel(BaseModel):
    """A Chat Completions model plus its full call configuration.

    Pure configuration: identity + capabilities + request shaping +
    per-provider compat. No behaviour, no detection, no env magic. The stream
    function reads it verbatim. Per-call mutation is via
    ``model.model_copy(update={...})``.

    Runtime handles (hooks) do **not** live here — they cannot
    be carried by a serializable data model. They are bundled with the model
    in :class:`otter_ai_chat_completions.options.ChatCompletionsModelOptions`,
    which is the seam's first argument; the cooperative-abort signal is the
    seam's third argument (an :class:`asyncio.Event`).
    """

    model_config = ConfigDict(extra="forbid")

    # --- Identity (feeds inert ``AssistantMessage`` provenance) ---
    id: str
    name: str
    #: Provenance only. NOT read for behaviour in this package — no detection,
    #: no env-keying, no header injection. Copied onto
    #: ``AssistantMessage.provider``.
    provider: Provider
    base_url: str
    api: ChatCompletionsApi = "chat-completions"

    # --- Capabilities (catalog facts) ---
    reasoning: bool
    input_modalities: list[Literal["text", "image"]]
    context_window: int
    #: The model's own output-token cap (pi-ai ``Model.maxTokens``).
    max_tokens: int
    cost: ChatCompletionsCost
    thinking_level_map: dict[ChatCompletionsThinkingLevelKey, str | None] | None = None

    # --- Request shaping (per-call serializable config) ---
    api_key: str | None = None
    temperature: float | None = None
    #: Per-request output cap (pi-ai ``options.maxTokens``). Renamed to avoid
    #: clashing with the model-cap :attr:`max_tokens` and to avoid coupling to
    #: OpenAI's wire field (see :attr:`ChatCompletionsCompat.max_tokens_field`).
    request_max_tokens: int | None = None
    tool_choice: str | dict[str, Any] | None = None
    #: Request reasoning level (pi-ai ``options.reasoning`` -> provider's
    #: ``reasoningEffort``). Distinct from the :attr:`reasoning` capability bool.
    reasoning_effort: ChatCompletionsReasoningEffort | None = None
    headers: dict[str, str] | None = None
    timeout_ms: int | None = None
    max_retries: int | None = None
    max_retry_delay_ms: int | None = None
    cache_retention: Literal["none", "short", "long"] | None = None
    session_id: str | None = None
    metadata: dict[str, Any] | None = None

    # --- Compat ---
    compat: ChatCompletionsCompat | None = None
