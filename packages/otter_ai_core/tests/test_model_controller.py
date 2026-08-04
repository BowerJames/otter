"""ModelController / State: async commands, fan-out, lifecycle, teardown.

Tests exercise the concerns of the ``default_model_controller`` package:

* :class:`State` — the idle/busy latch (starts idle) and the closing flag;
* :class:`DefaultModelController` — the async, confirmation-awaiting commands
  (:meth:`~DefaultModelController.add_message` / :meth:`~DefaultModelController.generate`),
  the busy/closing guards, idle tracking, bus fan-through, the no-strand
  teardown guarantee for in-flight commands, and the cooperative-then-
  deterministic teardown model.

The controller tests stand up a real ``create_connection()`` pair: the
controller drives ``pair.client`` and the test pushes server events on
``pair.backend`` (and drains the client→server events the controller pushes).
A small ``_conformant_backend`` task honours the abort contract — on
``abort_signal`` it ends the inbound so the controller's drain completes.

Name-keyed bus behaviour (fan-out, per-name dispatch,
idempotent unsubscribe, no-subscriber no-op, per-handler isolation,
end/aclose semantics) is covered in ``tests/test_bus.py``; the controller's
bus is the same :class:`~otter_ai_core.bus.Bus`, with its event names keyed on
:class:`~otter_ai_core.data_models.ServerContextEventType`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from otter_ai_core import (
    AssistantContextItem,
    AssistantMessage,
    StopReason,
    TextContent,
    ToolResultContextItem,
    ToolResultMessage,
    Usage,
    UsageCost,
    UserContextItem,
    UserMessage,
)
from otter_ai_core.context import Role
from otter_ai_core.data_models import (
    AbortResponse,
    AddToolResultMessage,
    AddUserMessage,
    BranchMove,
    BranchMoved,
    ClientContextEvent,
    ClientContextEventType,
    CompactionDone,
    CreateCompaction,
    ResponseDone,
    ResponseStarted,
    ResponseUpdated,
    ServerContextEvent,
    ServerContextEventType,
    ToolResultAdded,
    UserItemAdded,
    UserItemUpdated,
)
from otter_ai_core.default_model_controller import RESPONSE_DONE, DefaultModelController, State
from otter_ai_core.interfaces import ModelController
from tests._connection import ConnectionBackend, ConnectionPair, create_connection


def _default_controller_satisfies_protocol(
    controller: DefaultModelController,
) -> ModelController:
    # Structural conformance guard: mypy verifies DefaultModelController
    # satisfies the ModelController Protocol here (this file is in the mypy
    # ``files`` set). Never called at runtime.
    return controller


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def _usage() -> Usage:
    return Usage(
        input=10,
        output=5,
        cache_read=0,
        cache_write=0,
        total_tokens=15,
        cost=UsageCost(input=0.0, output=0.0, cache_read=0.0, cache_write=0.0, total=0.0),
    )


def _assistant_message(
    stop_reason: StopReason | None = StopReason.Stop,
) -> AssistantMessage:
    return AssistantMessage(
        role=Role.Assistant,
        content=[TextContent(type="text", text="hi")],
        api="responses",
        provider="openai",
        model="gpt-test",
        usage=_usage(),
        stop_reason=stop_reason,
        timestamp=0,
    )


def _assistant_item(
    stop_reason: StopReason | None = StopReason.Stop,
) -> AssistantContextItem:
    return AssistantContextItem(id="a1", message=_assistant_message(stop_reason))


def _user_message() -> UserMessage:
    return UserMessage(role=Role.User, content="hi", timestamp=0)


def _user_item() -> UserContextItem:
    return UserContextItem(id="u1", message=_user_message())


def _tool_result_message() -> ToolResultMessage:
    return ToolResultMessage(
        role=Role.ToolResult,
        tool_call_id="t1",
        tool_name="get_time",
        content=[TextContent(type="text", text="noon")],
        is_error=False,
        timestamp=0,
    )


def _tool_result_item() -> ToolResultContextItem:
    return ToolResultContextItem(id="tr1", message=_tool_result_message())


def _input() -> AddUserMessage:
    return AddUserMessage(message=_user_message())


def _compaction_done() -> CompactionDone:
    return CompactionDone(
        summary="compacted history",
        summary_item_id="cs1",
        first_kept_item_id="k1",
        removed_item_ids=["r1", "r2"],
        tokens_before=100,
        usage=_usage(),
    )


def _branch_moved() -> BranchMoved:
    return BranchMoved(
        at_item_id="u1",
        removed_item_ids=["a1"],
        summary_item_id="bs1",
    )


@asynccontextmanager
async def _pair() -> AsyncIterator[
    tuple[DefaultModelController, ConnectionBackend[ClientContextEvent, ServerContextEvent]]
]:
    """A controller wired to a fresh connection pair; yields (controller, backend).

    The controller is entered on entry. On exit the backend's inbound is ended
    cooperatively (so the controller drain finishes) and the controller is
    closed — no force-cancel under normal teardown.
    """
    pair: ConnectionPair[ClientContextEvent, ServerContextEvent] = create_connection()
    controller = DefaultModelController(pair.client)
    await controller.__aenter__()
    try:
        yield controller, pair.backend
    finally:
        controller.close()
        pair.backend.end()
        await controller.__aexit__(None, None, None)


async def _take(
    backend: ConnectionBackend[ClientContextEvent, ServerContextEvent],
    n: int,
) -> list[ClientContextEvent]:
    """Read ``n`` client→server events the controller pushed (none blocking)."""
    return [await asyncio.wait_for(anext(backend), 1) for _ in range(n)]


async def _conformant(
    backend: ConnectionBackend[ClientContextEvent, ServerContextEvent],
) -> None:
    """A backend that honours the abort contract: on abort, end the inbound."""
    await backend.wait_for_abort()
    backend.end()


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #


def test_state_starts_idle_and_open() -> None:
    s = State()
    assert s.is_idle.is_set() is True  # the idle-init bug fix
    assert s.is_closing is False


def test_state_busy_idle_round_trip() -> None:
    s = State()
    s.set_busy()
    assert s.is_idle.is_set() is False
    s.set_idle()
    assert s.is_idle.is_set() is True


def test_state_closing_flag() -> None:
    s = State()
    assert s.is_closing is False
    s.begin_closing()
    assert s.is_closing is True


async def test_state_wait_idle_returns_when_set() -> None:
    s = State()  # idle already
    await asyncio.wait_for(s.is_idle.wait(), 1)


# --------------------------------------------------------------------------- #
# DefaultModelController: construction & idle tracking
# --------------------------------------------------------------------------- #


async def test_controller_starts_idle() -> None:
    async with _pair() as (controller, _backend):
        assert controller.is_idle() is True
        assert controller.is_closing() is False


async def test_generate_flips_busy_then_idle_on_done() -> None:
    async with _pair() as (controller, backend):
        assert controller.is_idle()

        task = asyncio.create_task(controller.generate())
        pushed = await _take(backend, 1)
        assert pushed[0].type == ClientContextEventType.CREATE_RESPONSE
        assert controller.is_idle() is False  # busy

        backend.push(ResponseStarted(partial=_assistant_item()))
        backend.push(ResponseDone(item=_assistant_item()))
        result = await asyncio.wait_for(task, 1)  # generate returned to idle
        assert result == _assistant_item()

        assert controller.is_idle()


async def test_controller_bus_narrows_response_done() -> None:
    """A handler on the controller's bus narrows ``ResponseDone`` to ``.item``."""
    async with _pair() as (controller, backend):
        seen: list[str] = []
        done = asyncio.Event()

        async def handler(event: ServerContextEvent) -> None:
            match event.type:
                case ServerContextEventType.RESPONSE_DONE:
                    seen.append(event.item.id)  # strict-mypy narrowing of the union
                    done.set()
                case _:
                    pass

        controller.bus.on(RESPONSE_DONE, handler)
        backend.push(ResponseDone(item=_assistant_item()))
        await asyncio.wait_for(done.wait(), 1)
        assert seen == ["a1"]


