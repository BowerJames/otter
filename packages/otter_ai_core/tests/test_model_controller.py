"""ModelController / State: async commands, fan-out, lifecycle, teardown.

Tests exercise the concerns of the ``default_model_controller`` package:

* :class:`State` — the idle/busy latch (starts idle) and the closing flag;
* :class:`DefaultModelController` — the async, confirmation-awaiting commands
  (:meth:`~DefaultModelController.add_message` /
  :meth:`~DefaultModelController.add_tool_result` /
  :meth:`~DefaultModelController.generate`),
  the busy/closing guards, idle tracking, bus fan-through, the no-strand
  teardown guarantee for in-flight commands, and the cooperative-then-
  deterministic teardown model.

The controller drives a :class:`tests._fake_model_connection._RecordingModelConnection`
— a method-contract double that records the commands the controller issues
(``add_user_message`` / ``add_tool_result`` / ``generate`` / ``abort``) and lets
the test inject server events via ``feed()`` and terminate the stream via
``end()`` (``auto_end=True`` ends the stream on ``end()``; ``auto_end=False``
wedges the drain so teardown must force-cancel).

Name-keyed bus behaviour (fan-out, per-name dispatch,
idempotent unsubscribe, no-subscriber no-op, per-handler isolation,
end/aclose semantics) is covered in ``tests/test_bus.py``; the controller's
bus is the same :class:`~otter_ai_core.runtime.bus.Bus`, with its event names keyed on
:class:`~otter_ai_core.data_models.ServerContextEventType`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest

from otter_ai_core import (
    AssistantContextItem,
    AssistantMessage,
    BinaryStateMachine,
    StopReason,
    TextContent,
    ToolResultContextItem,
    ToolResultMessage,
    Usage,
    UsageCost,
    UserContextItem,
    UserMessage,
)
from otter_ai_core.data_models.context import Role
from otter_ai_core.data_models.events import (
    BranchMoved,
    CompactionDone,
    ResponseDone,
    ResponseStarted,
    ResponseUpdated,
    ServerContextEvent,
    ServerContextEventType,
    ToolResultAdded,
    UserItemAdded,
    UserItemUpdated,
)
from otter_ai_core.interfaces.roles import ModelConnection, ModelController
from otter_ai_core.runtime.default_model_controller import (
    DefaultModelController,
    State,
)
from tests._fake_model_connection import _RecordingModelConnection


def _default_controller_satisfies_protocol(
    controller: DefaultModelController,
) -> ModelController:
    # Structural conformance guard: mypy verifies DefaultModelController
    # satisfies the ModelController Protocol here (this file is in the mypy
    # ``files`` set). Never called at runtime.
    return controller


def _recording_connection_satisfies_model_connection(
    connection: _RecordingModelConnection,
) -> ModelConnection:
    # Structural conformance guard: the controller's dependency (a recording
    # test double) satisfies the ModelConnection Protocol.
    return connection


def _model_controller_is_a_binary_state_machine(ctrl: ModelController) -> BinaryStateMachine:
    # Structural conformance guard: ModelController is a BinaryStateMachine.
    return ctrl


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


@asynccontextmanager
async def _pair() -> AsyncGenerator[tuple[DefaultModelController, _RecordingModelConnection], None]:
    """A controller wired to a recording connection; yields (controller, connection).

    The controller is entered on entry. On exit ``controller.end()`` is called,
    which (with ``auto_end=True``) ends the connection's stream so the drain
    finishes; the controller is then reaped via ``__aexit__`` — no force-cancel
    under normal teardown.
    """
    connection = _RecordingModelConnection(auto_end=True)
    controller = DefaultModelController(connection)
    await controller.__aenter__()
    try:
        yield controller, connection
    finally:
        controller.end()
        await controller.__aexit__(None, None, None)


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
    async with _pair() as (controller, _connection):
        assert controller.is_idle() is True
        assert controller.is_closing() is False


async def test_generate_flips_busy_then_idle_on_done() -> None:
    async with _pair() as (controller, connection):
        assert controller.is_idle()

        task = asyncio.create_task(controller.generate())
        await asyncio.sleep(0)  # let generate call connection.generate()
        assert connection.generate_calls == 1
        assert controller.is_idle() is False  # busy

        connection.feed(ResponseStarted(partial=_assistant_item()))
        connection.feed(ResponseDone(item=_assistant_item()))
        result = await asyncio.wait_for(task, 1)  # generate returned to idle
        assert result == _assistant_item()

        assert controller.is_idle()


async def test_controller_bus_narrows_response_done() -> None:
    """A handler on the controller's bus narrows ``ResponseDone`` to ``.item``."""
    async with _pair() as (controller, connection):
        seen: list[str] = []
        done = asyncio.Event()

        async def handler(event: ServerContextEvent) -> None:
            match event.type:
                case ServerContextEventType.RESPONSE_DONE:
                    seen.append(event.item.id)  # strict-mypy narrowing of the union
                    done.set()
                case _:
                    pass

        controller.bus.on(ServerContextEventType.RESPONSE_DONE, handler)
        connection.feed(ResponseDone(item=_assistant_item()))
        await asyncio.wait_for(done.wait(), 1)
        assert seen == ["a1"]


