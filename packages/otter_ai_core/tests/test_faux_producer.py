"""FauxModelProducer / FauxModel — the integration-test harness.

These are **integration** tests: they stand up the *real* connection +
*real* :class:`~otter_ai_core.default_model_controller.DefaultModelController` (+ a real
:class:`~otter_ai_core.agent_loop.agent_loop.AgentLoop` for the tool turn) with
a :class:`~otter_ai_core.faux.FauxModelProducer` at the bottom, and assert on
producer output and the controller/loop round-trip — no API keys, no network.

Two cases (the synchronous-no-op abort and the latency contract-violation) drive
a *standalone* connection rather than :func:`create_faux_model`, because they
must push client→server events directly: ``DefaultModelController.abort()`` rejects
when idle, and ``FauxModel`` deliberately does not expose the client handle. This
is the standalone pattern documented in the #129 spec §14.5.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, cast

import pytest
from pydantic import BaseModel

from otter_ai_core import (
    AssistantContextItem,
    DefaultModelController,
    FauxBranchOutcome,
    FauxCompactionOutcome,
    FauxModelProducer,
    FauxModelScript,
    FauxProvenance,
    FauxResponse,
    FauxResponseRepeat,
    FauxStreamPolicy,
    StopReason,
    TextContent,
    ToolCall,
    UserMessage,
    create_connection,
    create_faux_model,
    faux_text_response,
    faux_tool_call_response,
)
from otter_ai_core.agent_loop.agent_loop import AgentLoop, QueueMode
from otter_ai_core.agent_loop.agent_tool import AgentToolResult, DefaultAgentTool
from otter_ai_core.context import ContentType, Role
from otter_ai_core.interfaces import AgentTool
from otter_ai_core.model_connection import (
    AbortResponse,
    AddUserMessage,
    CompactionDone,
    CreateResponse,
    ModelConnectionPair,
    ResponseUpdated,
    ServerContextEvent,
    ServerContextEventType,
)

# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def _user_message(text: str = "hi", timestamp: int = 0) -> UserMessage:
    return UserMessage(role=Role.User, content=text, timestamp=timestamp)


def _tool_call(call_id: str = "c1", name: str = "echo", **arguments: Any) -> ToolCall:
    return ToolCall(type=ContentType.ToolCall, id=call_id, name=name, arguments=dict(arguments))


def _first_text(item: AssistantContextItem) -> str:
    """Return the first ``TextContent`` block's text (with narrowing)."""
    for block in item.message.content:
        if isinstance(block, TextContent):
            return block.text
    raise AssertionError("expected a text content block")


class _EchoArgs(BaseModel):
    text: str = ""


async def _echo_execute(
    tool_call_id: str,  # noqa: ARG001
    params: _EchoArgs,
    signal: asyncio.Event,  # noqa: ARG001
) -> AgentToolResult[Any]:
    return AgentToolResult(
        result=[TextContent(type=ContentType.Text, text=params.text)],
        details=None,
    )


def _echo_tool() -> AgentTool[_EchoArgs, Any]:
    return DefaultAgentTool("echo", "echo the text back", _EchoArgs, _echo_execute)


def _tools(*tools: AgentTool[Any, Any]) -> list[AgentTool[BaseModel, Any]]:
    """Upcast a heterogeneous tool list to the loop's invariant field type."""
    return cast("list[AgentTool[BaseModel, Any]]", list(tools))


async def _drain(producer: Any, *, ticks: int = 20) -> None:
    """Yield control so a standalone producer's drain loop can run ``ticks`` times."""
    for _ in range(ticks):
        await asyncio.sleep(0)


# --------------------------------------------------------------------------- #
# 1. Echo turn (controller-level)
# --------------------------------------------------------------------------- #


async def test_echo_turn_round_trips_with_deterministic_ids() -> None:
    script = FauxModelScript(responses=[faux_text_response("hi there")])

    async with create_faux_model(script) as model:
        await model.controller.add_message(AddUserMessage(message=_user_message("hello")))
        item = await model.controller.generate()

        assert item.message.content[0].text == "hi there"  # type: ignore[union-attr]
        assert item.message.stop_reason == StopReason.Stop
        assert item.id == "item-2"  # item-1 was the user echo; ids are role-shared
        assert item.message.timestamp == 0  # deterministic_clock starts at 0
        assert [type(e).__name__ for e in model.producer.requests] == [
            "AddUserMessage",
            "CreateResponse",
        ]
        assert model.producer.response_count == 1
        assert model.producer.last_create is not None


