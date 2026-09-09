import asyncio
from collections.abc import AsyncIterator, Iterator
from unittest.mock import AsyncMock, Mock

import pytest

from .mock_scripting import ScriptExhausted, script


def test_iterable_script_returns_items_in_order() -> None:
    mock = Mock()
    script(mock, ["a", "b"])

    assert mock() == "a"
    assert mock() == "b"
    assert mock.outcomes == ["a", "b"]
    assert mock.call_count == 2


def test_iterable_script_raises_exception_instance_and_records_it() -> None:
    mock = Mock()
    boom = RuntimeError("boom")
    script(mock, [boom, "after"])

    with pytest.raises(RuntimeError):
        mock()
    assert mock() == "after"
    assert mock.outcomes == [boom, "after"]


def test_iterable_script_raises_exception_class() -> None:
    mock = Mock()
    script(mock, [ValueError])

    with pytest.raises(ValueError):
        mock()
    assert mock.outcomes == [ValueError]


def test_exhausted_script_raises_and_records_script_exhausted() -> None:
    mock = Mock()
    script(mock, ["only"])

    assert mock() == "only"
    with pytest.raises(ScriptExhausted):
        mock()
    assert mock.outcomes[0] == "only"
    assert isinstance(mock.outcomes[1], ScriptExhausted)


def test_outcomes_are_index_aligned_with_call_args_list() -> None:
    mock = Mock()
    script(mock, ["a", "b"])

    mock("x")
    mock(y=1)

    assert mock.call_args_list[0].args == ("x",)
    assert mock.outcomes[0] == "a"
    assert mock.call_args_list[1].kwargs == {"y": 1}
    assert mock.outcomes[1] == "b"


def test_bare_exception_is_raised_on_every_call() -> None:
    mock = Mock()
    boom = RuntimeError("always")
    script(mock, boom)

    for _ in range(3):
        with pytest.raises(RuntimeError):
            mock()
    assert mock.outcomes == [boom, boom, boom]


def test_rescripting_replaces_behavior_and_outcomes() -> None:
    mock = Mock()
    script(mock, ["old"])
    assert mock() == "old"

    script(mock, ["new"])

    assert mock.outcomes == []
    assert mock() == "new"
    assert mock.outcomes == ["new"]


def test_sync_callable_receives_args_and_return_is_recorded() -> None:
    mock = Mock()
    script(mock, lambda a, b=0: a + b)

    assert mock(2, b=3) == 5
    assert mock.outcomes == [5]


def test_sync_callable_raising_is_recorded_and_propagates() -> None:
    def behavior() -> int:
        raise ValueError("nope")

    mock = Mock()
    script(mock, behavior)

    with pytest.raises(ValueError):
        mock()
    assert isinstance(mock.outcomes[0], ValueError)


async def test_async_mock_awaits_coroutine_behavior() -> None:
    async def behavior(text: str) -> str:
        await asyncio.sleep(0)
        return f"echo: {text}"

    mock = AsyncMock()
    script(mock, behavior)

    assert await mock("hi") == "echo: hi"
    assert mock.outcomes == ["echo: hi"]
    assert mock.await_args_list[0].args == ("hi",)


async def test_async_behavior_raising_is_recorded_and_propagates() -> None:
    async def behavior() -> str:
        raise RuntimeError("async boom")

    mock = AsyncMock()
    script(mock, behavior)

    with pytest.raises(RuntimeError):
        await mock()
    assert isinstance(mock.outcomes[0], RuntimeError)


async def test_in_flight_call_is_observable_while_behavior_awaits() -> None:
    gate = asyncio.Event()
    started = asyncio.Event()

    async def behavior() -> str:
        started.set()
        await gate.wait()
        return "done"

    mock = AsyncMock()
    script(mock, behavior)

    task = asyncio.create_task(mock())
    await started.wait()
    assert mock.await_count == 1
    assert mock.outcomes == []

    gate.set()
    assert await task == "done"
    assert mock.outcomes == ["done"]


async def test_sync_behavior_works_on_async_mock() -> None:
    mock = AsyncMock()
    script(mock, ["value"])

    assert await mock() == "value"
    assert mock.outcomes == ["value"]


async def test_async_generator_script_yields_one_item_per_call() -> None:
    async def behavior() -> AsyncIterator[str]:
        yield "a"
        yield "b"

    mock = AsyncMock()
    script(mock, behavior)

    assert await mock() == "a"
    assert await mock() == "b"
    with pytest.raises(ScriptExhausted):
        await mock()
    assert mock.outcomes[:2] == ["a", "b"]
    assert isinstance(mock.outcomes[2], ScriptExhausted)


async def test_async_generator_script_awaits_only_before_first_yield() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def behavior() -> AsyncIterator[str]:
        started.set()
        await release.wait()
        yield "first"
        yield "second"

    mock = AsyncMock()
    script(mock, behavior)

    first = asyncio.create_task(mock())
    await started.wait()
    assert mock.outcomes == []

    release.set()
    assert await first == "first"
    # No second release: the generator resumes straight after the first
    # yield, so the await before it has already run once.
    assert await mock() == "second"
    assert mock.outcomes == ["first", "second"]


def test_sync_generator_script_yields_one_item_per_call() -> None:
    def behavior() -> Iterator[str]:
        yield "a"
        yield "b"

    mock = Mock()
    script(mock, behavior)

    assert mock() == "a"
    assert mock() == "b"
    with pytest.raises(ScriptExhausted):
        mock()
    assert mock.outcomes[:2] == ["a", "b"]
    assert isinstance(mock.outcomes[2], ScriptExhausted)


async def test_generator_script_raises_yielded_exceptions_per_convention() -> None:
    async def behavior() -> AsyncIterator[object]:
        yield ValueError
        yield RuntimeError("boom")
        yield "after"

    mock = AsyncMock()
    script(mock, behavior)

    with pytest.raises(ValueError):
        await mock()
    with pytest.raises(RuntimeError):
        await mock()
    assert await mock() == "after"
    assert mock.outcomes[0] is ValueError
    assert isinstance(mock.outcomes[1], RuntimeError)
    assert mock.outcomes[2] == "after"


async def test_async_generator_script_body_raise_is_recorded_and_propagates() -> None:
    async def behavior() -> AsyncIterator[str]:
        yield "a"
        raise RuntimeError("generator boom")

    mock = AsyncMock()
    script(mock, behavior)

    assert await mock() == "a"
    with pytest.raises(RuntimeError):
        await mock()
    assert mock.outcomes[0] == "a"
    assert isinstance(mock.outcomes[1], RuntimeError)


async def test_generator_script_passes_first_calls_args_to_the_generator() -> None:
    received: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def behavior(*args: object, **kwargs: object) -> AsyncIterator[str]:
        received.append((args, kwargs))
        yield "done"

    mock = AsyncMock()
    script(mock, behavior)

    assert await mock("x", key=1) == "done"
    assert await mock("ignored") == "done"
    assert received == [(("x",), {"key": 1})]