# --------------------------------------------------------------------------- #
# DefaultModelController: on() subscription surface (Subscribable)
# --------------------------------------------------------------------------- #


async def test_on_rejects_unknown_type_string() -> None:
    async with _pair() as (controller, _backend):

        async def handler(_event: ServerContextEvent) -> None:
            pass

        with pytest.raises(ValueError):
            controller.on("not.a.real.event", handler)


async def test_on_subscribes_by_type_string_and_fires() -> None:
    async with _pair() as (controller, backend):
        seen: list[str] = []
        done = asyncio.Event()

        async def handler(event: ServerContextEvent) -> None:
            assert event.type == ServerContextEventType.RESPONSE_DONE
            seen.append(event.item.id)
            done.set()

        # The type key is a plain string; the StrEnum value resolves it.
        controller.on(ServerContextEventType.RESPONSE_DONE.value, handler)
        backend.push(ResponseDone(item=_assistant_item()))
        await asyncio.wait_for(done.wait(), 1)
        assert seen == ["a1"]


# --------------------------------------------------------------------------- #
# DefaultModelController: command guards
# --------------------------------------------------------------------------- #


async def test_generate_while_busy_raises() -> None:
    async with _pair() as (controller, backend):
        task = asyncio.create_task(controller.generate())
        await _take(backend, 1)  # CreateResponse pushed; controller busy + parked
        with pytest.raises(RuntimeError, match="busy"):
            await controller.generate()
        # Release the in-flight generation so it doesn't leak.
        backend.push(ResponseDone(item=_assistant_item()))
        await asyncio.wait_for(task, 1)