# --------------------------------------------------------------------------- #
# 2. Tool-call turn via the real AgentLoop
# --------------------------------------------------------------------------- #


async def test_tool_call_turn_drives_real_agent_loop() -> None:
    script = FauxModelScript(
        responses=[
            faux_tool_call_response([_tool_call(text="ping")]),
            faux_text_response("done"),
        ]
    )

    async with create_faux_model(script) as model:
        loop = AgentLoop(
            _controller=model.controller,
            _follow_up_mode=QueueMode.ALL_AT_ONCE,
            _steering_mode=QueueMode.ALL_AT_ONCE,
            _tools=_tools(_echo_tool()),
        )
        loop.follow_up(_user_message("run echo"))
        assert loop._task is not None  # noqa: SLF001 — set by __post_init__
        await loop._task  # noqa: SLF001 — established await pattern (tests/test_agent_loop.py)

        assert model.producer.response_count == 2  # tool turn, then clean stop
        assert [type(e).__name__ for e in model.producer.requests] == [
            "AddUserMessage",
            "CreateResponse",  # turn 1: tool call
            "AddToolResultMessage",
            "CreateResponse",  # turn 2: stop
        ]


# --------------------------------------------------------------------------- #
# 3. Streaming
# --------------------------------------------------------------------------- #


async def test_streaming_emits_growing_text_partials() -> None:
    script = FauxModelScript(
        responses=[faux_text_response("abc", stream=FauxStreamPolicy(enabled=True, chunk_size=1))]
    )

    async with create_faux_model(script) as model:
        seen: list[ServerContextEvent] = []

        async def _collect(event: ServerContextEvent) -> None:
            seen.append(event)

        unsubs = [
            model.controller.on(ServerContextEventType.RESPONSE_STARTED, _collect),
            model.controller.on(ServerContextEventType.RESPONSE_UPDATED, _collect),
            model.controller.on(ServerContextEventType.RESPONSE_DONE, _collect),
        ]
        try:
            item = await model.controller.generate()
        finally:
            for unsub in unsubs:
                unsub()

        assert [type(e).__name__ for e in seen] == [
            "ResponseStarted",
            "ResponseUpdated",
            "ResponseUpdated",
            "ResponseUpdated",
            "ResponseDone",
        ]
        updated = [e for e in seen if isinstance(e, ResponseUpdated)]
        assert [_first_text(u.partial) for u in updated] == ["a", "ab", "abc"]
        assert all(u.partial.message.stop_reason is None for u in updated)
        # identical provenance to the final message (model_copy shares it)
        assert all(u.partial.id == item.id for u in updated)
        assert _first_text(item) == "abc"
        assert item.message.stop_reason == StopReason.Stop


# --------------------------------------------------------------------------- #
# 4. Protocol abort (latency path) — end-to-end through the real connection
# --------------------------------------------------------------------------- #


async def test_protocol_abort_latency_path() -> None:
    script = FauxModelScript(responses=[faux_text_response("never mind", delay=0.1)])

    async with create_faux_model(script) as model:
        gen = asyncio.create_task(model.controller.generate())
        await asyncio.sleep(0.02)  # let the producer enter the latency window
        model.controller.abort()  # protocol abort mid-flight
        item = await asyncio.wait_for(gen, 1)

        assert item.message.stop_reason == StopReason.Aborted
        assert item.message.error_message == "aborted"
        # aborted done carries the full scripted content (determinism choice)
        assert _first_text(item) == "never mind"
        assert [type(e).__name__ for e in model.producer.requests] == [
            "CreateResponse",
            "AbortResponse",
        ]
        assert model.producer.response_count == 1


# --------------------------------------------------------------------------- #
# 5. Protocol abort (synchronous no-op) — standalone (controller rejects idle abort)
# --------------------------------------------------------------------------- #


