"""Scoped structured log context — a ``contextvars``-backed field bag.

A faithful port of the coding wiki's *Scoped log context in Python*
(``python/logging-context.md``): a process-wide :class:`~contextvars.ContextVar`
carries the current scope's structured fields, and
:func:`logging_context` binds fields for the lifetime of a block.

The field set is **caller-driven** (not predetermined) and every field is
rendered by the package's formatters (:mod:`otter_ai_logging`) as first-class
structured data, written **before** the reserved core fields, so a caller
cannot clobber ``level`` / ``time`` / ``msg`` / ``traceback``.

This module depends on nothing but the standard library — in particular it
imports nothing from :mod:`otter_ai_logging`, so there is no import cycle.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

#: The whole field bag for the current context. ``None`` outside any block.
#: Always rebound via :meth:`~contextvars.ContextVar.set` (never mutated in
#: place) so :meth:`~contextvars.Token.reset` unwinds nested blocks correctly —
#: see :func:`logging_context`.
_log_fields_var: ContextVar[dict[str, Any] | None] = ContextVar("log_fields", default=None)


def current_context_fields() -> dict[str, Any]:
    """The currently-bound context fields (a shallow copy).

    Consumed by the formatter on each record; returns ``{}`` outside any
    :func:`logging_context` block so non-session log lines stay clean. A shallow
    copy so the caller cannot mutate the stored bag.
    """
    value = _log_fields_var.get()
    return dict(value) if value else {}


@contextmanager
def logging_context(**fields: Any) -> Iterator[None]:
    """Bind arbitrary structured fields to the current context for the block.

    Fields merge with the parent block (**copy-on-write**: each
    :meth:`~contextvars.ContextVar.set` stores a fresh dict, the parent is never
    mutated in place); ``None`` values are kept (rendered as ``null``). Reset via
    the :class:`~contextvars.Token` unwinds nested blocks exactly, so child
    fields do not leak to siblings or the next request.

    Because the underlying primitive is :class:`~contextvars.ContextVar`,
    bindings propagate across :func:`asyncio.create_task` (asyncio copies
    context at task creation) with **no per-call-site plumbing** — bind once at a
    session/request boundary and every worker task inherits it. A bare thread or
    a :meth:`loop.run_in_executor <asyncio.AbstractEventLoop.run_in_executor>` /
    :class:`~concurrent.futures.ThreadPoolExecutor` does **not** inherit
    contextvars — that boundary needs
    :func:`contextvars.copy_context().run <contextvars.copy_context>` to
    preserve the bindings.
    """
    parent = _log_fields_var.get()
    merged: dict[str, Any] = {**(parent or {}), **fields}
    token: Token[dict[str, Any] | None] = _log_fields_var.set(merged)
    try:
        yield
    finally:
        _log_fields_var.reset(token)