async def test_add_message_pushes_when_idle() -> None:
    async with _pair() as (controller, backend):
        task = asyncio.create_task(controller.add_message(_input()))
        pushed = await _take(backend, 1)
        assert isinstance(pushed[0], AddUserMessage)
        backend.push(UserItemAdded(item=_user_item()))
        result = await asyncio.wait_for(task, 1)
        assert result == _user_item()
        assert controller.is_idle()


async def test_add_message_rejected_while_busy() -> None:
    async with _pair() as (controller, backend):
        task = asyncio.create_task(controller.generate())
        await _take(backend, 1)  # busy
        with pytest.raises(RuntimeError, match="busy"):
            await controller.add_message(_input())
        backend.push(ResponseDone(item=_assistant_item()))
        await asyncio.wait_for(task, 1)


async def test_add_message_with_tool_result_awaits_tool_result_echo() -> None:
    async with _pair() as (controller, backend):
        task = asyncio.create_task(
            controller.add_message(AddToolResultMessage(message=_tool_result_message()))
        )
        pushed = await _take(backend, 1)
        assert pushed[0].type == ClientContextEventType.ADD_TOOL_RESULT_MESSAGE
        backend.push(ToolResultAdded(item=_tool_result_item()))
        result = await asyncio.wait_for(task, 1)
        assert result == _tool_result_item()
        assert controller.is_idle()


async def test_add_message_ignores_mismatched_echo_type() -> None:
    """An ``AddUserMessage`` await must not complete on a ``ToolResultAdded`` echo."""
    async with _pair() as (controller, backend):
        task = asyncio.create_task(controller.add_message(_input()))
        await _take(backend, 1)  # AddUserMessage pushed; awaiting USER_ITEM_ADDED

        backend.push(ToolResultAdded(item=_tool_result_item()))  # mismatched — ignored
        await asyncio.sleep(0.02)  # let the bus worker dispatch it
        assert task.done() is False  # still awaiting the matching echo

        backend.push(UserItemAdded(item=_user_item()))  # matching — completes
        await asyncio.wait_for(task, 1)


async def test_abort_pushes_abortresponse_when_busy() -> None:
    async with _pair() as (controller, backend):
        task = asyncio.create_task(controller.generate())
        await _take(backend, 1)  # CreateResponse; busy
        controller.abort()
        pushed = await _take(backend, 1)
        assert isinstance(pushed[0], AbortResponse)
        # The server still ends the aborted generation with response.done.
        backend.push(ResponseDone(item=_assistant_item()))
        await asyncio.wait_for(task, 1)


async def test_abort_when_idle_raises() -> None:
    async with _pair() as (controller, _backend):
        with pytest.raises(RuntimeError, match="idle"):
            controller.abort()


# --------------------------------------------------------------------------- #
# DefaultModelController: session ops (compact / branch)
# --------------------------------------------------------------------------- #


async def test_compact_pushes_createcompaction_when_idle() -> None:
    async with _pair() as (controller, backend):
        confirm = _compaction_done()
        task = asyncio.create_task(controller.compact())
        pushed = await _take(backend, 1)
        assert isinstance(pushed[0], CreateCompaction)
        backend.push(confirm)
        result = await asyncio.wait_for(task, 1)
        assert result == confirm
        assert controller.is_idle()


async def test_compact_considered_busy() -> None:
    async with _pair() as (controller, backend):
        task = asyncio.create_task(controller.compact())
        await _take(backend, 1)  # CreateCompaction pushed
        assert controller.is_idle() is False  # busy
        backend.push(_compaction_done())
        await asyncio.wait_for(task, 1)
        assert controller.is_idle()


