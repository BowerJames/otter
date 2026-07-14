"""Typed stream aliases and the producer-side seam for a single assistant message.

This module fixes ``TEvent`` of the generic abortable-stream runtime
(:mod:`otter_ai_core.stream`) to
:data:`~otter_ai_core.assistant_message_stream.AssistantMessageEvent`:

* :data:`AssistantMessageStreamClient` — the consumer handle: iterate the
  streaming events and abort via :meth:`~otter_ai_core.stream.StreamClient.abort`.
* :data:`AssistantMessageStreamBackend` — the producer handle: push events and
  observe the abort signal.
* :data:`AssistantMessageStreamFn` — the options-bound producer: a callable that
  takes a :class:`~otter_ai_core.Context` and returns an
  :data:`AssistantMessageStreamClient`. **No abort argument** — the abort
  signal is intrinsic to the stream, created by
  :func:`~otter_ai_core.stream.create_stream`.
* :data:`AssistantMessageStreamFnBuilder` — the builder seam that binds a
  provider's options bundle and returns an :data:`AssistantMessageStreamFn`.

Why the abort signal is intrinsic, not an argument
--------------------------------------------------
Previously the producer took an ``asyncio.Event`` abort signal as a second
argument and the consumer (a bare
:class:`~otter_ai_core.channel.ChannelReader`) had no way to signal abort. The
abort now lives on the stream itself: a producer calls
:func:`~otter_ai_core.stream.create_stream`, keeps the
:data:`AssistantMessageStreamBackend` (observing
:attr:`~otter_ai_core.stream.StreamBackend.abort_signal`), and returns the
:data:`AssistantMessageStreamClient`; the consumer calls
:meth:`~otter_ai_core.stream.StreamClient.abort`. The seam argument disappears,
so callers no longer thread an out-of-band event.

Both plain aliases are specialized via ``TypeVar``-invariant assignment. The
two seam aliases use PEP 695 ``type`` statements;
:data:`AssistantMessageStreamFn` must be defined first because
:data:`AssistantMessageStreamFnBuilder` references it.
"""

from __future__ import annotations

from collections.abc import Callable

from otter_ai_core.assistant_message_stream.assistant_message_events import (
    AssistantMessageEvent,
)
from otter_ai_core.builder import BuilderFn
from otter_ai_core.context import Context
from otter_ai_core.stream import StreamBackend, StreamClient

#: Stream of assistant streaming events (single assistant message per stream).
#: The consumer iterates with ``async for`` and aborts with ``.abort()``.
AssistantMessageStreamClient = StreamClient[AssistantMessageEvent]

#: Producer handle for an :data:`AssistantMessageStreamClient`.
#: Pushes events and observes the shared abort signal.
AssistantMessageStreamBackend = StreamBackend[AssistantMessageEvent]

#: The options-bound producer: a callable that takes a :class:`Context` and
#: returns an :data:`AssistantMessageStreamClient`.
#:
#: This is the post-binding shape — the options bundle has already been
#: resolved/closed over, so only the conversation state remains. A concrete
#: :data:`AssistantMessageStreamFnBuilder` *returns* one of these after binding
#: its options; a dispatch layer then invokes the returned function with
#: ``(context)`` to obtain the live stream.
#:
#: The :class:`Context` carries the conversation state and any other runtime
#: data the producer needs to generate the assistant message. The cooperative-
#: abort signal is **not** an argument here: the producer creates it with
#: :func:`~otter_ai_core.stream.create_stream` and the consumer drives it via
#: :meth:`~otter_ai_core.stream.StreamClient.abort`.
type AssistantMessageStreamFn = Callable[[Context], AssistantMessageStreamClient]

#: Builder of an :data:`AssistantMessageStreamFn`.
#:
#: Producer-side seam between a provider package and a dispatch layer (mirrors
#: ``StreamFunction`` in @earendil-works/pi-ai). It takes the provider's
#: per-call options bundle and returns an :data:`AssistantMessageStreamFn` with
#: the options closed over. A dispatch layer keys on the model's ``api`` (read
#: off the options) and invokes the registered builder with ``options`` to
#: obtain the bound producer, then calls that producer with ``(context)``.
#: Otter defines no dispatch today — this alias is the contract a provider
#: package and a dispatch layer will agree on.
#:
#: ``TOptions`` is open because the realistic shape is a provider-specific
#: **options bundle** — pure-data config (model id, temperature, max tokens,
#: API key, …). A provider that needs
#: nothing beyond the model may specialize ``TOptions`` to a bare ``Model``
#: type, but the options-bundle form is the intended pattern.
type AssistantMessageStreamFnBuilder[TOptions] = BuilderFn[
    TOptions, AssistantMessageStreamFn
]
