"""A high-level controller that drives a model connection.

A :class:`ModelController` wraps a
:data:`~otter_ai_core.model_connection.ModelConnectionClient` and turns the
low-level push/iterate/abort conduit into a conversation: it appends input
(``user_message.add`` / ``tool_result.add``), asks the server to generate
(``response.create``), asks it to stop the current generation
(``response.abort``), and tracks idle/busy state from the inbound
``response.done`` events. Every inbound server event is also re-published to a
:class:`~otter_ai_core.bus.Bus` for fan-out to subscribers (renderers,
persistence, metrics, …).

Async, confirmation-awaiting commands
-------------------------------------
The command surface is **async** and **awaits a backend confirmation** before
returning:

* :meth:`add_message` — pushes a ``user_message.add`` / ``tool_result.add``
  client event and awaits the matching ``user_item.added`` /
  ``tool_result_item.added`` server echo. Call it one or more times to stage
  input.
* :meth:`generate` — pushes ``response.create`` and awaits the matching
  ``response.done``.

Both are single-flight (rejected while busy) and never hang: if the run loop
exits before the awaited echo arrives — teardown via :meth:`close` /
:meth:`aclose`, or a non-conformant backend that ends the inbound early — the
awaiting command is released and raises :class:`RuntimeError` rather than
stranding its task.

Two distinct aborts
-------------------
The controller exposes **two** concepts that are easy to confuse:

* :meth:`ModelController.abort` — *protocol* abort. It pushes an
  :class:`~otter_ai_core.model_connection.AbortResponse`, i.e. "stop the
  current generation but keep the connection open; I want to keep talking."
  Only valid while a generation is in progress (busy).
* :meth:`ModelController.close` / :meth:`ModelController.aclose` — *runtime*
  teardown. They call
  :meth:`~otter_ai_core.connection.ConnectionClient.abort`, i.e. "I am done
  with this connection; tear it down." This sets the cooperative abort signal
  and closes the outbound so the backend can begin its shutdown.

Lifecycle / teardown
--------------------
Teardown is **cooperative first, deterministic second**:

* :meth:`close` is synchronous and only *initiates* teardown
  (``client.abort()``). It does **not** cancel anything — the controller keeps
  draining inbound so the backend's shutdown sequence (which may emit final
  items) flows through the bus. ``close`` is fire-and-forget and idempotent.
* :meth:`aclose` awaits the drain to completion under a deadline and is the
  recommended way to tear down. If the backend never ends the inbound (a
  non-conformant/wedged backend), the controller's run task — and the bus's
  worker — are force-cancelled once the deadline elapses, so no owned task is
  left pending. (This deterministic cancel is the last resort in place of
  relying on garbage collection, which would abandon pending tasks with a
  ``Task was destroyed but it is pending!`` warning and run no ``finally``
  cleanup.) ``aclose`` is also available via ``async with``.

Once :meth:`close` / :meth:`aclose` has begun, the command methods
(:meth:`add_message`, :meth:`generate`, :meth:`abort`) reject with
:class:`RuntimeError`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from types import TracebackType
from typing import Self

from otter_ai_core.bus import Bus, BusHandler
from otter_ai_core.context import ToolResultContextItem, UserContextItem
from otter_ai_core.model_connection import (
    AbortResponse,
    AddToolResultMessage,
    AddUserMessage,
    CreateResponse,
    ModelConnectionClient,
    ServerContextEvent,
    ServerContextEventType,
    ToolResultAdded,
    UserItemAdded,
)
from otter_ai_core.model_controller._lifecycle import await_or_cancel
from otter_ai_core.model_controller.state import State

#: Default graceful-drain deadline (seconds) for :meth:`ModelController.aclose`.
#: ``None`` would wait forever; a finite default keeps teardown deterministic
#: when the backend never ends the inbound stream.
_DEFAULT_ACLOSE_TIMEOUT: float = 5.0

#: A client→server event that appends conversation input before a generation.
InputEvent = AddUserMessage | AddToolResultMessage

_log = logging.getLogger(__name__)

#: An async subscriber invoked for a matching inbound server event.
type ModelControllerHandler = BusHandler[ServerContextEvent]


class ModelController:
    """Drive a :data:`ModelConnectionClient` as a stateful conversation.

    Construct with a client (typically the ``client`` end of a
    :func:`~otter_ai_core.connection.create_connection` whose backend is pumped
    by a transport task). The controller starts **idle**. Use
    :meth:`add_message` to append input (awaiting the server's echo),
    :meth:`generate` to request and await the next assistant response, and
    :meth:`abort` to cancel an in-flight response. Subscribe to inbound events
    via the :attr:`bus`.

    Tear down with ``await controller.aclose()`` (or ``async with``); see the
    module docstring for the two-abort distinction and the cooperative-then-
    deterministic teardown model.

    .. note::
       The constructor schedules a background drain task and so must be called
       from within a running :mod:`asyncio` event loop.
    """

    __slots__ = ("_client", "_bus", "_state", "_task", "_command_waiter")

    def __init__(self, client: ModelConnectionClient) -> None:
        self._client = client
        self._bus: Bus[ServerContextEventType, ServerContextEvent] = Bus(ServerContextEventType)
        self._state = State()
        self._command_waiter: asyncio.Event | None = None
        self._task: asyncio.Task[None] = asyncio.create_task(self._run())

    # ------------------------------------------------------------------ #
    # Read-only views
    # ------------------------------------------------------------------ #

    @property
    def bus(self) -> Bus[ServerContextEventType, ServerContextEvent]:
        """The pub/sub bus every inbound server event is re-published to."""
        return self._bus

    @property
    def state(self) -> State:
        """The controller's mutable :class:`State` (idle/busy latch, closing flag)."""
        return self._state

    def is_idle(self) -> bool:
        """``True`` when no generation is in progress (commands are accepted)."""
        return self._state.is_idle.is_set()

    async def wait_for_idle(self) -> None:
        await self._state.wait_for_idle()

    def on(
        self, event_type: ServerContextEventType, handler: ModelControllerHandler
    ) -> Callable[[], None]:
        return self._bus.subscribe(event_type, handler)

    def is_closing(self) -> bool:
        """``True`` once teardown has begun (commands are then rejected)."""
        return self._state.is_closing

    async def wait_idle(self) -> None:
        """Block until the controller is idle (e.g. the current generation finished)."""
        await self._state.is_idle.wait()

    # ------------------------------------------------------------------ #
    # Commands (rejected once closing, or while busy)
    # ------------------------------------------------------------------ #

    def _require_running(self) -> None:
        if self._state.is_closing:
            raise RuntimeError("ModelController is closing/closed; commands are rejected.")

    def _check_idle(self) -> None:
        if not self.is_idle():
            raise RuntimeError("ModelController is busy; command rejected.")

    async def add_message(self, message: InputEvent) -> UserContextItem | ToolResultContextItem:
        """Append one conversation input and await the server's item-added echo.

        Pushes a ``user_message.add`` / ``tool_result.add`` client event, flips
        the controller to busy, and blocks until the backend echoes the matching
        ``user_item.added`` / ``tool_result_item.added`` server event, then
        returns to idle. Call one or more times to stage input before
        :meth:`generate`.

        Returns the echoed :class:`~otter_ai_core.context.UserContextItem` /
        :class:`~otter_ai_core.context.ToolResultContextItem` (carrying the
        server-assigned ``id``), matching the type of ``message``.

        Raises :class:`RuntimeError` if the controller is closing/closed or
        already busy, or if the run loop exits before the echo arrives
        (teardown / non-conformant backend) — the await never hangs.
        """
        self._require_running()
        self._check_idle()
        self._state.set_busy()
        added = asyncio.Event()
        self._command_waiter = added
        received = False
        item: UserContextItem | ToolResultContextItem | None

        async def _on_added(event: ServerContextEvent) -> None:
            nonlocal received, item
            match event:
                case UserItemAdded() | ToolResultAdded():
                    item = event.item
            received = True
            added.set()

        # Subscribe only to the echo that matches this input type, so a stray
        # mismatched item-added event cannot release the command early.
        echo_type = (
            ServerContextEventType.USER_ITEM_ADDED
            if isinstance(message, AddUserMessage)
            else ServerContextEventType.TOOL_RESULT_ADDED
        )
        unsub = self._bus.subscribe(echo_type, _on_added)
        self._client.push(message)
        try:
            await added.wait()
        finally:
            self._command_waiter = None
            unsub()
        if not received:
            # We were released by teardown (the run-loop exit path in
            # ``_run``'s finally) rather than by the echo handler, so the
            # awaited confirmation never truly arrived. asyncio's FIFO
            # scheduling guarantees the converse: if ``_run`` published the
            # echo before exiting, the bus worker dispatched it — and thus ran
            # ``_on_added`` — before we resume, so ``received`` would be True.
            raise RuntimeError(
                "ModelController run loop exited before the item-added echo arrived."
            )
        self._state.set_idle()
        match item:
            case UserContextItem():
                return item
            case ToolResultContextItem():
                return item
            case _:
                raise RuntimeError("Add message did not receive an item")

    async def generate(self) -> None:
        """Request the next assistant response and await its completion.

        Pushes ``response.create``, flips the controller to busy, and blocks
        until the backend emits the matching ``response.done``, then returns to
        idle. Stage any input with :meth:`add_message` first.

        Raises :class:`RuntimeError` if the controller is closing/closed or
        already busy, or if the run loop exits before ``response.done`` arrives
        (teardown / non-conformant backend) — the await never hangs.
        """
        self._require_running()
        self._check_idle()
        self._state.set_busy()
        done = asyncio.Event()
        self._command_waiter = done
        received = False

        async def _on_done(_event: ServerContextEvent) -> None:
            nonlocal received
            received = True
            done.set()

        unsub = self._bus.subscribe(ServerContextEventType.RESPONSE_DONE, _on_done)
        self._client.push(CreateResponse())
        try:
            await done.wait()
        finally:
            self._command_waiter = None
            unsub()
        if not received:
            # Released by teardown rather than by the response.done handler —
            # see :meth:`add_message` for the FIFO reasoning that makes this
            # check sound.
            raise RuntimeError("ModelController run loop exited before response.done arrived.")
        self._state.set_idle()

    def abort(self) -> None:
        """Protocol-abort the in-progress generation, keeping the connection open.

        Pushes an :class:`~otter_ai_core.model_connection.AbortResponse` (a
        *protocol* event distinct from the *runtime* ``client.abort()`` used by
        :meth:`close`). Only valid while busy; the controller returns to idle
        when the server honours the abort with a ``response.done``.
        """
        self._require_running()
        if self.is_idle():
            raise RuntimeError("Cannot abort a response when idle.")
        self._client.push(AbortResponse())

    # ------------------------------------------------------------------ #
    # Lifecycle / teardown
    # ------------------------------------------------------------------ #

    def close(self) -> None:
        """Initiate cooperative teardown (synchronous, idempotent, fire-and-forget).

        Calls :meth:`~otter_ai_core.connection.ConnectionClient.abort`
        (runtime abort: sets the cooperative abort signal and closes the
        outbound) so a conformant backend begins its shutdown — emitting any
        final items, which the controller keeps draining through the
        :attr:`bus`, before ending the inbound. Does **not** cancel the run
        task; for awaited, deadline-bounded teardown use :meth:`aclose`.
        """
        if self._state.is_closing:
            return
        self._state.begin_closing()
        self._client.abort()

    async def aclose(self, timeout: float | None = _DEFAULT_ACLOSE_TIMEOUT) -> None:
        """Initiate teardown and await the drain to completion.

        Calls :meth:`close`, then awaits the controller's run task (which drains
        the backend's final shutdown items and ends the bus) under ``timeout``
        (``None`` waits forever — drain-or-hang). If the drain overruns — a
        non-conformant backend that never ends the inbound — the run task and
        the bus worker are force-cancelled so no owned task is left pending.
        Safe to call more than once.
        """
        self.close()
        try:
            await await_or_cancel(self._task, timeout)
        finally:
            # Always reap the bus worker — even if the await above was cancelled
            # mid-flight — so no owned task is left pending.
            await self._bus.aclose(timeout)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ #
    # Inbound drain loop
    # ------------------------------------------------------------------ #

    async def _run(self) -> None:
        try:
            async for event in self._client:
                if event.type == ServerContextEventType.RESPONSE_DONE:
                    self._state.set_idle()
                self._bus.publish(event)
        except asyncio.CancelledError:
            raise  # teardown (aclose); expected — let the finally clean up
        except Exception:
            # An unexpected failure in the drain loop: log it (diagnostics) and
            # let the task end cleanly rather than dying with an unretrieved
            # exception. The finally still releases wait_idle() and stops the bus.
            _log.error("model controller drain loop exited unexpectedly", exc_info=True)
        finally:
            # Defensively release any waiter: on an abnormal exit (unexpected
            # error or cancellation) a caller parked on wait_idle() must not
            # hang. Idempotent on the normal exit path (idle is already set by
            # the response.done handler). Whether the backend ended the inbound
            # gracefully or we were cancelled, also stop the bus so its worker
            # can drain and exit. Release an in-flight command await too, so
            # add_message/generate parked on their confirmation event are not
            # stranded when the drain loop exits.
            self._state.set_idle()
            if self._command_waiter is not None:
                self._command_waiter.set()
            self._bus.end()
