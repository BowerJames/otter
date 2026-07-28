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
    def __init__(self, max_level: int) -> None:
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


class TextFormatter(logging.Formatter):
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
