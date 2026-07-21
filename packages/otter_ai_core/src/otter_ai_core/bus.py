"""Generic typed asynchronous event bus (descriptor-keyed, fan-out).

A :class:`Bus` fans events out to the async handlers subscribed to a typed
:class:`BusEvent` descriptor. It is the fan-out (fire-and-forget) counterpart
to :mod:`otter_ai_core.hook_runner`: where
:class:`~otter_ai_core.hook_runner.HookRunner` invokes a *single* handler and
returns its result to the caller (emit-and-await), the bus invokes *every*
registered handler (side-effects only, each isolated) over a queue + worker.

Why descriptors, not an enum key
--------------------------------
Each event has its own payload type, and the set of events is open (consumers —
e.g. :class:`~otter_ai_core.model_controller.ModelController` — define their
own). A :class:`~enum.StrEnum` key cannot carry per-member type parameters, so
the type checker could not recover the payload type from
``publish(event_type, ...)``. Instead the key is a typed :class:`BusEvent`
descriptor: a frozen, hashable object parameterized over ``TPayload``.
:meth:`Bus.subscribe` / :meth:`Bus.publish` infer ``TPayload`` from the
descriptor, so the public API is fully type-safe with no ``@overload`` and the
set of events is infinitely extensible — new events need no change to
:class:`Bus`. This mirrors the existing
:class:`~otter_ai_core.hook_runner.Hook` / :class:`~otter_ai_core.hook_runner.HookRunner`
idiom, and the ``AgentLoopHookTypes`` + ``Hook`` split in
:mod:`otter_ai_core.agent_loop.hooks`.

Many handlers per event (fan-out)
---------------------------------
Unlike a hook (at most one handler), an event may have ``N`` handlers.
:meth:`Bus.subscribe` appends to a per-descriptor list; :meth:`Bus.publish`
fans the payload out to all of them. Handler exceptions are isolated and logged
(not propagated to the publisher), so one bad subscriber cannot break the
others — the bus does for its subscribers what
:class:`~otter_ai_core.hook_runner.HookRunner` deliberately does *not* (a hook
caller depends on the response, so its exceptions propagate).

Queue + worker / teardown
-------------------------
Unlike :class:`~otter_ai_core.hook_runner.HookRunner` (direct dispatch, no owned
task, no teardown), the bus owns a background worker task draining a
:class:`~otter_ai_core.channel.ChannelReader`. :meth:`publish` is synchronous
(enqueue); the worker awaits each handler in subscription order.
:meth:`end` signals no more events; :meth:`aclose` ends and awaits the worker's
drain to completion under a deadline (force-cancelling it if a non-conformant
handler hangs), so no owned task is left pending. The constructor schedules the
worker and must therefore be called from within a running :mod:`asyncio` loop.

No runtime discriminator checks
-------------------------------
The old enum-keyed bus validated that ``event.type`` belonged to its enum and
defensively dropped events whose discriminator was mutated while queued. Under
descriptor keying both are moot: the descriptor *is* the immutable routing key
(captured in the ``(descriptor, payload)`` pair at publish time), so mutating a
payload's fields cannot re-route it, and a cross-family mismatch is a *static*
type error rather than a runtime one — exactly the trade ``HookRunner`` already
makes ("public API fully type-safe; only the internals erased").

Scope
-----
:class:`Bus` defines no event families of its own — only the generic runtime.
:class:`BusEvent` and :class:`Bus` are runtime objects and are **not**
JSON-serializable (unlike :class:`~otter_ai_core.context.Context`).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from otter_ai_core.channel import ChannelPair, create_channel

_logger = logging.getLogger(__name__)

_DEFAULT_ACLOSE_TIMEOUT: float = 5.0


@dataclass(frozen=True, slots=True)
class BusEvent[TPayload]:
    """A typed event key; the value passed to :meth:`Bus.subscribe` / ``publish``.

    Frozen and hashable so a descriptor works as a :class:`dict` key. Define
    events as module-level singletons (one per event), annotated with their
    ``TPayload`` so ``subscribe`` / ``publish`` infer it::

        ITEM_DONE: BusEvent[Item] = BusEvent("item.done")

    .. note::
       Construct via ``BusEvent("name")`` with an annotation, not
       ``BusEvent[P]("name")``. Subscript-then-construct raises at runtime:
       CPython's generic-alias call tries to set ``__orig_class__``, which a
       frozen + slots dataclass rejects.

    .. note::
       At runtime Python's generic parameters are erased, so two descriptors
       with the same :attr:`name` are the *same key* regardless of their type
       parameters (e.g. a ``BusEvent[Item]`` and a ``BusEvent[Other]`` built
       with the same name collide). Hence the "define each event once as a
       module-level singleton" convention. Building the descriptor from a
       :class:`~enum.StrEnum` member (see
       :mod:`otter_ai_core.model_controller.events`) centralizes the name
       strings so they are discoverable rather than magic-string literals.
    """

    name: str


#: The handler signature for ``BusEvent[TPayload]``.
type BusHandler[TPayload] = Callable[[TPayload], Awaitable[None]]


async def _await_or_cancel(task: asyncio.Task[None], timeout: float | None) -> None:
    """Await ``task`` for up to ``timeout`` seconds; force-cancel if it overruns.

    ``timeout`` of ``None`` waits indefinitely (drain-or-hang). A timed-out or
    otherwise-interrupted await still cancels the task (so its ``finally`` blocks
    run) so no owned task is left pending. No-op if ``task`` is already done.
    """
    if task.done():
        return
    try:
        await asyncio.wait_for(task, timeout)
    except TimeoutError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    except BaseException:
        # The await itself was cancelled: cancel the task too, then re-raise.
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        raise


class Bus:
    """A descriptor-keyed pub/sub bus: fan-out to ``N`` handlers per event.

    :meth:`subscribe` appends a handler to an event's fan-out list (and returns
    an idempotent unsubscribe callable); :meth:`publish` enqueues a payload for
    the worker to fan out to every subscriber of that event. The bus owns a
    background worker task draining a channel; tear it down with
    :meth:`aclose` (or :meth:`end` to stop accepting events while letting
    already-published ones drain).
    """

    __slots__ = ("_reader", "_writer", "_handlers", "_task")

    def __init__(self) -> None:
        channel_pair: ChannelPair[tuple[object, object]] = create_channel()
        self._reader = channel_pair.reader
        self._writer = channel_pair.writer
        # Heterogeneous registry: the per-event TPayload relationship cannot be
        # tracked through a runtime dict, so storage is erased to ``object`` and
        # recovered with ``cast`` at the typed API boundary — mirroring
        # :class:`~otter_ai_core.hook_runner.HookRunner`. The public API stays
        # fully type-safe; only the internals are erased.
        self._handlers: dict[object, list[object]] = {}
        self._task: asyncio.Task[None] = asyncio.create_task(self._run())

    async def _run(self) -> None:
        async for event, payload in self._reader:
            for handler in self._handlers.get(event, ()):
                try:
                    await cast(BusHandler[object], handler)(payload)
                except Exception:
                    # Isolate the subscriber: log and keep dispatching. Do not
                    # catch BaseException — CancelledError must propagate so the
                    # worker can be torn down on aclose().
                    _logger.error(
                        "bus handler raised for %r; continuing",
                        event,
                        exc_info=True,
                    )

    def subscribe[TPayload](
        self, event: BusEvent[TPayload], handler: BusHandler[TPayload]
    ) -> Callable[[], None]:
        """Append ``handler`` to ``event``'s fan-out list; return an unsubscribe callable.

        The returned callable removes the handler and is idempotent — calling
        it more than once is a no-op after the first.

        ``TPayload`` is inferred from ``event``, so the handler's signature is
        checked against the event's payload type.
        """
        self._handlers.setdefault(event, []).append(handler)
        removed = False

        def _unsubscribe() -> None:
            nonlocal removed
            if removed:
                return
            removed = True
            with contextlib.suppress(ValueError):  # already gone / never added
                self._handlers[event].remove(handler)

        return _unsubscribe

    def publish[TPayload](self, event: BusEvent[TPayload], payload: TPayload) -> None:
        """Enqueue ``payload`` for the worker to fan out to ``event``'s subscribers.

        ``TPayload`` is inferred from ``event``, so ``payload`` is checked
        against the event's payload type. Publishing an event with no
        subscribers is a no-op (the worker fans out to an empty list).
        """
        self._writer.push((event, payload))

    def end(self) -> None:
        """Signal that no more events will be published.

        The worker still drains already-published events (handlers fire for
        them) and then exits. Idempotent (delegates to the channel writer).
        """
        self._writer.end()

    async def aclose(self, timeout: float | None = _DEFAULT_ACLOSE_TIMEOUT) -> None:
        """End the writer and await the worker's drain to completion.

        Lets already-published events reach their handlers, then awaits the
        worker task. ``timeout`` bounds the graceful drain (``None`` waits
        forever — drain-or-hang); if it overruns, the worker is force-cancelled
        so no owned task is left pending. Safe to call more than once.
        """
        self.end()
        await _await_or_cancel(self._task, timeout)
