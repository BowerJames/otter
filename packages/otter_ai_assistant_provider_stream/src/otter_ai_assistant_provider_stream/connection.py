"""The provider-dispatch seam.

:func:`create_model_connection_by_provider` is a concrete value of
:data:`otter_ai_core.model_connection.ModelConnectionFnBuilder`
parameterised by :class:`~otter_ai_core.ProviderModelOption`. It routes on the
option's ``api`` (:class:`~otter_ai_core.KnownApis`):

* :data:`~otter_ai_core.KnownApis.ChatCompletion` — resolve a catalog
  :class:`~otter_ai_chat_completions.ChatCompletionsModel`, clamp the thinking
  level, resolve the api key (explicit > env > raise), build a
  chat-completions
  :data:`~otter_ai_core.assistant_message_stream.AssistantMessageStreamFn`,
  and adapt it to a
  :data:`~otter_ai_core.model_connection.ModelConnectionFn` via
  :func:`otter_ai_assistant_stream_model_connection.create_assistant_stream_model_connection`.
* :data:`~otter_ai_core.KnownApis.Realtime` — resolve a realtime catalog
  :class:`~otter_ai_realtime.RealtimeModel`, set the api key (explicit > env;
  a missing key is left for the realtime seam to encode as a
  :class:`~otter_ai_core.model_connection.ConnectionErrorEvent`), and delegate
  to :func:`otter_ai_realtime.create_realtime_model_connection`.

The seam is a **builder**: it closes over ``options`` and returns the
options-bound :data:`~otter_ai_core.model_connection.ModelConnectionFn`. That
returned producer **never raises** — resolution/dispatch happens when it is
invoked, and any failure is encoded on the returned
:class:`~otter_ai_core.model_connection.ModelConnection`:

* the **chat** path surfaces resolution failures as a
  :class:`~otter_ai_core.model_connection.ResponseErrorEvent` (translated from
  an :class:`~otter_ai_core.assistant_message_stream.AssistantErrorEvent` by
  the adapter) when the caller sends a
  :class:`~otter_ai_core.model_connection.ResponseCreate`;
* the **realtime** path surfaces catalog misses as a
  :class:`~otter_ai_core.model_connection.ConnectionErrorEvent` immediately;
  a missing api key is surfaced by the realtime seam as a
  :class:`~otter_ai_core.model_connection.ConnectionErrorEvent`.

No per-call overrides or runtime hooks are accepted —
:class:`~otter_ai_core.ProviderModelOption` is pure data and the dispatched
builders use default hooks and apply no overrides on top of catalog facts.
"""

from __future__ import annotations

import asyncio
import time

from otter_ai_assistant_provider_stream.catalog import get_model
from otter_ai_assistant_provider_stream.connection_registry import (
    get_model_connection_builder,
)
from otter_ai_assistant_provider_stream.env import get_env_api_key
from otter_ai_assistant_provider_stream.realtime_catalog import get_realtime_model
from otter_ai_assistant_provider_stream.thinking import (
    clamp_thinking_level,
    resolve_reasoning_effort,
)
from otter_ai_assistant_stream_model_connection import (
    create_assistant_stream_model_connection,
)
from otter_ai_chat_completions import (
    ChatCompletionsHooks,
    ChatCompletionsModelOptions,
    create_chat_completions_assistant_message_stream,
)
from otter_ai_core import (
    AssistantMessage,
    Context,
    ProviderModelOption,
    Usage,
    UsageCost,
    create_connection,
    create_stream,
)
from otter_ai_core.assistant_message_stream import (
    AssistantErrorEvent,
    AssistantMessageStream,
    AssistantMessageStreamFn,
    AssistantMessageWriter,
)
from otter_ai_core.connection import ConnectionBackend
from otter_ai_core.model_connection import (
    ClientEvent,
    ConnectionErrorEvent,
    ModelConnection,
    ModelConnectionFn,
    ServerEvent,
)
from otter_ai_realtime import RealtimeModel, RealtimeModelOptions
from otter_ai_realtime.connection import create_realtime_model_connection


def create_model_connection_by_provider(
    options: ProviderModelOption,
) -> ModelConnectionFn:
    """Build a :class:`~otter_ai_core.model_connection.ModelConnectionFn` for a
    catalog model, routing on ``options.api``.

    A concrete value of
    :data:`~otter_ai_core.model_connection.ModelConnectionFnBuilder`: closes
    over ``options`` and returns the options-bound producer. The returned
    producer never raises — resolution/dispatch happens when it is invoked,
    and any failure is encoded on the returned
    :class:`~otter_ai_core.model_connection.ModelConnection`.

    ``abort`` (the producer's second argument) is the cooperative-cancel
    signal (an :class:`asyncio.Event`); it is threaded through to the
    dispatched connection producer.
    """

    def connection_fn(context: Context, abort: asyncio.Event) -> ModelConnection:
        builder = get_model_connection_builder(options.api)
        if builder is None:
            return _error_connection(
                f"No connection builder registered for api: {options.api.value!r}"
            )
        try:
            return builder(options)(context, abort)
        except Exception as exc:  # noqa: BLE001 — the producer must never raise.
            return _error_connection(f"{type(exc).__name__}: {exc}")

    return connection_fn


