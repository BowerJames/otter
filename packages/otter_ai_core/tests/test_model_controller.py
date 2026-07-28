"""ModelController / State: async commands, fan-out, lifecycle, teardown.

Tests exercise the concerns of the ``model_controller`` package:

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

Descriptor-keyed bus behaviour (fan-out, per-descriptor dispatch,
idempotent unsubscribe, no-subscriber no-op, per-handler isolation,
end/aclose semantics) is covered in ``tests/test_bus.py``; the controller's
bus is the same descriptor-keyed :class:`~otter_ai_core.bus.Bus`, with its
per-variant :class:`~otter_ai_core.bus.BusEvent` descriptors defined in
:mod:`otter_ai_core.interfaces.model_controller`.
"""

from __future__ import annotations

import asyncio
import contextlib

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
    create_connection,
)
from otter_ai_core.connection import ConnectionBackend, ConnectionPair
from otter_ai_core.context import Role
from otter_ai_core.interfaces import ModelController
from otter_ai_core.interfaces.model_controller import SERVER_EVENT_BY_TYPE
from otter_ai_core.model_connection import (
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
from otter_ai_core.model_controller import RESPONSE_DONE, DefaultModelController, State


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


def _pair() -> tuple[
    DefaultModelController,
    ConnectionBackend[ClientContextEvent, ServerContextEvent],
]:
    """A controller wired to a fresh connection pair; return (controller, backend)."""
    pair: ConnectionPair[ClientContextEvent, ServerContextEvent] = create_connection()
    return DefaultModelController(pair.client), pair.backend


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
    await backend.abort_signal.wait()
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
    controller, _backend = _pair()
    assert controller.is_idle() is True
    assert controller.is_closing() is False
    await controller.aclose(timeout=0.2)


async def test_generate_flips_busy_then_idle_on_done() -> None:
    controller, backend = _pair()
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
    await controller.aclose(timeout=0.2)


async def test_controller_bus_narrows_response_done() -> None:
    """A handler on the controller's bus narrows ``ResponseDone`` to ``.item``."""
    controller, backend = _pair()
    seen: list[str] = []
    done = asyncio.Event()

    async def handler(event: ServerContextEvent) -> None:
        match event.type:
            case ServerContextEventType.RESPONSE_DONE:
                seen.append(event.item.id)  # strict-mypy narrowing of the union
                done.set()
            case _:
                pass

    controller.bus.subscribe(RESPONSE_DONE, handler)
    backend.push(ResponseDone(item=_assistant_item()))
    await asyncio.wait_for(done.wait(), 1)
    assert seen == ["a1"]
    await controller.aclose(timeout=0.2)


# --------------------------------------------------------------------------- #
# DefaultModelController: command guards
# --------------------------------------------------------------------------- #


async def test_generate_while_busy_raises() -> None:
    controller, backend = _pair()
    task = asyncio.create_task(controller.generate())
    await _take(backend, 1)  # CreateResponse pushed; controller busy + parked
    with pytest.raises(RuntimeError, match="busy"):
        await controller.generate()
    # Release the in-flight generation so it doesn't leak.
    backend.push(ResponseDone(item=_assistant_item()))
    await asyncio.wait_for(task, 1)
    await controller.aclose(timeout=0.2)


async def test_add_message_pushes_when_idle() -> None:
    controller, backend = _pair()
    task = asyncio.create_task(controller.add_message(_input()))
    pushed = await _take(backend, 1)
    assert isinstance(pushed[0], AddUserMessage)
    backend.push(UserItemAdded(item=_user_item()))
    result = await asyncio.wait_for(task, 1)
    assert result == _user_item()
    assert controller.is_idle()
    await controller.aclose(timeout=0.2)


async def test_add_message_rejected_while_busy() -> None:
    controller, backend = _pair()
    task = asyncio.create_task(controller.generate())
    await _take(backend, 1)  # busy
    with pytest.raises(RuntimeError, match="busy"):
        await controller.add_message(_input())
    backend.push(ResponseDone(item=_assistant_item()))
    await asyncio.wait_for(task, 1)
    await controller.aclose(timeout=0.2)


async def test_add_message_with_tool_result_awaits_tool_result_echo() -> None:
    controller, backend = _pair()
    task = asyncio.create_task(
        controller.add_message(AddToolResultMessage(message=_tool_result_message()))
    )
    pushed = await _take(backend, 1)
    assert pushed[0].type == ClientContextEventType.ADD_TOOL_RESULT_MESSAGE
    backend.push(ToolResultAdded(item=_tool_result_item()))
    result = await asyncio.wait_for(task, 1)
    assert result == _tool_result_item()
    assert controller.is_idle()
    await controller.aclose(timeout=0.2)


async def test_add_message_ignores_mismatched_echo_type() -> None:
    """An ``AddUserMessage`` await must not complete on a ``ToolResultAdded`` echo."""
    controller, backend = _pair()
    task = asyncio.create_task(controller.add_message(_input()))
    await _take(backend, 1)  # AddUserMessage pushed; awaiting USER_ITEM_ADDED

    backend.push(ToolResultAdded(item=_tool_result_item()))  # mismatched — ignored
    await asyncio.sleep(0.02)  # let the bus worker dispatch it
    assert task.done() is False  # still awaiting the matching echo

    backend.push(UserItemAdded(item=_user_item()))  # matching — completes
    await asyncio.wait_for(task, 1)
    await controller.aclose(timeout=0.2)


async def test_abort_pushes_abortresponse_when_busy() -> None:
    controller, backend = _pair()
    task = asyncio.create_task(controller.generate())
    await _take(backend, 1)  # CreateResponse; busy
    controller.abort()
    pushed = await _take(backend, 1)
    assert isinstance(pushed[0], AbortResponse)
    # The server still ends the aborted generation with response.done.
    backend.push(ResponseDone(item=_assistant_item()))
    await asyncio.wait_for(task, 1)
    await controller.aclose(timeout=0.2)


async def test_abort_when_idle_raises() -> None:
    controller, _backend = _pair()
    with pytest.raises(RuntimeError, match="idle"):
        controller.abort()
    await controller.aclose(timeout=0.2)


# --------------------------------------------------------------------------- #
# DefaultModelController: session ops (compact / branch)
# --------------------------------------------------------------------------- #


async def test_compact_pushes_createcompaction_when_idle() -> None:
    controller, backend = _pair()
    confirm = _compaction_done()
    task = asyncio.create_task(controller.compact())
    pushed = await _take(backend, 1)
    assert isinstance(pushed[0], CreateCompaction)
    backend.push(confirm)
    result = await asyncio.wait_for(task, 1)
    assert result == confirm
    assert controller.is_idle()
    await controller.aclose(timeout=0.2)


async def test_compact_considered_busy() -> None:
    controller, backend = _pair()
    task = asyncio.create_task(controller.compact())
    await _take(backend, 1)  # CreateCompaction pushed
    assert controller.is_idle() is False  # busy
    backend.push(_compaction_done())
    await asyncio.wait_for(task, 1)
    assert controller.is_idle()
    await controller.aclose(timeout=0.2)


async def test_compact_forwards_params() -> None:
    controller, backend = _pair()
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
    await controller.aclose(timeout=0.2)


async def test_compact_rejected_while_busy() -> None:
    controller, backend = _pair()
    task = asyncio.create_task(controller.generate())
    await _take(backend, 1)  # busy
    with pytest.raises(RuntimeError, match="busy"):
        await controller.compact()
    backend.push(ResponseDone(item=_assistant_item()))
    await asyncio.wait_for(task, 1)
    await controller.aclose(timeout=0.2)


async def test_compact_ignores_mismatched_echo_type() -> None:
    """A compact await must not complete on a ``BranchMoved`` confirm."""
    controller, backend = _pair()
    task = asyncio.create_task(controller.compact())
    await _take(backend, 1)  # CreateCompaction pushed; awaiting COMPACTION_DONE

    backend.push(_branch_moved())  # mismatched — ignored
    await asyncio.sleep(0.02)  # let the bus worker dispatch it
    assert task.done() is False  # still awaiting the matching confirm

    backend.push(_compaction_done())  # matching — completes
    await asyncio.wait_for(task, 1)
    await controller.aclose(timeout=0.2)


async def test_compact_returns_confirm_verbatim_with_error_message() -> None:
    """A refused compaction surfaces as a confirm with ``error_message`` (not raised)."""
    controller, backend = _pair()
    refused = CompactionDone(error_message="unsupported")
    task = asyncio.create_task(controller.compact())
    await _take(backend, 1)
    backend.push(refused)
    result = await asyncio.wait_for(task, 1)
    assert result is refused
    assert result.error_message == "unsupported"
    assert controller.is_idle()
    await controller.aclose(timeout=0.2)


async def test_compact_raises_when_torn_down_mid_flight() -> None:
    """A wedged backend + teardown must release ``compact``; it must not hang."""
    controller, _backend = _pair()
    task = asyncio.create_task(controller.compact())
    await _take(_backend, 1)  # CreateCompaction pushed; awaiting compaction.done
    assert controller.is_idle() is False
    await controller.aclose(timeout=0.2)  # wedged -> run loop cancelled
    with pytest.raises(RuntimeError, match="run loop exited"):
        await task


async def test_branch_pushes_branchmove_when_idle() -> None:
    controller, backend = _pair()
    confirm = _branch_moved()
    task = asyncio.create_task(controller.branch("u1"))
    pushed = await _take(backend, 1)
    assert isinstance(pushed[0], BranchMove)
    backend.push(confirm)
    result = await asyncio.wait_for(task, 1)
    assert result == confirm
    assert controller.is_idle()
    await controller.aclose(timeout=0.2)


async def test_branch_considered_busy() -> None:
    controller, backend = _pair()
    task = asyncio.create_task(controller.branch("u1"))
    await _take(backend, 1)  # BranchMove pushed
    assert controller.is_idle() is False  # busy
    backend.push(_branch_moved())
    await asyncio.wait_for(task, 1)
    assert controller.is_idle()
    await controller.aclose(timeout=0.2)


async def test_branch_forwards_at_item_id_and_summary() -> None:
    controller, backend = _pair()
    task = asyncio.create_task(controller.branch("u1", summary="fork note"))
    pushed = await _take(backend, 1)
    event = pushed[0]
    assert isinstance(event, BranchMove)
    assert event.at_item_id == "u1"
    assert event.summary == "fork note"
    backend.push(_branch_moved())
    await asyncio.wait_for(task, 1)
    await controller.aclose(timeout=0.2)


async def test_branch_rejected_while_busy() -> None:
    controller, backend = _pair()
    task = asyncio.create_task(controller.generate())
    await _take(backend, 1)  # busy
    with pytest.raises(RuntimeError, match="busy"):
        await controller.branch("u1")
    backend.push(ResponseDone(item=_assistant_item()))
    await asyncio.wait_for(task, 1)
    await controller.aclose(timeout=0.2)


async def test_branch_ignores_mismatched_echo_type() -> None:
    """A branch await must not complete on a ``CompactionDone`` confirm."""
    controller, backend = _pair()
    task = asyncio.create_task(controller.branch("u1"))
    await _take(backend, 1)  # BranchMove pushed; awaiting BRANCH_MOVED

    backend.push(_compaction_done())  # mismatched — ignored
    await asyncio.sleep(0.02)  # let the bus worker dispatch it
    assert task.done() is False  # still awaiting the matching confirm

    backend.push(_branch_moved())  # matching — completes
    await asyncio.wait_for(task, 1)
    await controller.aclose(timeout=0.2)


async def test_branch_returns_confirm_verbatim_with_error_message() -> None:
    """A refused branch surfaces as a confirm with ``error_message`` (not raised).

    ``at_item_id`` is required even on refusal (echo of the request target).
    """
    controller, backend = _pair()
    refused = BranchMoved(at_item_id="u1", error_message="unsupported")
    task = asyncio.create_task(controller.branch("u1"))
    await _take(backend, 1)
    backend.push(refused)
    result = await asyncio.wait_for(task, 1)
    assert result is refused
    assert result.error_message == "unsupported"
    assert controller.is_idle()
    await controller.aclose(timeout=0.2)


async def test_branch_raises_when_torn_down_mid_flight() -> None:
    """A wedged backend + teardown must release ``branch``; it must not hang."""
    controller, _backend = _pair()
    task = asyncio.create_task(controller.branch("u1"))
    await _take(_backend, 1)  # BranchMove pushed; awaiting branch.moved
    assert controller.is_idle() is False
    await controller.aclose(timeout=0.2)  # wedged -> run loop cancelled
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
    controller, backend = _pair()
    done = asyncio.Event()

    async def handler(_event: ServerContextEvent) -> None:
        done.set()

    controller.bus.subscribe(SERVER_EVENT_BY_TYPE[event.type], handler)
    backend.push(event)
    await asyncio.wait_for(done.wait(), 1)
    await controller.aclose(timeout=0.2)


# --------------------------------------------------------------------------- #
# DefaultModelController: no-strand teardown of in-flight commands
# --------------------------------------------------------------------------- #


async def test_generate_raises_when_torn_down_mid_flight() -> None:
    """A wedged backend + teardown must release ``generate``; it must not hang."""
    controller, _backend = _pair()
    task = asyncio.create_task(controller.generate())
    await _take(_backend, 1)  # CreateResponse pushed; generate parked awaiting done
    assert controller.is_idle() is False
    await controller.aclose(timeout=0.2)  # wedged -> run loop cancelled
    with pytest.raises(RuntimeError, match="run loop exited"):
        await task


async def test_add_message_raises_when_torn_down_mid_flight() -> None:
    """A wedged backend + teardown must release ``add_message``; it must not hang."""
    controller, _backend = _pair()
    task = asyncio.create_task(controller.add_message(_input()))
    await _take(_backend, 1)  # AddUserMessage pushed; awaiting item-added echo
    assert controller.is_idle() is False
    await controller.aclose(timeout=0.2)
    with pytest.raises(RuntimeError, match="run loop exited"):
        await task


# --------------------------------------------------------------------------- #
# DefaultModelController: lifecycle / teardown
# --------------------------------------------------------------------------- #


async def test_close_initiates_abort_and_guards_commands() -> None:
    controller, backend = _pair()
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

    await controller.aclose(timeout=0.2)


async def test_close_drains_final_items_via_conformant_backend() -> None:
    controller, backend = _pair()
    received: list[ServerContextEvent] = []
    done = asyncio.Event()

    async def handler(event: ServerContextEvent) -> None:
        received.append(event)
        if isinstance(event, ResponseDone):
            done.set()

    controller.bus.subscribe(RESPONSE_DONE, handler)

    task = asyncio.create_task(controller.generate())
    await _take(backend, 1)  # CreateResponse

    async def conformant() -> None:
        await backend.abort_signal.wait()
        backend.push(ResponseDone(item=_assistant_item()))  # final shutdown item
        backend.end()

    conf = asyncio.create_task(conformant())
    controller.close()
    await asyncio.wait_for(done.wait(), 1)  # final item reached the handler
    await asyncio.wait_for(task, 1)  # generate completed from the response.done
    await conf
    assert any(isinstance(e, ResponseDone) for e in received)
    await controller.aclose(timeout=0.2)


async def test_aclose_completes_cleanly_on_conformant_backend() -> None:
    controller, backend = _pair()
    task = asyncio.create_task(_conformant(backend))
    await controller.aclose(timeout=0.2)
    await task
    assert controller._task.done()
    assert controller.bus._task.done()


async def test_aclose_cancels_wedged_backend() -> None:
    controller, _backend = _pair()
    # Wedged backend: nothing ends the inbound, so the drain would hang forever
    # without the deadline-gated cancel.
    loop = asyncio.get_running_loop()
    start = loop.time()
    await controller.aclose(timeout=0.1)
    assert loop.time() - start < 1.0  # did not hang; cancelled after ~0.1s
    assert controller._task.done()


async def test_async_context_manager_closes() -> None:
    pair: ConnectionPair[ClientContextEvent, ServerContextEvent] = create_connection()
    task = asyncio.create_task(_conformant(pair.backend))
    async with DefaultModelController(pair.client) as controller:
        assert controller.is_idle()
    assert controller.is_closing()
    assert controller._task.done()
    await task


async def test_close_and_aclose_are_idempotent() -> None:
    controller, backend = _pair()
    task = asyncio.create_task(_conformant(backend))
    controller.close()
    controller.close()  # idempotent
    await controller.aclose(timeout=0.2)
    await controller.aclose(timeout=0.2)  # idempotent
    assert controller._task.done()
    await task


async def test_post_close_commands_rejected_even_when_idle() -> None:
    controller, backend = _pair()
    task = asyncio.create_task(_conformant(backend))
    controller.close()
    assert controller.is_idle()  # no generation was ever started
    with pytest.raises(RuntimeError, match="closing"):
        await controller.generate()
    with pytest.raises(RuntimeError, match="closing"):
        await controller.compact()
    with pytest.raises(RuntimeError, match="closing"):
        await controller.branch("i1")
    await controller.aclose(timeout=0.2)
    await task


async def test_wait_idle_unblocks_when_torn_down_while_busy() -> None:
    """A teardown that cancels ``_run`` mid-generation must not strand wait_idle.

    With a wedged backend (no ``response.done`` ever arrives), ``aclose``
    force-cancels the drain loop. The ``_run`` ``finally`` defensively sets
    idle so a caller parked on ``wait_idle()`` is released rather than hung,
    and the in-flight ``generate()`` task raises rather than hanging.
    """
    controller, backend = _pair()
    task = asyncio.create_task(controller.generate())
    await _take(backend, 1)
    assert controller.is_idle() is False  # busy
    await controller.aclose(timeout=0.2)  # wedged backend -> cancel mid-flight
    with pytest.raises(RuntimeError, match="run loop exited"):
        await task
    # wait_idle() must return (defensive set_idle in _run's finally):
    await asyncio.wait_for(controller.wait_idle(), 1)
    assert controller.is_idle() is True


async def test_aclose_reaps_bus_even_when_cancelled_mid_flight() -> None:
    """If aclose() itself is cancelled, its finally still reaps the bus worker."""
    controller, _backend = _pair()
    # Wedged backend: the controller drain never completes on its own, so
    # aclose parks inside await_or_cancel(controller._task).
    close_task = asyncio.create_task(controller.aclose(timeout=10))
    await asyncio.sleep(0.05)  # let aclose park
    close_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await close_task
    # The bus worker was still reaped by aclose's finally — no owned task left.
    assert controller.bus._task.done()
