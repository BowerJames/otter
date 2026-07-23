"""Otter AI logging — stdlib ``logging`` configured for the wiki conventions.

This package configures the standard-library :mod:`logging` module for the
monorepo's logging conventions (see the coding wiki under ``/logging/`` and
``/python/logging.md``):

* **Line format** — ``<timestamp_utc> <level> <message>`` (ISO-8601 UTC), e.g.
  ``2026-07-09T10:56:29Z INFO user 42 authenticated``. When context is bound via
  :func:`logging_context`, a trailing ``key=value …`` suffix is appended **after**
  the message; it is absent outside any scope, so context-less lines are
  byte-identical to the core-fields baseline. Pass ``format="json"`` to
  :func:`configure_logging` to render each line instead as a single-line JSON
  object with context fields as top-level keys.
* **Stream routing** — ``DEBUG``/``INFO``/``WARNING`` → ``stdout``, ``ERROR``
  → ``stderr`` (stderr only; never mirrored). ``ERROR`` is the alertable
  channel.
* **Level** — driven by the ``LOG_LEVEL`` environment variable (one of
  ``DEBUG``/``INFO``/``WARNING``/``ERROR``), defaulting to :data:`DEFAULT_LEVEL`
  (``INFO``); an explicit argument to :func:`configure_logging` takes
  precedence over the environment.

The canonical level set is four levels; ``CRITICAL`` is intentionally rejected
(do not emit above ``ERROR`` from our own code — the stderr handler's ``ERROR``
floor still catches a library's stray ``CRITICAL`` and routes it to stderr
alongside ``ERROR``).

Application code calls :func:`configure_logging` once at startup; libraries and
modules obtain a logger with the stdlib idiom ``logging.getLogger(__name__)``.
:func:`configure_logging` is **idempotent**: a repeat call updates the root
level but does not attach duplicate handlers, so it is safe to call from tests
or re-entrant entry points.

**Scoped structured context.** :func:`logging_context` binds arbitrary
structured fields (a session/request ID, a user ID, a hook name, …) to the
current scope for the lifetime of a block; every log line emitted within the
block carries them, written **before** the reserved core fields so a caller
cannot clobber ``level`` / ``time`` / ``msg`` / ``traceback``. Fields merge on
nesting (copy-on-write) and unwind cleanly on exit; the capability propagates
across ``asyncio`` tasks with no per-call-site plumbing. See
:mod:`otter_ai_logging.context` for the mechanism.

It depends on nothing but the standard library — no dependency on
:mod:`otter_ai_core`.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import UTC, datetime
from typing import Any, Literal

from otter_ai_logging.context import current_context_fields, logging_context

__version__ = "0.1.0"

#: Name of the environment variable that sets the root log level.
LOG_LEVEL_ENV_VAR = "LOG_LEVEL"

#: Root log level used when ``LOG_LEVEL`` is unset and no level is passed.
DEFAULT_LEVEL: int = logging.INFO

#: The canonical level set. ``CRITICAL`` is intentionally excluded — do not
#: emit above ``ERROR`` from our own code.
_LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}

#: Attribute used to tag handlers owned by this configurator (idempotency).
_HANDLER_TAG = "_otter_ai_logging_handler"


class _MaxLevelFilter(logging.Filter):
    """Keep only records at or below a maximum level.

    Caps the ``stdout`` handler at ``WARNING`` so ``ERROR`` is excluded (a
    handler's ``level`` is a minimum threshold, not an exact match, so a bare
    ``DEBUG``-floor handler would otherwise also emit ``ERROR``).
    """

    def __init__(self, max_level: int) -> None:
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


class TextFormatter(logging.Formatter):
    """``<ts> <level> <msg>`` plus a trailing ``key=value …`` suffix when
    context is bound.

    Reserved core fields stay positional (a caller cannot clobber them); the
    suffix is absent outside any :func:`logging_context` scope, so context-less
    lines are byte-identical to the core-fields formatter.
    :func:`logging.Logger.exception` still appends the traceback below the
    message line (handled by the base :meth:`~logging.Formatter.format`, which
    is not overridden).

    Only :meth:`~logging.Formatter.formatMessage` is overridden — that is the
    stdlib's intended hook for the *rendered line*. The base ``format()`` calls
    it, then **itself** appends ``exc_info`` (caching ``record.exc_text``) and
    ``stack_info`` (with the ``if s[-1:] != "\\n"`` guards). Appending the
    context suffix in ``formatMessage`` therefore lands it between the message
    and any traceback, exactly where the wiki's plain-text examples put it
    (``<timestamp_utc> <level> <message> key=value …``), for single- and
    multi-line messages — and leaves exception / stack rendering to the base
    class, so a context-less line is byte-identical to the pre-refactor output
    in every case.
    """

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
        self.converter = time.gmtime  # asctime defaults to local time

    def formatMessage(self, record: logging.LogRecord) -> str:
        line = super().formatMessage(record)
        fields = current_context_fields()
        if fields:
            line += " " + " ".join(f"{k}={v}" for k, v in fields.items())
        return line


class JsonFormatter(logging.Formatter):
    """Context fields as top-level JSON keys, written **before** the reserved
    core fields.

    A caller binding ``level`` / ``time`` / ``msg`` / ``traceback`` cannot
    clobber the reserved fields (they are written after the context update).
    ``default=str`` so a non-serialisable value (a :class:`~datetime.datetime`,
    a custom object) stringifies instead of crashing the log call; ``None``
    renders as ``null``. The ``traceback`` key is present when ``exc_info`` is
    set, so :func:`logging.Logger.exception` emits the trace end-to-end.

    JSON builds an entirely different output shape (a dict), so :meth:`format`
    is overridden to construct the payload directly (there is no ``_style`` line
    to amend). The ``time`` field carries millisecond precision.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {}
        payload.update(current_context_fields())  # context FIRST
        payload["level"] = record.levelname.lower()
        payload["time"] = self._format_time(record)
        payload["msg"] = record.getMessage()
        if record.exc_info:
            payload["traceback"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)  # default=str: never crash

    @staticmethod
    def _format_time(record: logging.LogRecord) -> str:
        dt = datetime.fromtimestamp(record.created, tz=UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}Z"


