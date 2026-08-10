from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from types import NoneType

from otter_ai_core.data_models.context import (
    AssistantContextItem,
    ToolResultContextItem,
    UserContextItem,
)
from otter_ai_core.data_models.events import (
    AbortResponse,
    AddUserMessage,
    BranchMove,
    BranchMoved,
    CompactionDone,
    CreateCompaction,
    CreateResponse,
    InputEvent,
    ResponseDone,
    ResponseStarted,
    ResponseUpdated,
    ServerContextEventType,
    ToolResultAdded,
    UserItemAdded,
    UserItemUpdated,
)
from otter_ai_core.interfaces.roles import EventRunner, ModelConnection, ModelController
from otter_ai_core.mixins import TaskRunnerMixIn
from otter_ai_core.runtime.bus import create_bus
from otter_ai_core.runtime.default_model_controller.state import State

_log = logging.getLogger(__name__)

#: Maps each inbound server event type to the concrete class every emitted
#: payload must be an instance of. Registered on the controller's Bus at
#: construction so ``emit`` can validate payloads.
_SERVER_EVENT_TRIGGER_TYPES: dict[ServerContextEventType, type[object]] = {
    ServerContextEventType.RESPONSE_STARTED: ResponseStarted,
    ServerContextEventType.RESPONSE_UPDATED: ResponseUpdated,
    ServerContextEventType.RESPONSE_DONE: ResponseDone,
    ServerContextEventType.USER_ITEM_ADDED: UserItemAdded,
    ServerContextEventType.USER_ITEM_UPDATED: UserItemUpdated,
    ServerContextEventType.TOOL_RESULT_ADDED: ToolResultAdded,
    ServerContextEventType.COMPACTION_DONE: CompactionDone,
    ServerContextEventType.BRANCH_MOVED: BranchMoved,
}


class DefaultModelController(TaskRunnerMixIn, ModelController):
    def __init__(
        self,
        client: ModelConnection,
        event_runner_factory: Callable[[], EventRunner] = create_bus,
    ) -> None:
        self._client = client
        self._bus: EventRunner = event_runner_factory()
        for name, trigger_type in _SERVER_EVENT_TRIGGER_TYPES.items():
            self._bus.register(name, trigger_type, NoneType)
        self._state = State()
        self._command_waiter: asyncio.Event | None = None

    # ------------------------------------------------------------------ #
    # Read-only views
    # ------------------------------------------------------------------ #

    @property
    def bus(self) -> EventRunner:
        return self._bus

    @property
    def state(self) -> State:
        return self._state

    def is_idle(self) -> bool:
        return self._state.is_idle.is_set()

    async def wait_for_idle(self) -> None:
        await self._state.wait_for_idle()

    def on(self, type: str, handler: Callable[..., object]) -> Callable[[], None]:
        return self._bus.on(type, handler)

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
            unsub = self._bus.on(ServerContextEventType.USER_ITEM_ADDED, _on_added)
        else:
            unsub = self._bus.on(ServerContextEventType.TOOL_RESULT_ADDED, _on_added)
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

        unsub = self._bus.on(ServerContextEventType.RESPONSE_DONE, _on_done)
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

        unsub = self._bus.on(ServerContextEventType.COMPACTION_DONE, _on_done)
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

        unsub = self._bus.on(ServerContextEventType.BRANCH_MOVED, _on_done)
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

    def end(self) -> None:
        if self._state.is_closing:
            return
        self._state.begin_closing()
        self._client.end()

    def _register_tasks(self, tg: asyncio.TaskGroup) -> None:
        tg.create_task(self._run())
        tg.create_task(self._run_bus())

    async def _run_bus(self) -> None:
        # Own the bus sub-lifecycle: entering starts its drain, exiting reaps
        # it (cancellation-safe). ``await self._bus`` parks here until the bus
        # ends — which happens when ``_run``'s finally calls ``self._bus.end()``
        # once the connection finishes draining.
        async with self._bus:
            await self._bus

    # ------------------------------------------------------------------ #
    # Inbound drain loop
    # ------------------------------------------------------------------ #

    async def _run(self) -> None:
        try:
            async for event in self._client:
                await self._bus.emit(event.type, event)
        except asyncio.CancelledError:
            raise  # teardown; expected — let the finally clean up
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
