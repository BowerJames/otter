"""Scripted mocks for testing at abstraction seams.

Builds on ``unittest.mock``: :func:`script` upgrades a mock method's
``side_effect`` with a recorded outcomes log, standardising how tests
script behaviour and observe results for any abstraction's mocks.
"""

import asyncio
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator
from typing import TypeVar, cast, overload
from unittest.mock import AsyncMock, Mock

T = TypeVar("T")

type ScriptOutcome[T] = T | BaseException | type[BaseException]

type ScriptedBehavior[T] = (
    Iterable[ScriptOutcome[T]]
    | Callable[..., AsyncIterator[T]]
    | Callable[..., Iterator[T]]
    | Callable[..., T | Awaitable[T]]
    | BaseException
    | type[BaseException]
)


class ScriptExhausted(AssertionError):
    """A scripted mock was called more times than its script allowed."""


@overload
def script[T](mock: Mock | AsyncMock, behavior: Iterable[ScriptOutcome[T]]) -> Mock | AsyncMock: ...


@overload
def script[T](
    mock: Mock | AsyncMock, behavior: Callable[..., AsyncIterator[T]]
) -> Mock | AsyncMock: ...


@overload
def script[T](mock: Mock | AsyncMock, behavior: Callable[..., Iterator[T]]) -> Mock | AsyncMock: ...


@overload
def script[T](
    mock: Mock | AsyncMock, behavior: Callable[..., Awaitable[T]]
) -> Mock | AsyncMock: ...


@overload
def script[T](mock: Mock | AsyncMock, behavior: Callable[..., T]) -> Mock | AsyncMock: ...


@overload
def script(
    mock: Mock | AsyncMock, behavior: BaseException | type[BaseException]
) -> Mock | AsyncMock: ...


def script[T](
    mock: Mock | AsyncMock,
    behavior: Iterable[ScriptOutcome[T]]
    | Callable[..., object]
    | BaseException
    | type[BaseException],
) -> Mock | AsyncMock:
    """Scripts ``mock`` from ``behavior`` and records what happens.

    ``behavior`` is one of:

    - an iterable of results, consumed in order: exception classes and
      instances are raised, every other item is returned (the unittest
      ``side_effect`` convention);
    - a generator function (sync or async): called once with the first
      mocked call's arguments, then advanced one step per call — the
      body runs lazily between calls (so it may await), each yielded
      item is returned under the iterable convention above, exhaustion
      raises and records :class:`ScriptExhausted`, and anything the
      body raises propagates and is recorded;
    - a bare exception class or instance, raised on every call;
    - a callable receiving the mocked call's arguments: a sync callable's
      return value is returned, a coroutine function is awaited and its
      result returned, and whatever the callable raises propagates.

    Every completed call (or await) appends its result to
    ``mock.outcomes``, index-aligned with ``mock.call_args_list`` /
    ``mock.await_args_list``: an item that is an exception (class or
    instance) was raised, anything else was returned. An in-flight call
    is therefore observable as ``len(call_args_list) - len(outcomes)``.
    When an iterable or generator script runs dry, :class:`ScriptExhausted`
    (an ``AssertionError``) is raised and recorded first, so the log stays
    complete.

    Scripting a mock again replaces its behaviour and starts a fresh
    ``outcomes`` list.

    Returns ``mock`` for chaining.
    """
    outcomes: list[ScriptOutcome[T]] = []
    consume: Callable[..., object]

    def settle(item: ScriptOutcome[T]) -> T:
        """Records ``item``, raising it when it scripts an exception."""
        outcomes.append(item)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, type) and issubclass(item, BaseException):
            raise item
        return cast("T", item)

    if inspect.isasyncgenfunction(behavior):
        async_generator = cast("Callable[..., AsyncIterator[T]]", behavior)
        async_steps: AsyncIterator[T] | None = None

        async def from_async_generator(*args: object, **kwargs: object) -> object:
            nonlocal async_steps
            if async_steps is None:
                async_steps = async_generator(*args, **kwargs)
            item: ScriptOutcome[T]
            try:
                item = await anext(async_steps)
            except StopAsyncIteration:
                item = ScriptExhausted(f"script for {mock!r} exhausted")
            except BaseException as error:
                outcomes.append(error)
                raise
            return settle(item)

        consume = from_async_generator

    elif inspect.isgeneratorfunction(behavior):
        sync_generator = cast("Callable[..., Iterator[T]]", behavior)
        sync_steps: Iterator[T] | None = None

        def from_sync_generator(*args: object, **kwargs: object) -> object:
            nonlocal sync_steps
            if sync_steps is None:
                sync_steps = sync_generator(*args, **kwargs)
            item: ScriptOutcome[T]
            try:
                item = next(sync_steps)
            except StopIteration:
                item = ScriptExhausted(f"script for {mock!r} exhausted")
            except BaseException as error:
                outcomes.append(error)
                raise
            return settle(item)

        consume = from_sync_generator

    elif callable(behavior) and not asyncio.iscoroutinefunction(behavior):
        sync_behavior = cast("Callable[..., T]", behavior)

        def from_callable(*args: object, **kwargs: object) -> object:
            try:
                result = sync_behavior(*args, **kwargs)
            except BaseException as exc:
                outcomes.append(exc)
                raise
            outcomes.append(result)
            return result

        consume = from_callable

    elif callable(behavior):
        async_behavior = cast("Callable[..., Awaitable[T]]", behavior)

        async def from_coroutine(*args: object, **kwargs: object) -> object:
            try:
                result = await async_behavior(*args, **kwargs)
            except BaseException as exc:
                outcomes.append(exc)
                raise
            outcomes.append(result)
            return result

        consume = from_coroutine

    elif isinstance(behavior, Iterable):
        items = iter(behavior)

        def from_iterable(*args: object, **kwargs: object) -> object:
            try:
                item = next(items)
            except StopIteration:
                item = ScriptExhausted(f"script for {mock!r} exhausted")
            return settle(item)

        consume = from_iterable

    else:
        exception = cast("BaseException | type[BaseException]", behavior)

        def from_fixed(*args: object, **kwargs: object) -> object:
            outcomes.append(exception)
            raise exception

        consume = from_fixed

    mock.side_effect = consume
    mock.outcomes = outcomes
    return mock
