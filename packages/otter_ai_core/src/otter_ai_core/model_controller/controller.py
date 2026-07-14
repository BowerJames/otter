"""A high-level controller that drives a model connection.

A :class:`ModelController` wraps a
:data:`~otter_ai_core.model_connection.ModelConnectionClient` and turns the
low-level push/iterate/abort conduit into a conversation: it appends input
(``user_message.add`` / ``tool_result.add``), asks the server to generate
(``response.create``), asks it to stop the current generation
(``response.abort``), and tracks idle/busy state from the inbound
``response.done`` events. Every inbound server event is also re-published to a
:class:`~otter_ai_core.model_controller.bus.ModelBus` for fan-out to
subscribers (renderers, persistence, metrics, …).

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
(:meth:`generate`, :meth:`add_messages`, :meth:`abort`) reject with
:class:`RuntimeError`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from types import TracebackType
from typing import Self

from otter_ai_core.model_connection import (
    AbortResponse,
    AddToolResultMessage,
    AddUserMessage,
    CreateResponse,
    ModelConnectionClient,
    ServerContextEventType,
)
from otter_ai_core.model_controller.bus import ModelBus
from otter_ai_core.model_controller.state import State

#: Default graceful-drain deadline (seconds) for :meth:`ModelController.aclose`.
#: ``None`` would wait forever; a finite default keeps teardown deterministic
#: when the backend never ends the inbound stream.
_DEFAULT_ACLOSE_TIMEOUT: float = 5.0

#: A client→server event that appends conversation input before a generation.
InputEvent = AddUserMessage | AddToolResultMessage

_log = logging.getLogger(__name__)


class ModelController:
    """Drive a :data:`ModelConnectionClient` as a stateful conversation.

    Construct with a client (typically the ``client`` end of a
    :func:`~otter_ai_core.connection.create_connection` whose backend is pumped
    by a transport task). The controller starts **idle**. Use
    :meth:`generate` to send input and request a response; :meth:`abort` to
    cancel the in-flight response; :meth:`add_messages` to append input without
    requesting a response. Subscribe to inbound events via the :attr:`bus`.

    Tear down with ``await controller.aclose()`` (or ``async with``); see the
    module docstring for the two-abort distinction and the cooperative-then-
    deterministic teardown model.

    .. note::
       The constructor schedules a background drain task and so must be called
       from within a running :mod:`asyncio` event loop.
    """

    __slots__ = ("_client", "_bus", "_state", "_task")

    def __init__(self, client: ModelConnectionClient) -> None:
        self._client = client
        self._bus = ModelBus()
        self._state = State()
        self._task: asyncio.Task[None] = asyncio.create_task(self._run())

    # ------------------------------------------------------------------ #
    # Read-only views
    # ------------------------------------------------------------------ #

    @property
    def bus(self) -> ModelBus:
        """The pub/sub bus every inbound server event is re-published to."""
        return self._bus

    @property
    def state(self) -> State:
        """The controller's mutable :class:`State` (idle/busy latch, closing flag)."""
        return self._state

    def is_idle(self) -> bool:
        """``True`` when no generation is in progress (commands are accepted)."""
        return self._state.is_idle.is_set()

    def is_closing(self) -> bool:
        """``True`` once teardown has begun (commands are then rejected)."""
        return self._state.is_closing

    async def wait_idle(self) -> None:
        """Block until the controller is idle (e.g. the current generation finished)."""
        await self._state.is_idle.wait()

    # ------------------------------------------------------------------ #
    # Commands (rejected once closing)
    # ------------------------------------------------------------------ #

    def _require_running(self) -> None:
        if self._state.is_closing:
            raise RuntimeError(
                "ModelController is closing/closed; commands are rejected."
            )

    def add_messages(self, messages: list[InputEvent]) -> None:
        """Append conversation input (user messages / tool results) without generating.

        Only valid while idle. The items are pushed as
        ``user_message.add`` / ``tool_result.add`` client events for the server
        to echo back as items.
        """
        self._require_running()
        if not self.is_idle():
            raise RuntimeError(
                "Cannot add messages while a response generation is in progress."
            )
        for message in messages:
            self._client.push(message)

    def generate(self, messages: list[InputEvent]) -> None:
        """Append conversation input and request the next assistant response.

        Flips the controller to busy, pushes the input, then pushes
        ``response.create``. The controller returns to idle when the matching
        ``response.done`` arrives.
        """
        self._require_running()
        if not self.is_idle():
            raise RuntimeError(
                "Cannot generate a response while one is already in progress."
            )
        self._state.set_busy()
        for message in messages:
            self._client.push(message)
        self._client.push(CreateResponse())

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
        await _await_or_cancel(self._task, timeout)
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
            # can drain and exit.
            self._state.set_idle()
            self._bus.end()


async def _await_or_cancel(task: asyncio.Task[None], timeout: float | None) -> None:
    """Await ``task`` for up to ``timeout`` seconds; force-cancel if it overruns.

    ``timeout`` of ``None`` waits indefinitely (drain-or-hang). A timed-out or
    otherwise-interrupted await still cancels the task (running its ``finally``
    blocks) so no owned task is left pending.
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