# --------------------------------------------------------------------------- #
# DefaultModelController: on() subscription surface (Subscribable)
# --------------------------------------------------------------------------- #


async def test_on_rejects_unknown_type_string() -> None:
    async with _pair() as (controller, _connection):

        async def handler(_event: ServerContextEvent) -> None:
            pass

        with pytest.raises(ValueError):
            controller.on("not.a.real.event", handler)


async def test_on_subscribes_by_type_string_and_fires() -> None:
    async with _pair() as (controller, connection):
        seen: list[str] = []
        done = asyncio.Event()

        async def handler(event: ServerContextEvent) -> None:
            assert event.type == ServerContextEventType.RESPONSE_DONE
            seen.append(event.item.id)
            done.set()

        # The type key is a plain string; the StrEnum value resolves it.
        controller.on(ServerContextEventType.RESPONSE_DONE.value, handler)
        connection.feed(ResponseDone(item=_assistant_item()))
        await asyncio.wait_for(done.wait(), 1)
        assert seen == ["a1"]


# --------------------------------------------------------------------------- #
# DefaultModelController: command guards
# --------------------------------------------------------------------------- #


async def test_generate_while_busy_raises() -> None:
    async with _pair() as (controller, connection):
        task = asyncio.create_task(controller.generate())
        await asyncio.sleep(0)  # generate() called; controller busy + parked
        with pytest.raises(RuntimeError, match="busy"):
            await controller.generate()
        # Release the in-flight generation so it doesn't leak.
        connection.feed(ResponseDone(item=_assistant_item()))
        await asyncio.wait_for(task, 1)


async def test_add_message_calls_connection_when_idle() -> None:
    async with _pair() as (controller, connection):
        task = asyncio.create_task(controller.add_message("hi"))
        await asyncio.sleep(0)
        assert connection.user_messages == ["hi"]
        connection.feed(UserItemAdded(item=_user_item()))
        result = await asyncio.wait_for(task, 1)
        assert result == _user_item()
        assert controller.is_idle()


async def test_add_message_rejected_while_busy() -> None:
    async with _pair() as (controller, connection):
        task = asyncio.create_task(controller.generate())
        await asyncio.sleep(0)  # busy
        with pytest.raises(RuntimeError, match="busy"):
            await controller.add_message("hi")
        connection.feed(ResponseDone(item=_assistant_item()))
        await asyncio.wait_for(task, 1)


async def test_add_tool_result_calls_connection_when_idle() -> None:
    async with _pair() as (controller, connection):
        task = asyncio.create_task(controller.add_tool_result("t1", "get_time", "noon"))
        await asyncio.sleep(0)
        assert connection.tool_results == [("t1", "get_time", "noon")]
        connection.feed(ToolResultAdded(item=_tool_result_item()))
        result = await asyncio.wait_for(task, 1)
        assert result == _tool_result_item()
        assert controller.is_idle()


async def test_add_tool_result_rejected_while_busy() -> None:
    async with _pair() as (controller, connection):
        task = asyncio.create_task(controller.generate())
        await asyncio.sleep(0)  # busy
        with pytest.raises(RuntimeError, match="busy"):
            await controller.add_tool_result("t1", "get_time", "noon")
        connection.feed(ResponseDone(item=_assistant_item()))
        await asyncio.wait_for(task, 1)