async def test_compact_forwards_params() -> None:
    async with _pair() as (controller, backend):
        task = asyncio.create_task(
            controller.compact(
                first_kept_item_id="k1",
                custom_instructions="be terse",
                summary="client summary",
            )
        )
        pushed = await _take(backend, 1)
        event = pushed[0]
        assert isinstance(event, CreateCompaction)
        assert event.first_kept_item_id == "k1"
        assert event.custom_instructions == "be terse"
        assert event.summary == "client summary"
        backend.push(_compaction_done())
        await asyncio.wait_for(task, 1)


async def test_compact_rejected_while_busy() -> None:
    async with _pair() as (controller, backend):
        task = asyncio.create_task(controller.generate())
        await _take(backend, 1)  # busy
        with pytest.raises(RuntimeError, match="busy"):
            await controller.compact()
        backend.push(ResponseDone(item=_assistant_item()))
        await asyncio.wait_for(task, 1)


async def test_compact_ignores_mismatched_echo_type() -> None:
    """A compact await must not complete on a ``BranchMoved`` confirm."""
    async with _pair() as (controller, backend):
        task = asyncio.create_task(controller.compact())
        await _take(backend, 1)  # CreateCompaction pushed; awaiting COMPACTION_DONE

        backend.push(_branch_moved())  # mismatched — ignored
        await asyncio.sleep(0.02)  # let the bus worker dispatch it
        assert task.done() is False  # still awaiting the matching confirm

        backend.push(_compaction_done())  # matching — completes
        await asyncio.wait_for(task, 1)


async def test_compact_returns_confirm_verbatim_with_error_message() -> None:
    """A refused compaction surfaces as a confirm with ``error_message`` (not raised)."""
    async with _pair() as (controller, backend):
        refused = CompactionDone(error_message="unsupported")
        task = asyncio.create_task(controller.compact())
        await _take(backend, 1)
        backend.push(refused)
        result = await asyncio.wait_for(task, 1)
        assert result is refused
        assert result.error_message == "unsupported"
        assert controller.is_idle()


async def test_compact_raises_when_torn_down_mid_flight() -> None:
    """A wedged backend + teardown must release ``compact``; it must not hang."""
    async with _pair() as (controller, _backend):
        task = asyncio.create_task(controller.compact())
        await _take(_backend, 1)  # CreateCompaction pushed; awaiting compaction.done
        assert controller.is_idle() is False
        # Exiting ends the backend cooperatively + closes the controller, which
        # releases the in-flight command (run loop exits).
    with pytest.raises(RuntimeError, match="run loop exited"):
        await task


async def test_branch_pushes_branchmove_when_idle() -> None:
    async with _pair() as (controller, backend):
        confirm = _branch_moved()
        task = asyncio.create_task(controller.branch("u1"))
        pushed = await _take(backend, 1)
        assert isinstance(pushed[0], BranchMove)
        backend.push(confirm)
        result = await asyncio.wait_for(task, 1)
        assert result == confirm
        assert controller.is_idle()


async def test_branch_considered_busy() -> None:
    async with _pair() as (controller, backend):
        task = asyncio.create_task(controller.branch("u1"))
        await _take(backend, 1)  # BranchMove pushed
        assert controller.is_idle() is False  # busy
        backend.push(_branch_moved())
        await asyncio.wait_for(task, 1)
        assert controller.is_idle()


async def test_branch_forwards_at_item_id_and_summary() -> None:
    async with _pair() as (controller, backend):
        task = asyncio.create_task(controller.branch("u1", summary="fork note"))
        pushed = await _take(backend, 1)
        event = pushed[0]
        assert isinstance(event, BranchMove)
        assert event.at_item_id == "u1"
        assert event.summary == "fork note"
        backend.push(_branch_moved())
        await asyncio.wait_for(task, 1)


async def test_branch_rejected_while_busy() -> None:
    async with _pair() as (controller, backend):
        task = asyncio.create_task(controller.generate())
        await _take(backend, 1)  # busy
        with pytest.raises(RuntimeError, match="busy"):
            await controller.branch("u1")
        backend.push(ResponseDone(item=_assistant_item()))
        await asyncio.wait_for(task, 1)


