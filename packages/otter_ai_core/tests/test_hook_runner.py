"""HookRunner: typed emit-and-await registry (single handler per hook)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from otter_ai_core.hook_runner import Hook, HookRunner


@dataclass(frozen=True, slots=True)
class Ping:
    msg: str


@dataclass(frozen=True, slots=True)
class Pong:
    echoed: str


# Module-level hook singletons — the intended usage pattern.
PING: Hook[Ping, Pong] = Hook("ping")
TAP: Hook[Ping, None] = Hook("tap")
UNHANDLED: Hook[Ping, Pong] = Hook("unhandled")
OTHER: Hook[Ping, Pong] = Hook("other")


def _runner() -> HookRunner:
    return HookRunner()


async def test_emit_returns_handler_result() -> None:
    runner = _runner()

    async def handler(ping: Ping) -> Pong:
        return Pong(echoed=ping.msg)

    runner.register(PING, handler)
    result = await runner.emit(PING, Ping(msg="hi"))
    assert result == Pong(echoed="hi")


async def test_emit_returns_none_when_no_handler() -> None:
    runner = _runner()
    result = await runner.emit(UNHANDLED, Ping(msg="hi"))
    assert result is None


async def test_register_returns_unregister_that_removes_handler() -> None:
    runner = _runner()

    async def handler(ping: Ping) -> Pong:
        return Pong(echoed=ping.msg)

    unregister = runner.register(PING, handler)
    assert await runner.emit(PING, Ping(msg="hi")) is not None

    unregister()
    assert await runner.emit(PING, Ping(msg="hi")) is None


async def test_unregister_is_idempotent() -> None:
    runner = _runner()

    async def handler(ping: Ping) -> Pong:
        return Pong(echoed=ping.msg)

    unregister = runner.register(PING, handler)
    unregister()
    unregister()  # second call is a no-op and must not raise
    assert await runner.emit(PING, Ping(msg="hi")) is None


async def test_register_raises_on_reregister() -> None:
    runner = _runner()

    async def handler_a(ping: Ping) -> Pong:
        return Pong(echoed="a")

    async def handler_b(ping: Ping) -> Pong:
        return Pong(echoed="b")

    runner.register(PING, handler_a)
    with pytest.raises(RuntimeError, match="already has a registered handler"):
        runner.register(PING, handler_b)


async def test_unregister_then_reregister_replaces() -> None:
    runner = _runner()

    async def handler_a(ping: Ping) -> Pong:
        return Pong(echoed="a")

    async def handler_b(ping: Ping) -> Pong:
        return Pong(echoed="b")

    unregister = runner.register(PING, handler_a)
    result = await runner.emit(PING, Ping(msg="x"))
    assert result is not None
    assert result.echoed == "a"

    unregister()
    runner.register(PING, handler_b)
    result = await runner.emit(PING, Ping(msg="x"))
    assert result is not None
    assert result.echoed == "b"


async def test_handler_exception_propagates() -> None:
    runner = _runner()

    async def handler(ping: Ping) -> Pong:
        raise ValueError("boom")

    runner.register(PING, handler)
    with pytest.raises(ValueError, match="boom"):
        await runner.emit(PING, Ping(msg="hi"))


async def test_stale_unregister_does_not_remove_replacement() -> None:
    runner = _runner()

    async def handler_a(ping: Ping) -> Pong:
        return Pong(echoed="a")

    async def handler_b(ping: Ping) -> Pong:
        return Pong(echoed="b")

    unregister_a = runner.register(PING, handler_a)
    unregister_a()
    runner.register(PING, handler_b)

    unregister_a()  # stale — must not remove handler_b
    result = await runner.emit(PING, Ping(msg="x"))
    assert result is not None
    assert result.echoed == "b"


async def test_tap_hook_returns_none() -> None:
    # A hook whose TReturn is None: handler-present-None is indistinguishable
    # from handler-absent-None (the accepted trade-off). Both yield None, but
    # the handler still runs.
    runner = _runner()
    seen: list[str] = []

    async def handler(ping: Ping) -> None:
        seen.append(ping.msg)

    runner.register(TAP, handler)
    # TReturn is None, so emit returns None by definition — the point is that
    # the handler still ran:
    await runner.emit(TAP, Ping(msg="hi"))
    assert seen == ["hi"]
    assert await runner.emit(UNHANDLED, Ping(msg="hi")) is None  # no handler


async def test_distinct_hooks_route_independently() -> None:
    runner = _runner()
    seen: list[str] = []

    async def on_ping(ping: Ping) -> Pong:
        seen.append(f"ping:{ping.msg}")
        return Pong(echoed=ping.msg)

    async def on_other(ping: Ping) -> Pong:
        seen.append(f"other:{ping.msg}")
        return Pong(echoed=ping.msg)

    runner.register(PING, on_ping)
    runner.register(OTHER, on_other)

    await runner.emit(PING, Ping(msg="1"))
    await runner.emit(OTHER, Ping(msg="2"))

    assert seen == ["ping:1", "other:2"]


async def test_handler_receives_exact_params() -> None:
    runner = _runner()
    ping = Ping(msg="identity")
    received: list[Ping] = []

    async def handler(ping: Ping) -> Pong:
        received.append(ping)
        return Pong(echoed=ping.msg)

    runner.register(PING, handler)
    await runner.emit(PING, ping)
    assert received == [ping]
    assert received[0] is ping  # exact object, by identity


async def test_hook_equality_is_by_name() -> None:
    # Runtime generic erasure: same-name descriptors are the same key
    # regardless of type parameters. This pins the singleton convention.
    runner = _runner()
    same_name_a: Hook[Ping, Pong] = Hook("dup")
    same_name_b: Hook[Ping, None] = Hook("dup")

    async def handler_a(_: Ping) -> Pong:
        return Pong(echoed="a")

    async def handler_b(_: Ping) -> None:
        pass

    # Runtime generic erasure: same-name descriptors are equal as keys regardless
    # of their (statically non-overlapping) type parameters.
    assert same_name_a == same_name_b  # type: ignore[comparison-overlap]
    assert hash(same_name_a) == hash(same_name_b)

    runner.register(same_name_a, handler_a)
    with pytest.raises(RuntimeError, match="already has a registered handler"):
        runner.register(same_name_b, handler_b)  # collides — same key
