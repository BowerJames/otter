import asyncio
from collections.abc import Callable

from otter_ai_core.assistant_message_stream.assistant_message_events import (
    AssistantMessageEvent,
)
from otter_ai_core.context import Context
from otter_ai_core.stream import Stream, StreamWriter

# --------------------------------------------------------------------------- #
# Typed aliases
# --------------------------------------------------------------------------- #
#
# The two plain aliases (``AssistantMessageStream`` / ``AssistantMessageWriter``)
# are specialized via ``TypeVar``-invariant assignment (``StreamWriter.push``
# accepts ``TEvent``, so the alias is invariant regardless). The two seam
# aliases use PEP 695 ``type`` statements; ``AssistantMessageStreamFn`` must be
# defined first because ``AssistantMessageStreamFnBuilder`` references it.

#: Stream of assistant streaming events (single assistant message per stream).
AssistantMessageStream = Stream[AssistantMessageEvent]

#: Producer handle for an :data:`AssistantMessageStream`.
AssistantMessageWriter = StreamWriter[AssistantMessageEvent]

#: The options-bound producer: a callable that takes a :class:`Context` and an
#: ``asyncio.Event`` abort signal and returns an :data:`AssistantMessageStream`.
#:
#: This is the post-binding shape — the options bundle has already been
#: resolved/closed over, so only the conversation state and the abort signal
#: remain. A concrete :data:`AssistantMessageStreamFnBuilder` *returns* one of
#: these after binding its options; a dispatch layer then invokes the returned
#: function with ``(context, abort)`` to obtain the live stream.
#:
#: The :class:`Context` carries the conversation state and any other runtime
#: data the producer needs to generate the assistant message. The
#: ``asyncio.Event`` is the cooperative-abort signal: the producer should
#: monitor it and terminate the stream gracefully if it is set, so the consumer
#: can handle cancellation cleanly.
type AssistantMessageStreamFn = Callable[
    [Context, asyncio.Event], AssistantMessageStream
]

#: Builder of an :data:`AssistantMessageStreamFn`.
#:
#: Producer-side seam between a provider package and a future dispatch layer
#: (mirrors ``StreamFunction`` in @earendil-works/pi-ai). It takes the
#: provider's per-call options bundle and returns an
#: :data:`AssistantMessageStreamFn` with the options closed over. A future
#: dispatch layer would key on the model's ``api`` (read off the options)
#: and invoke the registered builder with ``options`` to obtain the bound
#: producer, then call that producer with ``(context, abort)``. Otter defines
#: no dispatch today — this alias is the contract a provider package and a
#: dispatch layer will agree on.
#:
#: ``TOptions`` is open because the realistic shape is a provider-specific
#: **options bundle** — pure-data config (model id, temperature, max tokens,
#: API key, …) bundled with runtime handles (hooks) that cannot
#: travel out-of-band (a closure is per-call and defeats registry-keyed lookup;
#: registry metadata is per-registration, not per-call). A provider that needs
#: nothing beyond the model may specialize ``TOptions`` to a bare ``Model``
#: type, but the options-bundle form is the intended pattern.
#
#: The builder is a *builder* — it does not itself produce a stream. Binding
#: the options is distinct from driving a specific conversation, which keeps a
#: registered builder reusable across many calls and lets the dispatch layer
#: hand callers the bound :data:`AssistantMessageStreamFn` directly.

type AssistantMessageStreamFnBuilder[TOptions] = Callable[
    [TOptions], AssistantMessageStreamFn
]
