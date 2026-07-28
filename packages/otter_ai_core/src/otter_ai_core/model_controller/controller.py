from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Self

from otter_ai_core.bus import Bus
from otter_ai_core.context import AssistantContextItem, ToolResultContextItem, UserContextItem
from otter_ai_core.interfaces import AbortableConnection
from otter_ai_core.interfaces.model_controller import (
    BRANCH_MOVED,
    COMPACTION_DONE,
    RESPONSE_DONE,
    SERVER_EVENT_BY_TYPE,
    TOOL_RESULT_ADDED,
    USER_ITEM_ADDED,
)
from otter_ai_core.model_connection import (
    AbortResponse,
    AddUserMessage,
    BranchMove,
    BranchMoved,
    ClientContextEvent,
    CompactionDone,
    CreateCompaction,
    CreateResponse,
    InputEvent,
    ResponseDone,
    ServerContextEvent,
    ServerContextEventType,
    ToolResultAdded,
    UserItemAdded,
)
from otter_ai_core.model_controller._lifecycle import await_or_cancel
from otter_ai_core.model_controller.state import State

#: Default graceful-drain deadline (seconds) for :meth:`DefaultModelController.aclose`.
#: ``None`` would wait forever; a finite default keeps teardown deterministic
#: when the backend never ends the inbound stream.
_DEFAULT_ACLOSE_TIMEOUT: float = 5.0

_log = logging.getLogger(__name__)


class DefaultModelController:
    __slots__ = ("_client", "_bus", "_state", "_task", "_command_waiter")

    def __init__(self, client: AbortableConnection[ServerContextEvent, ClientContextEvent]) -> None:
        self._client = client
        self._bus: Bus = Bus()
        self._state = State()
        self._command_waiter: asyncio.Event | None = None
        self._task: asyncio.Task[None] = asyncio.create_task(self._run())

    # ------------------------------------------------------------------ #
    # Read-only views
    # ------------------------------------------------------------------ #

    @property
    def bus(self) -> Bus:
        return self._bus

    @property
    def state(self) -> State:
        return self._state

    def is_idle(self) -> bool:
        return self._state.is_idle.is_set()

    async def wait_for_idle(self) -> None:
        await self._state.wait_for_idle()

    def on(
        self,
        event: ServerContextEventType,
        handler: Callable[[ServerContextEvent], Awaitable[None]],
    ) -> Callable[[], None]:
        return self._bus.subscribe(SERVER_EVENT_BY_TYPE[event], handler)

    def is_closing(self) -> bool:
        return self._state.is_closing

    async def wait_idle(self) -> None:
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
        self._require_running()
        self._check_idle()
        self._state.set_busy()
        added = asyncio.Event()
        self._command_waiter = added
        received = False
        item: UserContextItem | ToolResultContextItem | None

        async def _on_added(event: UserItemAdded | ToolResultAdded) -> None:
            nonlocal received, item
            item = event.item
            received = True
            added.set()

        # Subscribe only to the echo that matches this input type, so a stray
        # mismatched item-added event cannot release the command early. The
        # wider ``_on_added`` handler (contravariance) satisfies either
        # per-variant descriptor; subscribe in-branch so each call binds a
        # single concrete descriptor.
        if isinstance(message, AddUserMessage):
            unsub = self._bus.subscribe(USER_ITEM_ADDED, _on_added)
        else:
            unsub = self._bus.subscribe(TOOL_RESULT_ADDED, _on_added)
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
            case UserContextItem() | ToolResultContextItem():
                return item
            case _:
                raise RuntimeError("Add message did not receive an item")

    async def generate(self) -> AssistantContextItem:
        self._require_running()
        self._check_idle()
        self._state.set_busy()
        done = asyncio.Event()
        self._command_waiter = done
        received = False
        item: AssistantContextItem | None

        async def _on_done(event: ResponseDone) -> None:
            nonlocal received, item
            item = event.item
            received = True
            done.set()

        unsub = self._bus.subscribe(RESPONSE_DONE, _on_done)
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
        match item:
            case AssistantContextItem():
                return item
            case _:
                raise RuntimeError("Generate did not receive an item")

    async def compact(
        self,
        *,
        first_kept_item_id: str | None = None,
        custom_instructions: str | None = None,
        summary: str | None = None,
    ) -> CompactionDone:
        self._require_running()
        self._check_idle()
        self._state.set_busy()
        done = asyncio.Event()
        self._command_waiter = done
        received = False
        result: CompactionDone | None

        async def _on_done(event: CompactionDone) -> None:
            nonlocal received, result
            result = event
            received = True
            done.set()

        unsub = self._bus.subscribe(COMPACTION_DONE, _on_done)
        self._client.push(
            CreateCompaction(
                first_kept_item_id=first_kept_item_id,
                custom_instructions=custom_instructions,
                summary=summary,
            )
        )
        try:
            await done.wait()
        finally:
            self._command_waiter = None
            unsub()
        if not received:
            # Released by teardown (the run-loop exit path in ``_run``'s
            # finally) rather than by the confirm handler — see
            # :meth:`add_message` for the FIFO reasoning that makes this check
            # sound.
            raise RuntimeError("ModelController run loop exited before compaction.done arrived.")
        self._state.set_idle()
        match result:
            case CompactionDone():
                return result
            case _:
                raise RuntimeError("Compact did not receive a confirm")

    async def branch(
        self,
        at_item_id: str,
        *,
        summary: str | None = None,
    ) -> BranchMoved:
        self._require_running()
        self._check_idle()
        self._state.set_busy()
        done = asyncio.Event()
        self._command_waiter = done
        received = False
        result: BranchMoved | None

        async def _on_done(event: BranchMoved) -> None:
            nonlocal received, result
            result = event
            received = True
            done.set()

        unsub = self._bus.subscribe(BRANCH_MOVED, _on_done)
        self._client.push(BranchMove(at_item_id=at_item_id, summary=summary))
        try:
            await done.wait()
        finally:
            self._command_waiter = None
            unsub()
        if not received:
            # Released by teardown (the run-loop exit path in ``_run``'s
            # finally) rather than by the confirm handler — see
            # :meth:`add_message` for the FIFO reasoning that makes this check
            # sound.
            raise RuntimeError("ModelController run loop exited before branch.moved arrived.")
        self._state.set_idle()
        match result:
            case BranchMoved():
                return result
            case _:
                raise RuntimeError("Branch did not receive a confirm")

    def abort(self) -> None:
        self._require_running()
        if self.is_idle():
            raise RuntimeError("Cannot abort a response when idle.")
        self._client.push(AbortResponse())

    # ------------------------------------------------------------------ #
    # Lifecycle / teardown
    # ------------------------------------------------------------------ #

    def close(self) -> None:
        if self._state.is_closing:
            return
        self._state.begin_closing()
        self._client.abort()

    async def aclose(self, timeout: float | None = _DEFAULT_ACLOSE_TIMEOUT) -> None:
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
                self._bus.publish(SERVER_EVENT_BY_TYPE[event.type], event)
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
            # the in-flight command method once its confirmation event arrives).
            # Whether the backend ended the inbound
            # gracefully or we were cancelled, also stop the bus so its worker
            # can drain and exit. Release an in-flight command await too, so
            # add_message/generate parked on their confirmation event are not
            # stranded when the drain loop exits.
            self._state.set_idle()
            if self._command_waiter is not None:
                self._command_waiter.set()
            self._bus.end()