def _resolve_level(level: str | int | None) -> int:
    """Resolve a numeric level from an explicit value or ``LOG_LEVEL``.

    An explicit non-``None`` argument takes precedence over the environment;
    ``LOG_LEVEL`` is consulted only when ``level`` is ``None``; when both are
    absent :data:`DEFAULT_LEVEL` is returned. Only the four canonical levels
    are accepted — ``CRITICAL``/unknown values raise :class:`ValueError`.
    """
    if isinstance(level, int):
        if level not in _LEVELS.values():
            raise _invalid_level_error(level)
        return level
    if level is None:
        level = os.environ.get(LOG_LEVEL_ENV_VAR)
    if level is None:
        return DEFAULT_LEVEL
    name = level.upper()
    if name not in _LEVELS:
        raise _invalid_level_error(level)
    return _LEVELS[name]


def _invalid_level_error(value: str | int) -> ValueError:
    return ValueError(
        f"Unknown log level {value!r}; expected one of "
        f"{', '.join(_LEVELS)} (via the {LOG_LEVEL_ENV_VAR} environment "
        "variable or an explicit argument to configure_logging())."
    )


def configure_logging(
    level: str | int | None = None,
    *,
    format: Literal["json", "text"] = "text",
) -> None:
    """Configure the root logger per the wiki format and stream-routing rules.

    Two handlers are attached to the root logger:

    * a ``stdout`` handler (``DEBUG`` floor) capped at ``WARNING`` by a
      :class:`_MaxLevelFilter`, so it emits ``DEBUG``/``INFO``/``WARNING``; and
    * a ``stderr`` handler (``ERROR`` floor) — the alertable channel.

    Both share the selected ``formatter``: :class:`TextFormatter` by default
    (the ``<timestamp_utc> <level> <message>`` line plus a trailing
    ``key=value …`` suffix when context is bound), or :class:`JsonFormatter`
    when ``format="json"``.

    ``level`` sets the root logger's effective level: an explicit value wins,
    otherwise the ``LOG_LEVEL`` environment variable is read, otherwise
    :data:`DEFAULT_LEVEL` (``INFO``) is used.

    ``format`` is keyword-only — existing positional calls
    (``configure_logging("DEBUG")``) are unaffected — and selects the line
    rendering (``"text"`` default, ``"json"`` opt-in).

    Safe to call repeatedly (idempotent in effect): each call replaces any
    handlers previously attached by this function — and only those — with a
    fresh pair, so repeat calls never duplicate handlers and the configuration
    self-corrects if one of our handlers was removed elsewhere. Calling
    ``configure_logging(format="json")`` then
    ``configure_logging(format="text")`` swaps the formatter cleanly. Other
    handlers on the root logger are left untouched.
    """
    root = logging.getLogger()
    root.setLevel(_resolve_level(level))

    # Replace any handlers we previously attached (and only ours) with a fresh
    # pair: a repeat call never duplicates handlers, and the configuration
    # self-corrects if one of ours was removed elsewhere. Other handlers on the
    # root logger are left untouched.
    root.handlers = [
        handler for handler in root.handlers if not getattr(handler, _HANDLER_TAG, False)
    ]

    formatter = JsonFormatter() if format == "json" else TextFormatter()

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.addFilter(_MaxLevelFilter(logging.WARNING))
    stdout_handler.setFormatter(formatter)
    setattr(stdout_handler, _HANDLER_TAG, True)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    stderr_handler.setFormatter(formatter)
    setattr(stderr_handler, _HANDLER_TAG, True)

    root.addHandler(stdout_handler)
    root.addHandler(stderr_handler)


__all__ = [
    "configure_logging",
    "logging_context",
    "current_context_fields",
    "TextFormatter",
    "JsonFormatter",
    "DEFAULT_LEVEL",
    "LOG_LEVEL_ENV_VAR",
    "__version__",
]
