"""The provider-dispatch seam.

:func:`create_assistant_message_stream_by_provider` is a concrete value of
:data:`otter_ai_core.AssistantMessageStreamFn` that resolves a
:class:`~otter_ai_assistant_provider_stream.types.ModelProviderConfig` against
the catalog + env + thinking-clamp registries, builds a fully-populated
:class:`~otter_ai_chat_completions.ChatCompletionsModelOptions`, and dispatches
to the api stream fn registered for the model's ``api``.

The seam **never raises**. Request/model/runtime failures (unknown model,
unknown api, missing api key) are encoded as an
:class:`~otter_ai_core.AssistantErrorEvent` carrying a best-effort skeleton
:class:`~otter_ai_core.AssistantMessage`, mirroring pi-ai's
``createLazyLoadErrorMessage`` pattern. This honours the
``AssistantMessageStreamFn`` contract: the caller always receives a live
stream and learns of failure by reading its terminal event.
"""

from __future__ import annotations

import asyncio
import time

from otter_ai_assistant_provider_stream.api_registry import get_api_stream_fn
from otter_ai_assistant_provider_stream.catalog import get_model
from otter_ai_assistant_provider_stream.env import get_env_api_key
from otter_ai_assistant_provider_stream.thinking import (
    clamp_thinking_level,
    resolve_reasoning_effort,
)
from otter_ai_assistant_provider_stream.types import (
    ModelProviderConfig,
    ModelProviderOptions,
    ModelProviderOverrides,
)
from otter_ai_chat_completions import (
    ChatCompletionsCompat,
    ChatCompletionsModel,
    ChatCompletionsModelOptions,
)
from otter_ai_core import (
    AssistantErrorEvent,
    AssistantMessage,
    AssistantMessageStream,
    AssistantMessageWriter,
    Context,
    Usage,
    UsageCost,
    create_stream,
)

#: Fields on :class:`ModelProviderOverrides` that map 1:1 onto mutable
#: :class:`~otter_ai_chat_completions.ChatCompletionsModel` request fields.
#: ``compat`` is handled separately (field-merged) and ``api_key`` lives on
#: :class:`ModelProviderConfig`, not here.
_DIRECT_OVERRIDE_FIELDS: tuple[str, ...] = (
    "temperature",
    "request_max_tokens",
    "headers",
    "timeout_ms",
    "max_retries",
    "max_retry_delay_ms",
    "cache_retention",
    "session_id",
    "metadata",
    "tool_choice",
    "base_url",
)


def create_assistant_message_stream_by_provider(
    options: ModelProviderOptions,
    context: Context,
    abort: asyncio.Event | None = None,
) -> AssistantMessageStream:
    """Build an :class:`~otter_ai_core.AssistantMessageStream` for a catalog model.

    Synchronous; never raises. Resolution/dispatch failures are encoded as an
    :class:`~otter_ai_core.AssistantErrorEvent` on the returned stream.

    ``abort`` is the cooperative-abort signal (an :class:`asyncio.Event`);
    when omitted a fresh, unset event is created. It is threaded through to
    the dispatched provider stream fn.
    """
    if abort is None:
        abort = asyncio.Event()
    try:
        cc_options = _resolve_options(options)
        fn = get_api_stream_fn(options.model.api)
        if fn is None:
            raise RuntimeError(
                f"No stream fn registered for api: {options.model.api!r}"
            )
        return fn(cc_options, context, abort)
    except Exception as exc:  # noqa: BLE001 — the seam must never raise.
        return _error_stream(options.model, exc)


# --------------------------------------------------------------------------- #
# Option resolution
# --------------------------------------------------------------------------- #