async def test_add_message_ignores_mismatched_echo_type() -> None:
    """An ``add_message`` await must not complete on a ``ToolResultAdded`` echo."""
    async with _pair() as (controller, connection):
        task = asyncio.create_task(controller.add_message("hi"))
        await asyncio.sleep(0)  # add_user_message called; awaiting USER_ITEM_ADDED

        connection.feed(ToolResultAdded(item=_tool_result_item()))  # mismatched — ignored
        await asyncio.sleep(0.02)  # let the bus worker dispatch it
        assert task.done() is False  # still awaiting the matching echo

        connection.feed(UserItemAdded(item=_user_item()))  # matching — completes
        await asyncio.wait_for(task, 1)


async def test_add_tool_result_ignores_mismatched_echo_type() -> None:
    """An ``add_tool_result`` await must not complete on a ``UserItemAdded`` echo."""
    async with _pair() as (controller, connection):
        task = asyncio.create_task(controller.add_tool_result("t1", "get_time", "noon"))
        await asyncio.sleep(0)  # add_tool_result called; awaiting TOOL_RESULT_ADDED

        connection.feed(UserItemAdded(item=_user_item()))  # mismatched — ignored
        await asyncio.sleep(0.02)  # let the bus worker dispatch it
        assert task.done() is False  # still awaiting the matching echo

        connection.feed(ToolResultAdded(item=_tool_result_item()))  # matching — completes
        await asyncio.wait_for(task, 1)


async def test_abort_calls_connection_abort_when_busy() -> None:
    async with _pair() as (controller, connection):
        task = asyncio.create_task(controller.generate())
        await asyncio.sleep(0)  # generate() called; busy
        controller.abort()
        assert connection.abort_calls == 1
        # The server still ends the aborted generation with response.done.
        connection.feed(ResponseDone(item=_assistant_item()))
        await asyncio.wait_for(task, 1)


async def test_abort_when_idle_raises() -> None:
    async with _pair() as (controller, _connection):
        with pytest.raises(RuntimeError, match="idle"):
            controller.abort()


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
    async with _pair() as (controller, connection):
        done = asyncio.Event()

        async def handler(_event: ServerContextEvent) -> None:
            done.set()

        controller.bus.on(event.type, handler)
        connection.feed(event)
        await asyncio.wait_for(done.wait(), 1)


# --------------------------------------------------------------------------- #
# DefaultModelController: no-strand teardown of in-flight commands
# --------------------------------------------------------------------------- #


async def test_generate_raises_when_torn_down_mid_flight() -> None:
    """A wedged connection + teardown must release ``generate``; it must not hang."""
    async with _pair() as (controller, _connection):
        task = asyncio.create_task(controller.generate())
        await asyncio.sleep(0)  # generate() called; generate parked awaiting done
        assert controller.is_idle() is False
        # Exiting ends the connection cooperatively + closes the controller, which
        # releases the in-flight command (run loop exits).
    with pytest.raises(RuntimeError, match="run loop exited"):
        await task


async def test_add_message_raises_when_torn_down_mid_flight() -> None:
    """A wedged connection + teardown must release ``add_message``; it must not hang."""
    async with _pair() as (controller, _connection):
        task = asyncio.create_task(controller.add_message("hi"))
        await asyncio.sleep(0)  # add_user_message called; awaiting item-added echo
        assert controller.is_idle() is False
    with pytest.raises(RuntimeError, match="run loop exited"):
        await task


async def test_add_tool_result_raises_when_torn_down_mid_flight() -> None:
    """A wedged connection + teardown must release ``add_tool_result``; it must not hang."""
    async with _pair() as (controller, _connection):
        task = asyncio.create_task(controller.add_tool_result("t1", "get_time", "noon"))
        await asyncio.sleep(0)  # add_tool_result called; awaiting item-added echo
        assert controller.is_idle() is False
    with pytest.raises(RuntimeError, match="run loop exited"):
        await task


# --------------------------------------------------------------------------- #
# DefaultModelController: lifecycle / teardown
# --------------------------------------------------------------------------- #


