"""Smoke test for the generic :data:`Hook` type alias.

``Hook`` is a zero-runtime PEP 695 type alias; this guards against accidental
removal and confirms it is usable as an async ``Callable``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from otter_ai_core import Hook


async def _sample_hook(_event: int) -> str:
    return "ok"


def test_hook_is_imported() -> None:
    assert Hook is not None


def test_hook_callback_is_callable() -> None:
    fn: Hook[int, str] = _sample_hook
    assert isinstance(fn, Callable)  # type: ignore[arg-type]


async def test_hook_return_is_awaitable() -> None:
    fn: Hook[int, str] = _sample_hook
    result = fn(1)
    assert isinstance(result, Awaitable)
    assert await result == "ok"