def _resolve_options(options: ModelProviderOptions) -> ChatCompletionsModelOptions:
    """Resolve a :class:`ModelProviderOptions` into a ``ChatCompletionsModelOptions``.

    Raises on unresolvable input (unknown model, missing api key); the seam
    wraps these into an error stream.
    """
    config = options.model

    base = get_model(config.provider, config.model)
    if base is None:
        raise RuntimeError(
            f"No model registered for provider={config.provider!r} "
            f"model={config.model!r}"
        )

    model = _apply_overrides(base, config.overrides)

    # Clamp the requested thinking level against the resolved model's
    # supported levels, then map to a reasoning_effort. Clamping runs after
    # overrides so it sees the final catalog facts (overrides do not touch
    # reasoning capability / thinking_level_map today, so order is equivalent;
    # post-override is chosen for clarity).
    clamped = clamp_thinking_level(model, config.thinking_level)
    effort = resolve_reasoning_effort(clamped)

    api_key = _resolve_api_key(config)
    model = model.model_copy(update={"api_key": api_key, "reasoning_effort": effort})

    return ChatCompletionsModelOptions(
        model=model,
        hooks=options.hooks,
    )


def _apply_overrides(
    base: ChatCompletionsModel, overrides: ModelProviderOverrides | None
) -> ChatCompletionsModel:
    """Return ``base`` with the (non-compat) overrides applied via ``model_copy``.

    ``compat`` is merged separately. ``model_copy`` keeps the catalog model
    immutable; a fresh instance is returned.
    """
    if overrides is None:
        return base
    update: dict[str, object] = {}
    for field in _DIRECT_OVERRIDE_FIELDS:
        value = getattr(overrides, field)
        if value is not None:
            update[field] = value
    model = base.model_copy(update=update)

    if overrides.compat is not None:
        merged = _merge_compat(base.compat, overrides.compat)
        model = model.model_copy(update={"compat": merged})
    return model


def _merge_compat(
    base: ChatCompletionsCompat | None, override: ChatCompletionsCompat
) -> ChatCompletionsCompat:
    """Field-merge an override compat onto a base compat (override wins).

    Mirrors pi-ai's ``getCompat``: every field set on the override wins; fields
    left as ``None`` on the override fall back to the base value (or the
    standard default when the base is also ``None`` — resolved downstream).
    """
    base_dict = base.model_dump() if base is not None else {}
    override_dict = override.model_dump(exclude_defaults=False)
    merged: dict[str, object] = {}
    # Iterate over the union of both fields: when ``base`` is ``None`` (e.g.
    # OpenAI models, which use standard defaults) ``base_dict`` is empty, so a
    # plain ``for field in base_dict`` would silently drop every override.
    for field in set(base_dict) | set(override_dict):
        override_value = override_dict.get(field)
        if override_value is not None:
            merged[field] = override_value
        elif field in base_dict and base_dict[field] is not None:
            merged[field] = base_dict[field]
    return ChatCompletionsCompat.model_validate(merged)


def _resolve_api_key(config: ModelProviderConfig) -> str:
    """Resolve the api key: explicit > env > raise."""
    if config.api_key:
        return config.api_key
    env_key = get_env_api_key(config.provider)
    if env_key:
        return env_key
    raise RuntimeError(f"No API key for provider: {config.provider}")


# --------------------------------------------------------------------------- #
# Error path
# --------------------------------------------------------------------------- #


def _zero_usage() -> Usage:
    return Usage(
        input=0,
        output=0,
        cache_read=0,
        cache_write=0,
        total_tokens=0,
        cost=UsageCost(
            input=0.0, output=0.0, cache_read=0.0, cache_write=0.0, total=0.0
        ),
    )


def _error_stream(
    config: ModelProviderConfig, exc: Exception
) -> AssistantMessageStream:
    """Build a stream that yields a single ``AssistantErrorEvent`` then ends.

    The skeleton message carries best-effort provenance (provider/model/api)
    from the caller's config so a consumer can still attribute the failure.
    """
    message = AssistantMessage(
        role="assistant",
        content=[],
        api=config.api,
        provider=config.provider,
        model=config.model,
        usage=_zero_usage(),
        stop_reason="error",
        error_message=f"{type(exc).__name__}: {exc}",
        timestamp=int(time.time() * 1000),
    )
    stream: AssistantMessageStream
    writer: AssistantMessageWriter
    stream, writer = create_stream()
    writer.push(
        AssistantErrorEvent(
            role="assistant",
            type="error",
            reason="error",
            error=message,
        )
    )
    writer.end()
    return stream


__all__ = ["create_assistant_message_stream_by_provider"]