async def test_end_initiates_terminate_and_guards_commands() -> None:
    async with _pair() as (controller, connection):
        controller.end()
        assert controller.is_closing() is True
        assert connection._ended is True  # connection.end() fired

        with pytest.raises(RuntimeError, match="closing"):
            await controller.generate()
        with pytest.raises(RuntimeError, match="closing"):
            await controller.add_message("hi")
        with pytest.raises(RuntimeError, match="closing"):
            await controller.add_tool_result("t1", "get_time", "noon")
        with pytest.raises(RuntimeError, match="closing"):
            controller.abort()


async def test_end_drains_final_items_before_teardown() -> None:
    """A fed ``ResponseDone`` completes an in-flight ``generate`` and reaches its
    bus handler before the connection is torn down."""
    async with _pair() as (controller, connection):
        received: list[ServerContextEvent] = []
        done = asyncio.Event()

        async def handler(event: ServerContextEvent) -> None:
            received.append(event)
            if isinstance(event, ResponseDone):
                done.set()

        controller.bus.on(ServerContextEventType.RESPONSE_DONE, handler)

        task = asyncio.create_task(controller.generate())
        await asyncio.sleep(0)  # generate parked

        connection.feed(ResponseDone(item=_assistant_item()))  # final item
        await asyncio.wait_for(done.wait(), 1)  # final item reached the handler
        await asyncio.wait_for(task, 1)  # generate completed from the response.done
        assert any(isinstance(e, ResponseDone) for e in received)


async def test_teardown_completes_cleanly() -> None:
    async with _pair() as (_controller, _connection):
        pass  # nothing in flight
    # Teardown completed cleanly on exit; the controller lifecycle task is done.
    assert _controller._task is not None
    assert _controller._task.done()


async def test_teardown_force_cancels_wedged_connection() -> None:
    # Wedged connection: nothing ever ends the stream, so the drain hangs and
    # __aexit__ force-cancels it within the shutdown deadline (teardown always
    # exits cleanly; no exception propagates). ``_run``'s finally ends the
    # bus, so the nested bus reap does not add latency.
    connection = _RecordingModelConnection(auto_end=False)
    controller = DefaultModelController(connection)
    controller._shutdown_timeout = 0.1
    loop = asyncio.get_running_loop()
    start = loop.time()
    async with controller:
        pass  # nothing ends the stream -> drain hangs -> __aexit__ forces
    assert loop.time() - start < 2.0  # force-cancelled within the deadline


async def test_async_context_manager_ends() -> None:
    connection = _RecordingModelConnection(auto_end=True)
    async with DefaultModelController(connection) as controller:
        assert controller.is_idle()
        controller.end()  # end -> connection.end() (auto_end) -> drain completes
    assert controller.is_closing()


async def test_end_is_idempotent() -> None:
    async with _pair() as (controller, _connection):
        controller.end()
        controller.end()  # idempotent
    assert controller.is_closing()


async def test_post_end_commands_rejected_even_when_idle() -> None:
    async with _pair() as (controller, _connection):
        controller.end()
        assert controller.is_idle()  # no generation was ever started
        with pytest.raises(RuntimeError, match="closing"):
            await controller.generate()
        with pytest.raises(RuntimeError, match="closing"):
            await controller.add_message("hi")
        with pytest.raises(RuntimeError, match="closing"):
            await controller.add_tool_result("t1", "get_time", "noon")


async def test_wait_idle_unblocks_when_torn_down_while_busy() -> None:
    """Teardown mid-generation must not strand wait_idle.

    Ending the connection + closing the controller winds the drain down; the
    ``_run`` ``finally`` defensively sets idle so a caller parked on
    ``wait_idle()`` is released rather than hung, and the in-flight
    ``generate()`` task raises rather than hanging.
    """
    async with _pair() as (controller, _connection):
        task = asyncio.create_task(controller.generate())
        await asyncio.sleep(0)
        assert controller.is_idle() is False  # busy
        # Exiting ends the connection + closes the controller, winding the drain
        # down and releasing the in-flight generate (run loop exits).
    with pytest.raises(RuntimeError, match="run loop exited"):
        await task
    # wait_idle() must return (defensive set_idle in _run's finally):
    await asyncio.wait_for(controller.wait_idle(), 1)
    assert controller.is_idle() is True


async def test_teardown_leaves_controller_task_done() -> None:
    async with _pair() as (_controller, _connection):
        pass
    # The controller and its bus drain tasks both completed on teardown.
    assert _controller._task is not None
    assert _controller._task.done()
