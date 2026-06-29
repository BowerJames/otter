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
# Plain assignment (not PEP 695 ``type`` statements). ``TEvent`` is invariant
# because ``StreamWriter.push`` accepts it, so covariance is not available
# regardless.

#: Stream of assistant streaming events (single assistant message per stream).
AssistantMessageStream = Stream[AssistantMessageEvent]

#: Producer handle for an :data:`AssistantMessageStream`.
AssistantMessageWriter = StreamWriter[AssistantMessageEvent]

#: Function that builds an :data:`AssistantMessageStream`.
#:
#: Producer-side seam between a provider package and a future dispatch layer
#: (mirrors ``StreamFunction`` in @earendil-works/pi-ai, with the model and
#: options slots collapsed into one: ``TOptions``).
#:
#: The first argument carries the provider's per-call configuration. A future
#: dispatch layer would key on the model's ``api`` (read off the configuration)
#: and invoke the registered function with ``(options, context, abort)``. Otter
#: defines no dispatch today — this alias is the contract a provider package
#: and a dispatch layer will agree on.
#:
#: ``TOptions`` is open because the realistic shape is a provider-specific
#: **options bundle** — pure-data config (model id, temperature, max tokens,
#: API key, …) bundled with runtime handles (hooks) that cannot
#: travel out-of-band (a closure is per-call and defeats registry-keyed lookup;
#: registry metadata is per-registration, not per-call). A provider that needs
#: nothing beyond the model may specialize ``TOptions`` to a bare ``Model``
#: type, but the options-bundle form is the intended pattern.
#:
#: The second argument is a :class:`Context` instance, which carries the conversation
#: state and any other runtime data the provider needs to generate the assistant
#: message.
#:
#: The third argument is an ``asyncio.Event`` that represents an abort
#: signal. The producer should monitor this event and terminate the stream
#: gracefully if it is set, ensuring that the consumer can handle
#: cancellation gracefully.

type AssistantMessageStreamFnBuilder[TOptions] = Callable[
    [TOptions, Context, asyncio.Event], AssistantMessageStream
]

#: The options-bound form of :data:`AssistantMessageStreamFnBuilder`: a producer
#: whose options bundle has already been resolved/closed over, so only the
#: :class:`Context` and the abort signal remain. It is the post-binding shape a
#: dispatch layer would hand a caller that no longer needs to see the options
#: slot. Concrete provider seams today are values of
#: :data:`AssistantMessageStreamFnBuilder`; this alias is exported for parity
#: and future bound-call sites.
type AssistantMessageStreamFn = Callable[
    [Context, asyncio.Event], AssistantMessageStream
]
