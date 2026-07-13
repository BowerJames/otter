"""Otter AI logging — stdlib ``logging`` configured for the wiki conventions.

This package configures the standard-library :mod:`logging` module for the
monorepo's logging conventions (see the coding wiki under ``/logging/`` and
``/python/logging.md``):

* **Line format** — ``<timestamp_utc> <level> <message>`` (ISO-8601 UTC), e.g.
  ``2026-07-09T10:56:29Z INFO user 42 authenticated``.
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

It depends on nothing but the standard library — no dependency on
:mod:`otter_ai_core`.
"""

from __future__ import annotations

import logging
import os
import sys
import time

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


def _utc_formatter() -> logging.Formatter:
    """The ``<timestamp_utc> <level> <message>`` formatter, in UTC."""
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    formatter.converter = time.gmtime  # asctime defaults to local time
    return formatter


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


def configure_logging(level: str | int | None = None) -> None:
    """Configure the root logger per the wiki format and stream-routing rules.

    Two handlers are attached to the root logger:

    * a ``stdout`` handler (``DEBUG`` floor) capped at ``WARNING`` by a
      :class:`_MaxLevelFilter`, so it emits ``DEBUG``/``INFO``/``WARNING``; and
    * a ``stderr`` handler (``ERROR`` floor) — the alertable channel.

    Both share the UTC ``<timestamp_utc> <level> <message>`` formatter.

    ``level`` sets the root logger's effective level: an explicit value wins,
    otherwise the ``LOG_LEVEL`` environment variable is read, otherwise
    :data:`DEFAULT_LEVEL` (``INFO``) is used.

    Safe to call repeatedly (idempotent in effect): each call replaces any
    handlers previously attached by this function — and only those — with a
    fresh pair, so repeat calls never duplicate handlers and the configuration
    self-corrects if one of our handlers was removed elsewhere. Other handlers
    on the root logger are left untouched.
    """
    root = logging.getLogger()
    root.setLevel(_resolve_level(level))

    # Replace any handlers we previously attached (and only ours) with a fresh
    # pair: a repeat call never duplicates handlers, and the configuration
    # self-corrects if one of ours was removed elsewhere. Other handlers on the
    # root logger are left untouched.
    root.handlers = [
        handler
        for handler in root.handlers
        if not getattr(handler, _HANDLER_TAG, False)
    ]

    formatter = _utc_formatter()

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
    "DEFAULT_LEVEL",
    "LOG_LEVEL_ENV_VAR",
    "__version__",
]
