"""Scripted mocks for testing at abstraction seams.

Builds on ``unittest.mock``: :func:`script` upgrades a mock method's
``side_effect`` with a recorded outcomes log, standardising how tests
script behaviour and observe results for any abstraction's mocks.
"""

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import TypeVar, cast, overload
from unittest.mock import AsyncMock, Mock

T = TypeVar("T")

type ScriptOutcome[T] = T | BaseException | type[BaseException]

type ScriptedBehavior[T] = (
    Iterable[ScriptOutcome[T]]
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
    - a bare exception class or instance, raised on every call;
    - a callable receiving the mocked call's arguments: a sync callable's
      return value is returned, a coroutine function is awaited and its
      result returned, and whatever the callable raises propagates.

    Every completed call (or await) appends its result to
    ``mock.outcomes``, index-aligned with ``mock.call_args_list`` /
    ``mock.await_args_list``: an item that is an exception (class or
    instance) was raised, anything else was returned. An in-flight call
    is therefore observable as ``len(call_args_list) - len(outcomes)``.
    When an iterable script runs dry, :class:`ScriptExhausted` (an
    ``AssertionError``) is raised and recorded first, so the log stays
    complete.

    Scripting a mock again replaces its behaviour and starts a fresh
    ``outcomes`` list.

    Returns ``mock`` for chaining.
    """
    outcomes: list[ScriptOutcome[T]] = []

    if callable(behavior) and not asyncio.iscoroutinefunction(behavior):
        sync_behavior = cast("Callable[..., T]", behavior)

        def from_callable(*args: object, **kwargs: object) -> object:
            try:
                result = sync_behavior(*args, **kwargs)
            except BaseException as exc:
                outcomes.append(exc)
                raise
            outcomes.append(result)
            return result

        consume: Callable[..., object] = from_callable

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
            outcomes.append(item)
            if isinstance(item, BaseException):
                raise item
            if isinstance(item, type) and issubclass(item, BaseException):
                raise item
            return item

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
