import asyncio

import pytest

from otter_ai_core.components.gate import Gate


async def test_completed_wait_consumes_the_opening() -> None:
    gate = Gate()
    first = asyncio.create_task(gate.wait())
    await asyncio.sleep(0)  # first wait reaches the closed gate and blocks
    assert not first.done()

    gate.set()
    await first  # the opening admits the waiter

    second = asyncio.create_task(gate.wait())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not second.done()  # the pass consumed the opening; the gate closed again

    gate.set()
    await second


async def test_set_with_no_waiter_is_remembered() -> None:
    gate = Gate()
    gate.set()  # opened in advance, before anyone is waiting

    waiter = asyncio.create_task(gate.wait())
    await waiter  # passes on the remembered opening; no further set() needed


async def test_repeated_set_collapses_to_one_opening() -> None:
    gate = Gate()
    gate.set()
    gate.set()  # opening twice must not queue two passes

    first = asyncio.create_task(gate.wait())
    await first  # consumes the single pending opening

    second = asyncio.create_task(gate.wait())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not second.done()  # only one pass was pending; the gate closed again

    gate.set()
    await second  # a fresh opening admits the second waiter — the gate isn't wedged


async def test_set_releases_all_queued_waiters_at_once() -> None:
    gate = Gate()
    first = asyncio.create_task(gate.wait())
    await asyncio.sleep(0)  # first wait reaches the closed gate and blocks
    second = asyncio.create_task(gate.wait())
    await asyncio.sleep(0)
    await asyncio.sleep(0)  # second wait blocks; both waiters are queued

    gate.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert first.done()  # one opening releases...
    assert second.done()  # ...every waiter queued at set() time
    await first
    await second  # propagate any exceptions the waits raised

    third = asyncio.create_task(gate.wait())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not third.done()  # the gate closed behind the released batch


async def test_cancelling_a_blocked_waiter_does_not_disturb_the_gate() -> None:
    gate = Gate()
    cancelled = asyncio.create_task(gate.wait())
    await asyncio.sleep(0)  # first wait blocks
    survivor = asyncio.create_task(gate.wait())
    await asyncio.sleep(0)
    await asyncio.sleep(0)  # both waiters queued

    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    assert not survivor.done()  # one waiter's cancellation releases nobody

    gate.set()
    await survivor  # the opening still releases the remaining waiter

    fresh = asyncio.create_task(gate.wait())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not fresh.done()  # the gate closed behind the survivor — nothing wedged
