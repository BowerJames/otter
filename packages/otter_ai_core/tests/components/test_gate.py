import asyncio

import pytest

from otter_ai_core.components.gate import Gate


async def test_completed_wait_consumes_the_opening() -> None:
    gate = Gate()
    first = asyncio.create_task(gate.wait_for_open())
    await asyncio.sleep(0)  # first wait reaches the closed gate and blocks
    assert not first.done()

    gate.open()
    await first  # the opening admits the waiter

    second = asyncio.create_task(gate.wait_for_open())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not second.done()  # the pass consumed the opening; the gate closed again

    gate.open()
    await second


async def test_open_with_no_waiter_is_remembered() -> None:
    gate = Gate()
    gate.open()  # opened in advance, before anyone is waiting

    waiter = asyncio.create_task(gate.wait_for_open())
    await waiter  # passes on the remembered opening; no further open() needed


async def test_repeated_open_collapses_to_one_opening() -> None:
    gate = Gate()
    gate.open()
    gate.open()  # opening twice must not queue two passes

    first = asyncio.create_task(gate.wait_for_open())
    await first  # consumes the single pending opening

    second = asyncio.create_task(gate.wait_for_open())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not second.done()  # only one pass was pending; the gate closed again

    gate.open()
    await second  # a fresh opening admits the second waiter — the gate isn't wedged


async def test_open_releases_all_queued_waiters_at_once() -> None:
    gate = Gate()
    first = asyncio.create_task(gate.wait_for_open())
    await asyncio.sleep(0)  # first wait reaches the closed gate and blocks
    second = asyncio.create_task(gate.wait_for_open())
    await asyncio.sleep(0)
    await asyncio.sleep(0)  # second wait blocks; both waiters are queued

    gate.open()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert first.done()  # one opening releases...
    assert second.done()  # ...every waiter queued at open() time
    await first
    await second  # propagate any exceptions the waits raised

    third = asyncio.create_task(gate.wait_for_open())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not third.done()  # the gate closed behind the released batch


async def test_wait_for_arrival_completes_once_a_waiter_parks() -> None:
    gate = Gate()
    arrival = asyncio.create_task(gate.wait_for_arrival())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not arrival.done()  # nobody has reached the gate; nothing to signal

    waiter = asyncio.create_task(gate.wait_for_open())
    await asyncio.sleep(0)  # waiter reaches the closed gate and parks

    await asyncio.wait_for(arrival, timeout=1)  # the pause point is reached

    gate.open()
    await waiter  # leave nothing parked behind


async def test_free_pass_through_an_open_gate_does_not_signal_arrival() -> None:
    gate = Gate()
    gate.open()  # remembered opening; nobody waiting

    passer = asyncio.create_task(gate.wait_for_open())
    await passer  # slips straight through the open gate; nothing ever paused

    arrival = asyncio.create_task(gate.wait_for_arrival())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not arrival.done()  # a free pass is not an arrival

    arrival.cancel()
    with pytest.raises(asyncio.CancelledError):
        await arrival


async def test_arrival_signal_resets_on_open_and_fires_per_arrival() -> None:
    gate = Gate()
    first = asyncio.create_task(gate.wait_for_open())
    await asyncio.sleep(0)  # first parks at the closed gate
    await asyncio.wait_for(gate.wait_for_arrival(), timeout=1)

    gate.open()
    await first  # the released batch passes through

    arrival = asyncio.create_task(gate.wait_for_arrival())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not arrival.done()  # the epoch ended with the release; no signal

    arrival.cancel()
    with pytest.raises(asyncio.CancelledError):
        await arrival

    second = asyncio.create_task(gate.wait_for_open())
    await asyncio.sleep(0)  # a fresh waiter parks
    await asyncio.wait_for(gate.wait_for_arrival(), timeout=1)  # next epoch fires

    gate.open()
    await second


async def test_cancelling_every_parked_waiter_resets_the_arrival_signal() -> None:
    gate = Gate()
    waiter = asyncio.create_task(gate.wait_for_open())
    await asyncio.sleep(0)  # waiter parks
    await asyncio.wait_for(gate.wait_for_arrival(), timeout=1)

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter  # the cancellation runs wait_for_open's cleanup

    arrival = asyncio.create_task(gate.wait_for_arrival())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not arrival.done()  # no parked callers remain; the signal reset

    arrival.cancel()
    with pytest.raises(asyncio.CancelledError):
        await arrival


async def test_cancelling_a_blocked_waiter_does_not_disturb_the_gate() -> None:
    gate = Gate()
    cancelled = asyncio.create_task(gate.wait_for_open())
    await asyncio.sleep(0)  # first wait blocks
    survivor = asyncio.create_task(gate.wait_for_open())
    await asyncio.sleep(0)
    await asyncio.sleep(0)  # both waiters queued

    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    assert not survivor.done()  # one waiter's cancellation releases nobody
    await asyncio.wait_for(gate.wait_for_arrival(), timeout=1)  # survivor still parked: signalled

    gate.open()
    await survivor  # the opening still releases the remaining waiter

    fresh = asyncio.create_task(gate.wait_for_open())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not fresh.done()  # the gate closed behind the survivor — nothing wedged