async def test_branch_ignores_mismatched_echo_type() -> None:
    """A branch await must not complete on a ``CompactionDone`` confirm."""
    async with _pair() as (controller, backend):
        task = asyncio.create_task(controller.branch("u1"))
        await _take(backend, 1)  # BranchMove pushed; awaiting BRANCH_MOVED

        backend.push(_compaction_done())  # mismatched — ignored
        await asyncio.sleep(0.02)  # let the bus worker dispatch it
        assert task.done() is False  # still awaiting the matching confirm

        backend.push(_branch_moved())  # matching — completes
        await asyncio.wait_for(task, 1)


async def test_branch_returns_confirm_verbatim_with_error_message() -> None:
    """A refused branch surfaces as a confirm with ``error_message`` (not raised).

    ``at_item_id`` is required even on refusal (echo of the request target).
    """
    async with _pair() as (controller, backend):
        refused = BranchMoved(at_item_id="u1", error_message="unsupported")
        task = asyncio.create_task(controller.branch("u1"))
        await _take(backend, 1)
        backend.push(refused)
        result = await asyncio.wait_for(task, 1)
        assert result is refused
        assert result.error_message == "unsupported"
        assert controller.is_idle()


async def test_branch_raises_when_torn_down_mid_flight() -> None:
    """A wedged backend + teardown must release ``branch``; it must not hang."""
    async with _pair() as (controller, _backend):
        task = asyncio.create_task(controller.branch("u1"))
        await _take(_backend, 1)  # BranchMove pushed; awaiting branch.moved
        assert controller.is_idle() is False
        # Exiting ends the backend cooperatively + closes the controller, which
        # releases the in-flight command (run loop exits).
    with pytest.raises(RuntimeError, match="run loop exited"):
        await task


# --------------------------------------------------------------------------- #
# DefaultModelController: bus fan-through (every server event type)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "event",
    [
        ResponseStarted(partial=_assistant_item()),
        ResponseUpdated(partial=_assistant_item()),
        ResponseDone(item=_assistant_item()),
        UserItemAdded(item=_user_item()),
        UserItemUpdated(item=_user_item()),
        ToolResultAdded(item=_tool_result_item()),
        CompactionDone(),
        BranchMoved(at_item_id="i1"),
    ],
)
async def test_controller_republishes_each_server_event(event: ServerContextEvent) -> None:
    async with _pair() as (controller, backend):
        done = asyncio.Event()

        async def handler(_event: ServerContextEvent) -> None:
            done.set()

        controller.bus.on(event.type, handler)
        backend.push(event)
        await asyncio.wait_for(done.wait(), 1)


# --------------------------------------------------------------------------- #
# DefaultModelController: no-strand teardown of in-flight commands
# --------------------------------------------------------------------------- #


async def test_generate_raises_when_torn_down_mid_flight() -> None:
    """A wedged backend + teardown must release ``generate``; it must not hang."""
    async with _pair() as (controller, _backend):
        task = asyncio.create_task(controller.generate())
        await _take(_backend, 1)  # CreateResponse pushed; generate parked awaiting done
        assert controller.is_idle() is False
        # Exiting ends the backend cooperatively + closes the controller, which
        # releases the in-flight command (run loop exits).
    with pytest.raises(RuntimeError, match="run loop exited"):
        await task


async def test_add_message_raises_when_torn_down_mid_flight() -> None:
    """A wedged backend + teardown must release ``add_message``; it must not hang."""
    async with _pair() as (controller, _backend):
        task = asyncio.create_task(controller.add_message(_input()))
        await _take(_backend, 1)  # AddUserMessage pushed; awaiting item-added echo
        assert controller.is_idle() is False
        # Exiting ends the backend cooperatively + closes the controller, which
        # releases the in-flight command (run loop exits).
    with pytest.raises(RuntimeError, match="run loop exited"):
        await task


# --------------------------------------------------------------------------- #
# DefaultModelController: lifecycle / teardown
# --------------------------------------------------------------------------- #


async def test_close_initiates_abort_and_guards_commands() -> None:
    async with _pair() as (controller, backend):
        assert backend.abort_signal.is_set() is False
        controller.close()
        assert controller.is_closing() is True
        assert backend.abort_signal.is_set() is True  # client.abort() fired

        with pytest.raises(RuntimeError, match="closing"):
            await controller.generate()
        with pytest.raises(RuntimeError, match="closing"):
            await controller.add_message(_input())
        with pytest.raises(RuntimeError, match="closing"):
            controller.abort()
        with pytest.raises(RuntimeError, match="closing"):
            await controller.compact()
        with pytest.raises(RuntimeError, match="closing"):
            await controller.branch("i1")