async def test_protocol_abort_synchronous_noop() -> None:
    # Standalone connection (no controller): the controller rejects abort() while
    # idle, and FauxModel does not expose the client handle, so push directly.
    # With delay=0 a generation resolves synchronously within one _handle step
    # and clears _in_flight, so a later AbortResponse is a correct no-op
    # (no double-emit).
    pair: ModelConnectionPair = create_connection()
    script = FauxModelScript(responses=[faux_text_response("hi")])  # delay=0

    async with FauxModelProducer(pair.backend, script) as producer:
        pair.client.push(CreateResponse())
        await _drain(producer)
        assert producer.response_count == 1

        pair.client.push(AbortResponse())  # nothing in flight
        await _drain(producer)
        assert producer.response_count == 1  # unchanged
        assert [type(e).__name__ for e in producer.requests] == [
            "CreateResponse",
            "AbortResponse",
        ]


# --------------------------------------------------------------------------- #
# 6. Latency-window contract violation fails loud — standalone
# --------------------------------------------------------------------------- #


async def test_latency_window_contract_violation_fails_loud(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pair: ModelConnectionPair = create_connection()
    script = FauxModelScript(responses=[faux_text_response("x", delay=0.1)])

    async with FauxModelProducer(pair.backend, script) as producer:
        with caplog.at_level(logging.ERROR, logger="otter_ai_core.faux.producer"):
            pair.client.push(CreateResponse())
            await asyncio.sleep(0.02)  # enter the window
            # Single-flight breach: a non-AbortResponse event mid-window.
            pair.client.push(AddUserMessage(message=_user_message("intruder")))
            await asyncio.sleep(0.05)  # let the race resolve + the error log flush

        # The producer did not silently drop the event and continue: it emitted
        # no terminal response.done and its drain loop terminated, logging the
        # RuntimeError (fail-loud) rather than swallowing it.
        assert producer.response_count == 0
        assert producer._task.done()  # noqa: SLF001
        assert any(
            rec.exc_info is not None and "non-abort event" in str(rec.exc_info[1])
            for rec in caplog.records
        ), [rec.message for rec in caplog.records]


# --------------------------------------------------------------------------- #
# 7. Session ops — compaction
# --------------------------------------------------------------------------- #


async def test_compaction_happy_path_echoes_script_default() -> None:
    script = FauxModelScript(responses=[faux_text_response("ok")])

    async with create_faux_model(script) as model:
        await model.controller.generate()
        confirm = await model.controller.compact()

    assert isinstance(confirm, CompactionDone)
    assert confirm.summary == "faux compaction summary"
    assert confirm.error_message is None


async def test_compaction_client_summary_is_echoed() -> None:
    script = FauxModelScript(responses=[faux_text_response("ok")])

    async with create_faux_model(script) as model:
        await model.controller.generate()
        confirm = await model.controller.compact(summary="my summary", first_kept_item_id="k1")

    assert confirm.summary == "my summary"
    assert confirm.first_kept_item_id == "k1"
    assert confirm.error_message is None


async def test_compaction_refusal_is_returned_not_raised() -> None:
    script = FauxModelScript(
        responses=[faux_text_response("ok")],
        compaction=FauxCompactionOutcome(error_message="stateless: cannot compact in place"),
    )

    async with create_faux_model(script) as model:
        await model.controller.generate()
        confirm = await model.controller.compact()

    assert confirm.error_message == "stateless: cannot compact in place"


# --------------------------------------------------------------------------- #
# 8. Session ops — branch
# --------------------------------------------------------------------------- #


async def test_branch_happy_path() -> None:
    script = FauxModelScript(responses=[faux_text_response("ok")])

    async with create_faux_model(script) as model:
        await model.controller.generate()
        confirm = await model.controller.branch(at_item_id="item-2")

    assert confirm.at_item_id == "item-2"
    assert confirm.error_message is None


async def test_branch_refusal_still_echoes_at_item_id() -> None:
    script = FauxModelScript(
        responses=[faux_text_response("ok")],
        branch=FauxBranchOutcome(error_message="unsupported"),
    )

    async with create_faux_model(script) as model:
        await model.controller.generate()
        confirm = await model.controller.branch(at_item_id="item-1")

    assert confirm.at_item_id == "item-1"  # echoed from the request
    assert confirm.error_message == "unsupported"


# --------------------------------------------------------------------------- #
# 9. Script exhaustion
# --------------------------------------------------------------------------- #


async def test_script_exhaustion_errors_loud_not_hangs() -> None:
    script = FauxModelScript(responses=[faux_text_response("only one")])  # repeat=ERROR

    async with create_faux_model(script) as model:
        first = await model.controller.generate()
        assert _first_text(first) == "only one"

        second = await model.controller.generate()  # script exhausted
        assert second.message.stop_reason == StopReason.Error
        assert "script exhausted" in (second.message.error_message or "")
        assert model.producer.response_count == 2


async def test_empty_script_errors_on_first_generate() -> None:
    script = FauxModelScript(responses=[])

    async with create_faux_model(script) as model:
        item = await model.controller.generate()

    assert item.message.stop_reason == StopReason.Error
    assert "script exhausted" in (item.message.error_message or "")


async def test_repeat_last_replays_final_response() -> None:
    script = FauxModelScript(
        responses=[faux_text_response("same"), faux_text_response("same")],
        repeat=FauxResponseRepeat.LAST,
    )

    async with create_faux_model(script) as model:
        for _ in range(4):
            item = await model.controller.generate()
            assert _first_text(item) == "same"
        assert model.producer.response_count == 4


# --------------------------------------------------------------------------- #
# 10. Script reuse (the §5/§8 invariant)
# --------------------------------------------------------------------------- #


async def test_script_reuse_is_independent() -> None:
    script = FauxModelScript(responses=[faux_text_response("a"), faux_text_response("b")])

    first_ids: list[str] = []
    second_ids: list[str] = []
    async with create_faux_model(script) as a:
        first_ids.append((await a.controller.generate()).id)
        first_ids.append((await a.controller.generate()).id)
    async with create_faux_model(script) as b:
        second_ids.append((await b.controller.generate()).id)
        second_ids.append((await b.controller.generate()).id)

    # The script was not mutated: both producers saw the full response list.
    assert first_ids == ["item-1", "item-2"]
    # Each producer materialises its own id/clock generators from the script's
    # factories — the second producer starts fresh at item-1 / timestamp 0.
    assert second_ids == ["item-1", "item-2"]


# --------------------------------------------------------------------------- #
# 11. Stop-reason inference
# --------------------------------------------------------------------------- #


async def test_stop_reason_infers_tool_use_from_tool_call() -> None:
    script = FauxModelScript(responses=[faux_tool_call_response([_tool_call()])])

    async with create_faux_model(script) as model:
        item = await model.controller.generate()

    assert item.message.stop_reason == StopReason.ToolUse


async def test_explicit_stop_reason_wins_over_inference() -> None:
    script = FauxModelScript(
        responses=[faux_tool_call_response([_tool_call()], stop_reason=StopReason.Stop)]
    )

    async with create_faux_model(script) as model:
        item = await model.controller.generate()

    assert item.message.stop_reason == StopReason.Stop


# --------------------------------------------------------------------------- #
# 12. Empty-text tool call
# --------------------------------------------------------------------------- #


async def test_empty_text_tool_call_has_no_text_block() -> None:
    script = FauxModelScript(responses=[FauxResponse.tool_calls([_tool_call()])])

    async with create_faux_model(script) as model:
        item = await model.controller.generate()

    assert not any(isinstance(block, TextContent) for block in item.message.content)
    assert any(isinstance(block, ToolCall) for block in item.message.content)


# --------------------------------------------------------------------------- #
# 13. Determinism (scoped to producer output)
# --------------------------------------------------------------------------- #


async def test_same_script_yields_identical_producer_output() -> None:
    script = FauxModelScript(responses=[faux_text_response("x"), faux_text_response("y")])

    run_one: list[tuple[str, int]] = []
    run_two: list[tuple[str, int]] = []
    async with create_faux_model(script) as a:
        for _ in range(2):
            it = await a.controller.generate()
            run_one.append((it.id, it.message.timestamp))
    async with create_faux_model(script) as b:
        for _ in range(2):
            it = await b.controller.generate()
            run_two.append((it.id, it.message.timestamp))

    assert run_one == run_two == [("item-1", 0), ("item-2", 1)]


async def test_custom_factories_are_honoured() -> None:
    counter = {"n": 1000}

    def ids() -> Any:
        def gen() -> str:
            counter["n"] += 1
            return f"x-{counter['n']}"

        return gen

    script = FauxModelScript(
        responses=[faux_text_response("a")],
        item_id_factory=ids,
        clock_factory=lambda: lambda: 42,
    )

    async with create_faux_model(script) as model:
        item = await model.controller.generate()

    assert item.id == "x-1001"
    assert item.message.timestamp == 42


# --------------------------------------------------------------------------- #
# 14. delay resolution
# --------------------------------------------------------------------------- #


async def test_explicit_delay_zero_overrides_script_delay() -> None:
    # script delay is large, but the response pins delay=0.0 -> no window.
    script = FauxModelScript(delay=0.2, responses=[FauxResponse.text("ok", delay=0.0)])

    async with create_faux_model(script) as model:
        gen = asyncio.create_task(model.controller.generate())
        await asyncio.sleep(0.05)  # well within the 0.2s a window would last
        assert gen.done()  # completed synchronously — no latency window
        item = await gen
        assert item.message.stop_reason == StopReason.Stop


async def test_delay_none_inherits_script_delay() -> None:
    script = FauxModelScript(delay=0.2, responses=[faux_text_response("ok")])  # delay=None

    async with create_faux_model(script) as model:
        gen = asyncio.create_task(model.controller.generate())
        await asyncio.sleep(0.05)  # well inside the inherited window
        assert not gen.done()  # still in flight — window inherited
        item = await asyncio.wait_for(gen, 2)
        assert item.message.stop_reason == StopReason.Stop


# --------------------------------------------------------------------------- #
# 15. Teardown
# --------------------------------------------------------------------------- #


async def test_aclose_leaves_no_pending_tasks() -> None:
    script = FauxModelScript(responses=[faux_text_response("ok")])

    async with create_faux_model(script) as model:
        await model.controller.generate()

    assert model.controller._task.done()  # noqa: SLF001
    assert model.producer._task.done()  # noqa: SLF001
    assert model.controller.is_closing()


async def test_aclose_is_idempotent() -> None:
    script = FauxModelScript(responses=[faux_text_response("ok")])
    model = create_faux_model(script)
    try:
        await model.aclose()
        await model.aclose()  # second teardown is a no-op, not an error
    finally:
        await model.aclose()


async def test_aclose_races_inflight_generate_cleanly() -> None:
    script = FauxModelScript(responses=[faux_text_response("x", delay=0.2)])

    async with create_faux_model(script) as model:
        gen = asyncio.create_task(model.controller.generate())
        await asyncio.sleep(0.02)  # enter the latency window
        await model.aclose()  # teardown races the in-flight generation

    # The in-flight generate was released by the controller's run-loop exit
    # (it raises RuntimeError on teardown) — not stranded.
    with contextlib.suppress(RuntimeError):
        await gen
    assert gen.done()
    assert model.controller._task.done()  # noqa: SLF001
    assert model.producer._task.done()  # noqa: SLF001


async def test_standalone_producer_reaps_after_controller_aclose() -> None:
    pair: ModelConnectionPair = create_connection()
    script = FauxModelScript(responses=[faux_text_response("ok")])

    async with FauxModelProducer(pair.backend, script) as producer:
        controller = DefaultModelController(pair.client)
        await controller.generate()
        await controller.aclose()
    # producer task reaped on context exit (cooperatively — the controller
    # closed the outbound first, so the producer's drain already exited).
    assert producer._task.done()  # noqa: SLF001


# --------------------------------------------------------------------------- #
# 16. Provenance override
# --------------------------------------------------------------------------- #


async def test_per_response_provenance_overrides_script_default() -> None:
    script = FauxModelScript(
        responses=[
            faux_text_response("first", provenance=FauxProvenance(model="override-model")),
            faux_text_response("second"),
        ]
    )

    async with create_faux_model(script) as model:
        first = await model.controller.generate()
        second = await model.controller.generate()

    assert first.message.model == "override-model"
    assert second.message.model == "faux-model"  # script default, override is per-turn


# --------------------------------------------------------------------------- #
# 17. Spy snapshot
# --------------------------------------------------------------------------- #


async def test_requests_returns_a_fresh_snapshot() -> None:
    script = FauxModelScript(responses=[faux_text_response("ok")])

    async with create_faux_model(script) as model:
        await model.controller.generate()
        snapshot = model.producer.requests
        snapshot.clear()  # mutate the returned list
        again = model.producer.requests
        assert [type(e).__name__ for e in again] == ["CreateResponse"]  # internal record intact
