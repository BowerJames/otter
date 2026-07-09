"""Smoke test for the generic :data:`BuilderFn` type alias.

``BuilderFn`` is a zero-runtime PEP 695 type alias; this guards against
accidental removal and confirms a trivially-conforming options-binding
callable binds under a ``BuilderFn[...]`` annotation. (mypy is the real
enforcer of conformance.)
"""

from __future__ import annotations

from collections.abc import Callable

from otter_ai_core import BuilderFn


def _make_thing(options: int) -> str:
    return f"thing-{options}"


def test_builder_fn_is_imported() -> None:
    assert BuilderFn is not None


def test_builder_fn_callable_binds() -> None:
    fn: BuilderFn[int, str] = _make_thing
    assert isinstance(fn, Callable)  # type: ignore[arg-type]
    assert fn(7) == "thing-7"
