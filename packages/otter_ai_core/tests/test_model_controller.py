"""ModelController / ModelBus / State: commands, fan-out, lifecycle, teardown.

Tests exercise the three concerns of the ``model_controller`` package:

* :class:`State` — the idle/busy latch (starts idle) and the closing flag;
* :class:`ModelBus` — typed pub/sub with per-handler error isolation and
  deadline-bounded teardown;
* :class:`ModelController` — conversation commands, idle tracking, bus
  fan-through, and the cooperative-then-deterministic teardown model.

The controller tests stand up a real ``create_connection()`` pair: the
controller drives ``pair.client`` and the test pushes server events on
``pair.backend`` (and drains the client→server events the controller pushes).
A small ``_conformant_backend`` task honours the abort contract — on
``abort_signal`` it ends the inbound so the controller's drain completes.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

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
from otter_ai_core.model_connection import (
    AbortResponse,
    AddUserMessage,
    ClientContextEvent,
    ClientContextEventType,
    ResponseDone,
    ResponseStarted,
    ResponseUpdated,
    ServerContextEvent,
    ServerContextEventType,
    ToolResultAdded,
    UserItemAdded,
    UserItemUpdated,
)
from otter_ai_core.model_controller import ModelBus, ModelController, State

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
    return AssistantContextItem.from_message(_assistant_message(stop_reason), id="a1")


def _user_message() -> UserMessage:
    return UserMessage(role=Role.User, content="hi", timestamp=0)


def _user_item() -> UserContextItem:
    return UserContextItem.from_message(_user_message(), id="u1")


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
    return ToolResultContextItem.from_message(_tool_result_message(), id="tr1")


def _input() -> AddUserMessage:
    return AddUserMessage(message=_user_message())


def _pair() -> tuple[
    ModelController,
    ConnectionBackend[ClientContextEvent, ServerContextEvent],
]:
    """A controller wired to a fresh connection pair; return (controller, backend)."""
    pair: ConnectionPair[ClientContextEvent, ServerContextEvent] = create_connection()
    return ModelController(pair.client), pair.backend


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
# ModelBus
# --------------------------------------------------------------------------- #


async def test_bus_matching_handler_fires() -> None:
    bus = ModelBus()
    seen: list[ServerContextEvent] = []
    done = asyncio.Event()

    async def handler(event: ServerContextEvent) -> None:
        seen.append(event)
        done.set()

    bus.subscribe(ServerContextEventType.RESPONSE_DONE, handler)
    bus.publish(ResponseDone(item=_assistant_item()))
    await asyncio.wait_for(done.wait(), 1)
    assert len(seen) == 1
    await bus.aclose()


async def test_model_bus_handler_preserves_server_event_narrowing() -> None:
    bus = ModelBus()
    seen: list[str] = []
    done = asyncio.Event()

    async def handler(event: ServerContextEvent) -> None:
        match event.type:
            case ServerContextEventType.RESPONSE_DONE:
                # Strict mypy must narrow the full union before allowing .item.
                seen.append(event.item.id)
                done.set()
            case _:
                pass

    bus.subscribe(ServerContextEventType.RESPONSE_DONE, handler)
    bus.publish(ResponseDone(item=_assistant_item()))
    await asyncio.wait_for(done.wait(), 1)
    assert seen == ["a1"]
    await bus.aclose()


async def test_bus_non_matching_type_not_dispatched() -> None:
    bus = ModelBus()
    wrong = asyncio.Event()
    marker = asyncio.Event()

    async def on_user_item(event: ServerContextEvent) -> None:
        wrong.set()

    async def on_done(event: ServerContextEvent) -> None:
        marker.set()

    bus.subscribe(ServerContextEventType.USER_ITEM_ADDED, on_user_item)
    bus.subscribe(ServerContextEventType.RESPONSE_DONE, on_done)
    bus.publish(ResponseDone(item=_assistant_item()))
    await asyncio.wait_for(marker.wait(), 1)  # event processed
    assert wrong.is_set() is False
    await bus.aclose()


async def test_bus_multiple_handlers_in_subscription_order() -> None:
    bus = ModelBus()
    order: list[int] = []
    done = asyncio.Event()

    async def first(event: ServerContextEvent) -> None:
        order.append(1)

    async def second(event: ServerContextEvent) -> None:
        order.append(2)
        done.set()

    bus.subscribe(ServerContextEventType.RESPONSE_DONE, first)
    bus.subscribe(ServerContextEventType.RESPONSE_DONE, second)
    bus.publish(ResponseDone(item=_assistant_item()))
    await asyncio.wait_for(done.wait(), 1)
    assert order == [1, 2]
    await bus.aclose()


async def test_bus_unsubscribe_is_idempotent() -> None:
    bus = ModelBus()
    seen: list[ServerContextEvent] = []
    marker = asyncio.Event()

    async def handler(event: ServerContextEvent) -> None:
        seen.append(event)

    async def marker_handler(event: ServerContextEvent) -> None:
        marker.set()

    unsubscribe = bus.subscribe(ServerContextEventType.RESPONSE_DONE, handler)
    bus.subscribe(ServerContextEventType.RESPONSE_DONE, marker_handler)
    unsubscribe()
    unsubscribe()  # idempotent — no error
    bus.publish(ResponseDone(item=_assistant_item()))
    await asyncio.wait_for(marker.wait(), 1)  # worker processed the event
    assert seen == []
    await bus.aclose()


async def test_bus_isolates_handler_errors(caplog: pytest.LogCaptureFixture) -> None:
    """A raising handler is logged and skipped; siblings and later events still run."""
    bus = ModelBus()
    sibling = asyncio.Event()
    next_event = asyncio.Event()

    async def bad(event: ServerContextEvent) -> None:
        raise ValueError("boom")

    async def good(event: ServerContextEvent) -> None:
        sibling.set()

    async def on_user_item(event: ServerContextEvent) -> None:
        next_event.set()

    bus.subscribe(ServerContextEventType.RESPONSE_DONE, bad)
    bus.subscribe(ServerContextEventType.RESPONSE_DONE, good)
    bus.subscribe(ServerContextEventType.USER_ITEM_ADDED, on_user_item)

    with caplog.at_level(logging.ERROR, logger="otter_ai_core.bus"):
        bus.publish(ResponseDone(item=_assistant_item()))
        await asyncio.wait_for(sibling.wait(), 1)  # sibling ran despite bad raising
        bus.publish(UserItemAdded(item=_user_item()))
        await asyncio.wait_for(next_event.wait(), 1)  # bus survived to next event

    assert sibling.is_set()
    assert next_event.is_set()
    assert any("handler raised" in r.getMessage() for r in caplog.records)
    assert any(r.exc_info is not None for r in caplog.records)
    await bus.aclose()


async def test_bus_end_drains_queued_events() -> None:
    bus = ModelBus()
    seen: list[ServerContextEvent] = []
    done = asyncio.Event()

    async def handler(event: ServerContextEvent) -> None:
        seen.append(event)
        done.set()

    bus.subscribe(ServerContextEventType.RESPONSE_DONE, handler)
    bus.publish(ResponseDone(item=_assistant_item()))
    bus.end()
    await asyncio.wait_for(done.wait(), 1)  # handler still fired after end()
    assert len(seen) == 1
    await bus.aclose()


async def test_bus_publish_after_end_is_noop() -> None:
    bus = ModelBus()
    count = 0
    done = asyncio.Event()

    async def handler(event: ServerContextEvent) -> None:
        nonlocal count
        count += 1
        done.set()

    bus.subscribe(ServerContextEventType.RESPONSE_DONE, handler)
    bus.publish(ResponseDone(item=_assistant_item()))
    await asyncio.wait_for(done.wait(), 1)
    assert count == 1
    bus.end()
    bus.publish(ResponseDone(item=_assistant_item()))  # dropped
    await bus.aclose()
    assert count == 1


async def test_bus_aclose_drains_and_completes() -> None:
    bus = ModelBus()
    done = asyncio.Event()

    async def handler(event: ServerContextEvent) -> None:
        done.set()

    bus.subscribe(ServerContextEventType.RESPONSE_DONE, handler)
    bus.publish(ResponseDone(item=_assistant_item()))
    await asyncio.wait_for(done.wait(), 1)
    await asyncio.wait_for(bus.aclose(timeout=1), 1)
    assert bus._task.done()


async def test_bus_aclose_cancels_wedged_handler() -> None:
    bus = ModelBus()
    release = asyncio.Event()

    async def handler(event: ServerContextEvent) -> None:
        await release.wait()  # hangs until released

    bus.subscribe(ServerContextEventType.RESPONSE_DONE, handler)
    bus.publish(ResponseDone(item=_assistant_item()))
    await asyncio.sleep(0.02)  # let the worker park in the handler
    await asyncio.wait_for(bus.aclose(timeout=0.1), 1)  # force-cancelled
    assert bus._task.done()


# --------------------------------------------------------------------------- #
# ModelController: construction & idle tracking
# --------------------------------------------------------------------------- #


async def test_controller_starts_idle() -> None:
    controller, _backend = _pair()
    assert controller.is_idle() is True
    assert controller.is_closing() is False
    await controller.aclose(timeout=0.2)


async def test_generate_flips_busy_then_idle_on_done() -> None:
    controller, backend = _pair()
    assert controller.is_idle()

    controller.generate([_input()])
    assert controller.is_idle() is False  # busy

    pushed = await _take(backend, 2)
    assert pushed[0].type == ClientContextEventType.ADD_USER_MESSAGE
    assert pushed[1].type == ClientContextEventType.CREATE_RESPONSE

    backend.push(ResponseStarted(partial=_assistant_item()))
    backend.push(ResponseDone(item=_assistant_item()))
    await asyncio.wait_for(controller.wait_idle(), 1)  # done -> idle

    await controller.aclose(timeout=0.2)


async def test_response_done_sets_idle_before_publish() -> None:
    """``_run`` sets idle before re-publishing, so handlers observe idle == True."""
    controller, backend = _pair()
    controller.generate([_input()])
    await _take(backend, 2)
    seen_idle: list[bool] = []
    done = asyncio.Event()

    async def handler(event: ServerContextEvent) -> None:
        seen_idle.append(controller.is_idle())
        done.set()

    controller.bus.subscribe(ServerContextEventType.RESPONSE_DONE, handler)
    backend.push(ResponseDone(item=_assistant_item()))
    await asyncio.wait_for(done.wait(), 1)
    assert seen_idle == [True]
    await controller.aclose(timeout=0.2)


# --------------------------------------------------------------------------- #
# ModelController: command guards
# --------------------------------------------------------------------------- #


async def test_generate_while_busy_raises() -> None:
    controller, _backend = _pair()
    controller.generate([_input()])
    with pytest.raises(RuntimeError, match="in progress"):
        controller.generate([_input()])
    await controller.aclose(timeout=0.2)


async def test_add_messages_pushes_when_idle() -> None:
    controller, backend = _pair()
    controller.add_messages([_input()])
    pushed = await _take(backend, 1)
    assert isinstance(pushed[0], AddUserMessage)
    await controller.aclose(timeout=0.2)


async def test_add_messages_rejected_while_busy() -> None:
    controller, _backend = _pair()
    controller.generate([_input()])
    with pytest.raises(RuntimeError, match="in progress"):
        controller.add_messages([_input()])
    await controller.aclose(timeout=0.2)


async def test_abort_pushes_abortresponse_when_busy() -> None:
    controller, backend = _pair()
    controller.generate([_input()])
    await _take(backend, 2)  # drain AddUserMessage + CreateResponse
    controller.abort()
    pushed = await _take(backend, 1)
    assert isinstance(pushed[0], AbortResponse)
    await controller.aclose(timeout=0.2)


async def test_abort_when_idle_raises() -> None:
    controller, _backend = _pair()
    with pytest.raises(RuntimeError, match="idle"):
        controller.abort()
    await controller.aclose(timeout=0.2)


# --------------------------------------------------------------------------- #
# ModelController: bus fan-through (every server event type)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "event_type, event",
    [
        (
            ServerContextEventType.RESPONSE_STARTED,
            ResponseStarted(partial=_assistant_item()),
        ),
        (
            ServerContextEventType.RESPONSE_UPDATED,
            ResponseUpdated(partial=_assistant_item()),
        ),
        (ServerContextEventType.RESPONSE_DONE, ResponseDone(item=_assistant_item())),
        (
            ServerContextEventType.USER_ITEM_ADDED,
            UserItemAdded(item=_user_item()),
        ),
        (
            ServerContextEventType.USER_ITEM_UPDATED,
            UserItemUpdated(item=_user_item()),
        ),
        (
            ServerContextEventType.TOOL_RESULT_ADDED,
            ToolResultAdded(item=_tool_result_item()),
        ),
    ],
)
async def test_controller_republishes_each_server_event(
    event_type: ServerContextEventType, event: ServerContextEvent
) -> None:
    controller, backend = _pair()
    done = asyncio.Event()

    async def handler(_event: ServerContextEvent) -> None:
        done.set()

    controller.bus.subscribe(event_type, handler)
    backend.push(event)
    await asyncio.wait_for(done.wait(), 1)
    await controller.aclose(timeout=0.2)


# --------------------------------------------------------------------------- #
# ModelController: lifecycle / teardown
# --------------------------------------------------------------------------- #


async def test_close_initiates_abort_and_guards_commands() -> None:
    controller, backend = _pair()
    assert backend.abort_signal.is_set() is False
    controller.close()
    assert controller.is_closing() is True
    assert backend.abort_signal.is_set() is True  # client.abort() fired

    with pytest.raises(RuntimeError, match="closing"):
        controller.generate([_input()])
    with pytest.raises(RuntimeError, match="closing"):
        controller.add_messages([_input()])
    with pytest.raises(RuntimeError, match="closing"):
        controller.abort()

    await controller.aclose(timeout=0.2)


async def test_close_drains_final_items_via_conformant_backend() -> None:
    controller, backend = _pair()
    received: list[ServerContextEvent] = []
    done = asyncio.Event()

    async def handler(event: ServerContextEvent) -> None:
        received.append(event)
        if isinstance(event, ResponseDone):
            done.set()

    controller.bus.subscribe(ServerContextEventType.RESPONSE_DONE, handler)

    controller.generate([_input()])
    await _take(backend, 2)

    async def conformant() -> None:
        await backend.abort_signal.wait()
        backend.push(ResponseDone(item=_assistant_item()))  # final shutdown item
        backend.end()

    task = asyncio.create_task(conformant())
    controller.close()
    await asyncio.wait_for(done.wait(), 1)  # final item reached the handler
    await task
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
    async with ModelController(pair.client) as controller:
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
        controller.generate([_input()])
    await controller.aclose(timeout=0.2)
    await task


async def test_wait_idle_unblocks_when_torn_down_while_busy() -> None:
    """A teardown that cancels ``_run`` mid-generation must not strand wait_idle.

    With a wedged backend (no ``response.done`` ever arrives), ``aclose``
    force-cancels the drain loop. The ``_run`` ``finally`` defensively sets
    idle so a caller parked on ``wait_idle()`` is released rather than hung.
    """
    controller, backend = _pair()
    controller.generate([_input()])
    await _take(backend, 2)
    assert controller.is_idle() is False  # busy
    await controller.aclose(timeout=0.2)  # wedged backend -> cancel mid-flight
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
