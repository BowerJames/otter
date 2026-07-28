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
    value = _log_fields_var.get()
    return dict(value) if value else {}


@contextmanager
def logging_context(**fields: Any) -> Iterator[None]:
    parent = _log_fields_var.get()
    merged: dict[str, Any] = {**(parent or {}), **fields}
    token: Token[dict[str, Any] | None] = _log_fields_var.set(merged)
    try:
        yield
    finally:
        _log_fields_var.reset(token)
