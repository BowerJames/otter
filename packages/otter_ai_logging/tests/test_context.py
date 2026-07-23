"""Tests for the scoped structured-context capability.

Asserts the wiki's *Scoped log context in Python* contract
(``python/logging-context.md``): a process-wide ``ContextVar`` carries the
current scope's field bag; :func:`logging_context` binds fields for the
lifetime of a block, merging on nesting (copy-on-write) and unwinding cleanly
on exit; :func:`current_context_fields` returns a shallow copy (``{}`` outside
any block); ``None`` passes through; bindings propagate across
``asyncio.create_task``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator

import pytest

from otter_ai_logging import (
    configure_logging,
    current_context_fields,
    logging_context,
)
from otter_ai_logging.context import _log_fields_var  # implementation detail under test


@pytest.fixture(autouse=True)
def _reset_context_var() -> Iterator[None]:
    """Reset the context var around each test.

    ``logging_context`` unwinds via ``finally: reset(token)``, so a passing test
    leaves the var at ``None``; this guards against a test that fails mid-block
    leaking fields into the next.
    """
    token = _log_fields_var.set(None)
    try:
        yield
    finally:
        _log_fields_var.reset(token)


# --------------------------------------------------------------------------- #
# current_context_fields reader
# --------------------------------------------------------------------------- #


def test_reader_empty_outside_any_block() -> None:
    assert current_context_fields() == {}


def test_reader_returns_a_shallow_copy() -> None:
    # The returned dict must be a copy: mutating it must not corrupt the stored
    # bag that the formatter reads.
    with logging_context(session_id="call-123"):
        fields = current_context_fields()
        fields["injected"] = "tamper"
        assert current_context_fields() == {"session_id": "call-123"}


# --------------------------------------------------------------------------- #
# Fields appear on / vanish from emitted lines
# --------------------------------------------------------------------------- #


def test_fields_appear_on_emitted_line(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    log = logging.getLogger("otter.test.context")
    with logging_context(session_id="call-123", user_id=42):
        log.info("authenticated")
    out, _ = capfd.readouterr()
    assert "INFO authenticated session_id=call-123 user_id=42" in out


def test_fields_absent_outside_the_block(capfd: pytest.CaptureFixture[str]) -> None:
    # "emit nothing extra outside any scope": a line emitted after the block
    # must carry no context suffix.
    configure_logging("INFO")
    log = logging.getLogger("otter.test.context")
    with logging_context(session_id="call-123"):
        log.info("inside")
    log.info("outside")
    out, _ = capfd.readouterr()
    inside, outside = out.strip().splitlines()
    assert "session_id=call-123" in inside
    assert "session_id" not in outside


# --------------------------------------------------------------------------- #
# Merge-on-nesting
# --------------------------------------------------------------------------- #


def test_child_inherits_and_overrides_parent() -> None:
    with logging_context(session_id="call-123", user_id=1):
        with logging_context(user_id=2, hook="tool"):
            assert current_context_fields() == {
                "session_id": "call-123",
                "user_id": 2,
                "hook": "tool",
            }
        # child's overrides/fields reverted; parent unaffected
        assert current_context_fields() == {"session_id": "call-123", "user_id": 1}


def test_child_adds_its_own_field() -> None:
    with logging_context(session_id="call-123"):
        with logging_context(span="a"):
            assert current_context_fields() == {"session_id": "call-123", "span": "a"}
        assert current_context_fields() == {"session_id": "call-123"}


# --------------------------------------------------------------------------- #
# Clean unwind / no leaks
# --------------------------------------------------------------------------- #


def test_sibling_blocks_do_not_leak() -> None:
    with logging_context(request="first"):
        assert current_context_fields() == {"request": "first"}
    assert current_context_fields() == {}  # nothing leaked past the block
    with logging_context(request="second"):
        assert current_context_fields() == {"request": "second"}
    assert current_context_fields() == {}


def test_copy_on_write_parent_not_mutated() -> None:
    # Copy-on-write is load-bearing: each set() must store a FRESH dict, never
    # mutating the parent in place — else the child's field would leak past the
    # block via the shared parent dict and reset() could not revert it.
    with logging_context(session_id="call-123"):
        parent_ref = _log_fields_var.get()
        with logging_context(child="x"):
            assert _log_fields_var.get() is not parent_ref  # fresh dict (COW)
        assert parent_ref == {"session_id": "call-123"}  # untouched
        assert "child" not in parent_ref


# --------------------------------------------------------------------------- #
# None passthrough
# --------------------------------------------------------------------------- #


def test_none_passes_through() -> None:
    with logging_context(n=None):
        assert current_context_fields() == {"n": None}


def test_inner_none_overrides_outer() -> None:
    with logging_context(v="outer"):
        with logging_context(v=None):
            assert current_context_fields() == {"v": None}
        assert current_context_fields() == {"v": "outer"}  # reset reverts


# --------------------------------------------------------------------------- #
# asyncio propagation
# --------------------------------------------------------------------------- #


def test_async_task_inherits_context() -> None:
    captured: list[dict[str, object]] = []

    async def worker() -> None:
        captured.append(current_context_fields())

    async def main() -> None:
        with logging_context(session_id="call-123"):
            # asyncio copies context at task creation, so the worker sees the
            # binding with no per-call-site plumbing.
            await asyncio.create_task(worker())

    asyncio.run(main())
    assert captured == [{"session_id": "call-123"}]