# --------------------------------------------------------------------------- #
# Chat-completions builder
# --------------------------------------------------------------------------- #


def _chat_completions_connection_builder(
    options: ProviderModelOption,
) -> ModelConnectionFn:
    """Resolve a chat-completions stream fn and adapt it to a connection.

    Resolution failures are encoded as an error ``AssistantMessageStreamFn``
    so they surface (via the adapter) as a ``ResponseErrorEvent`` when the
    caller sends a ``ResponseCreate``.
    """

    def connection_fn(context: Context, abort: asyncio.Event) -> ModelConnection:
        try:
            stream_fn = _resolve_chat_stream_fn(options)
        except Exception as exc:  # noqa: BLE001 — encode failure on the stream.
            stream_fn = _error_stream_fn(options, exc)
        return create_assistant_stream_model_connection(stream_fn)(context, abort)

    return connection_fn


def _resolve_chat_stream_fn(
    options: ProviderModelOption,
) -> AssistantMessageStreamFn:
    """Resolve a :class:`ProviderModelOption` into a chat-completions stream fn.

    Raises on unresolvable input (unknown model, missing api key); the caller
    wraps these into an error stream fn.
    """
    base = get_model(options.provider.value, options.model)
    if base is None:
        raise RuntimeError(
            f"No model registered for provider={options.provider.value!r} "
            f"model={options.model!r}"
        )

    clamped = clamp_thinking_level(base, options.thinking_level)
    effort = resolve_reasoning_effort(clamped)

    api_key = _resolve_api_key(options)
    model = base.model_copy(update={"api_key": api_key, "reasoning_effort": effort})

    cc_options = ChatCompletionsModelOptions(model=model, hooks=ChatCompletionsHooks())
    return create_chat_completions_assistant_message_stream(cc_options)


def _resolve_api_key(options: ProviderModelOption) -> str:
    """Resolve the api key for a chat-completions model: explicit > env > raise."""
    if options.api_key:
        return options.api_key
    env_key = get_env_api_key(options.provider.value)
    if env_key:
        return env_key
    raise RuntimeError(f"No API key for provider: {options.provider.value}")


def _error_stream_fn(
    options: ProviderModelOption, exc: Exception
) -> AssistantMessageStreamFn:
    """Build a stream fn that yields a single ``AssistantErrorEvent`` then ends.

    The skeleton message carries best-effort provenance (provider/model/api)
    from the caller's option so a consumer can still attribute the failure.
    """

    def stream_fn(_context: Context, _abort: asyncio.Event) -> AssistantMessageStream:
        message = AssistantMessage(
            role="assistant",
            content=[],
            api=options.api.value,
            provider=options.provider.value,
            model=options.model,
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

    return stream_fn


# --------------------------------------------------------------------------- #
# Realtime builder
# --------------------------------------------------------------------------- #


def _realtime_connection_builder(
    options: ProviderModelOption,
) -> ModelConnectionFn:
    """Resolve a realtime model and delegate to the realtime seam.

    A catalog miss is encoded as a ``ConnectionErrorEvent`` immediately when
    the producer is invoked (before any client event); a missing api key is
    left for the realtime seam to encode.
    """

    def connection_fn(context: Context, abort: asyncio.Event) -> ModelConnection:
        try:
            rt_model = _resolve_realtime_model(options)
        except _RealtimeCatalogMiss as exc:
            return _error_connection(str(exc))
        rt_options = RealtimeModelOptions(model=rt_model)
        return create_realtime_model_connection(rt_options)(context, abort)

    return connection_fn


class _RealtimeCatalogMiss(RuntimeError):
    """Raised when no realtime catalog model matches the option."""


def _resolve_realtime_model(options: ProviderModelOption) -> RealtimeModel:
    """Resolve a :class:`ProviderModelOption` into a realtime catalog model.

    Raises :class:`_RealtimeCatalogMiss` on an unknown model. The api key is
    resolved explicit > env and left ``None`` when neither is set (the
    realtime seam then encodes a ``ConnectionErrorEvent``). The thinking level
    is intentionally ignored — realtime has no reasoning-effort concept.
    """
    base = get_realtime_model(options.provider.value, options.model)
    if base is None:
        raise _RealtimeCatalogMiss(
            f"No realtime model registered for provider={options.provider.value!r} "
            f"model={options.model!r}"
        )
    api_key = options.api_key or get_env_api_key(options.provider.value)
    if api_key:
        base = base.model_copy(update={"api_key": api_key})
    return base


# --------------------------------------------------------------------------- #
# Error-connection helper
# --------------------------------------------------------------------------- #


def _error_connection(message: str) -> ModelConnection:
    """A connection whose backend pushes one ``ConnectionErrorEvent`` then ends.

    No backend task is spawned — the single event is pushed synchronously and
    the inbound writer ended, so the caller iterating the connection observes
    exactly the error and then completion.
    """
    conn: ModelConnection
    backend: ConnectionBackend[ClientEvent, ServerEvent]
    conn, backend = create_connection()
    backend.push(
        ConnectionErrorEvent(
            type="connection.error",
            message=message,
            reason="dispatch_error",
        )
    )
    backend.end()
    return conn


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


__all__ = ["create_model_connection_by_provider"]