async def test_close_drains_final_items_via_conformant_backend() -> None:
    async with _pair() as (controller, backend):
        received: list[ServerContextEvent] = []
        done = asyncio.Event()

        async def handler(event: ServerContextEvent) -> None:
            received.append(event)
            if isinstance(event, ResponseDone):
                done.set()

        controller.bus.on(RESPONSE_DONE, handler)

        task = asyncio.create_task(controller.generate())
        await _take(backend, 1)  # CreateResponse

        async def conformant() -> None:
            await backend.wait_for_abort()
            backend.push(ResponseDone(item=_assistant_item()))  # final shutdown item
            backend.end()

        conf = asyncio.create_task(conformant())
        controller.close()
        await asyncio.wait_for(done.wait(), 1)  # final item reached the handler
        await asyncio.wait_for(task, 1)  # generate completed from the response.done
        await conf
        assert any(isinstance(e, ResponseDone) for e in received)


async def test_teardown_completes_cleanly_on_conformant_backend() -> None:
    async with _pair() as (controller, backend):
        task = asyncio.create_task(_conformant(backend))
    await task
    # Teardown completed cleanly on exit; the controller lifecycle task is done.
    assert controller._task is not None
    assert controller._task.done()


async def test_teardown_force_cancels_wedged_backend() -> None:
    # Wedged backend: nothing ever ends the inbound, so the drain hangs and
    # __aexit__ force-cancels it within the shutdown deadline (teardown always
    # exits cleanly; no exception propagates). ``_run``'s finally ends the
    # bus, so the nested bus reap does not add latency.
    pair: ConnectionPair[ClientContextEvent, ServerContextEvent] = create_connection()
    controller = DefaultModelController(pair.client)
    controller._shutdown_timeout = 0.1
    loop = asyncio.get_running_loop()
    start = loop.time()
    async with controller:
        pass  # nothing ends the inbound -> drain hangs -> __aexit__ forces
    assert loop.time() - start < 2.0  # force-cancelled within the deadline


async def test_async_context_manager_closes() -> None:
    pair: ConnectionPair[ClientContextEvent, ServerContextEvent] = create_connection()
    task = asyncio.create_task(_conformant(pair.backend))
    async with DefaultModelController(pair.client) as controller:
        assert controller.is_idle()
        controller.close()  # abort -> _conformant ends the inbound -> drain completes
    assert controller.is_closing()
    await task


async def test_close_is_idempotent() -> None:
    async with _pair() as (controller, backend):
        task = asyncio.create_task(_conformant(backend))
        controller.close()
        controller.close()  # idempotent
    await task
    assert controller.is_closing()


async def test_post_close_commands_rejected_even_when_idle() -> None:
    async with _pair() as (controller, backend):
        task = asyncio.create_task(_conformant(backend))
        controller.close()
        assert controller.is_idle()  # no generation was ever started
        with pytest.raises(RuntimeError, match="closing"):
            await controller.generate()
        with pytest.raises(RuntimeError, match="closing"):
            await controller.compact()
        with pytest.raises(RuntimeError, match="closing"):
            await controller.branch("i1")
        await task


async def test_wait_idle_unblocks_when_torn_down_while_busy() -> None:
    """Teardown mid-generation must not strand wait_idle.

    Ending the backend + closing the controller winds the drain down; the
    ``_run`` ``finally`` defensively sets idle so a caller parked on
    ``wait_idle()`` is released rather than hung, and the in-flight
    ``generate()`` task raises rather than hanging.
    """
    async with _pair() as (controller, backend):
        task = asyncio.create_task(controller.generate())
        await _take(backend, 1)
        assert controller.is_idle() is False  # busy
        # Exiting ends the backend + closes the controller, winding the drain
        # down and releasing the in-flight generate (run loop exits).
    with pytest.raises(RuntimeError, match="run loop exited"):
        await task
    # wait_idle() must return (defensive set_idle in _run's finally):
    await asyncio.wait_for(controller.wait_idle(), 1)
    assert controller.is_idle() is True


async def test_teardown_leaves_controller_task_done() -> None:
    async with _pair() as (controller, backend):
        task = asyncio.create_task(_conformant(backend))
    await task
    # The controller and its bus drain tasks both completed on teardown.
    assert controller._task is not None
    assert controller._task.done()
