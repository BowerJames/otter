"""Tests for :func:`otter_ai_logging.configure_logging`.

Asserts the wiki conventions: the ``<timestamp_utc> <level> <message>`` UTC
format, the DEBUG–WARNING → stdout / ERROR → stderr routing, level resolution
from the ``LOG_LEVEL`` environment variable (default ``INFO``), the canonical
four-level set (``CRITICAL``/unknown rejected), and idempotency.

Output capture uses ``capfd`` (file-descriptor level) rather than ``capsys``:
the :mod:`logging` handlers write to ``sys.stdout``/``sys.stderr`` whose stream
*objects* are bound at :func:`~otter_ai_logging.configure_logging` time, and
``capfd`` captures at the fd level independent of those object identities,
sidestepping both the stream-binding timing issue and pytest's own logging
plugin.
"""

from __future__ import annotations

import calendar
import json
import logging
import re
import sys
import time
from datetime import datetime

import pytest

from otter_ai_logging import (
    _HANDLER_TAG,  # implementation detail under test
    LOG_LEVEL_ENV_VAR,
    JsonFormatter,
    TextFormatter,
    _MaxLevelFilter,  # implementation detail under test
    configure_logging,
    logging_context,
)

_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) (DEBUG|INFO|WARNING|ERROR) .*$")


def _emit_all(log: logging.Logger) -> None:
    """Emit one record at each canonical level."""
    log.debug("debug message")
    log.info("info %d", 7)
    log.warning("warning message")
    log.error("error message")


def _record(level: int) -> logging.LogRecord:
    return logging.LogRecord("x", level, "", 0, "", (), None)


# --------------------------------------------------------------------------- #
# Level resolution
# --------------------------------------------------------------------------- #


def test_default_level_is_info() -> None:
    configure_logging()
    assert logging.getLogger().level == logging.INFO


def test_env_var_sets_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LOG_LEVEL_ENV_VAR, "WARNING")
    configure_logging()
    assert logging.getLogger().level == logging.WARNING


def test_env_var_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LOG_LEVEL_ENV_VAR, "debug")
    configure_logging()
    assert logging.getLogger().level == logging.DEBUG


def test_explicit_level_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LOG_LEVEL_ENV_VAR, "ERROR")
    configure_logging("DEBUG")
    assert logging.getLogger().level == logging.DEBUG


def test_explicit_int_level_accepted() -> None:
    configure_logging(logging.WARNING)
    assert logging.getLogger().level == logging.WARNING


def test_invalid_env_level_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LOG_LEVEL_ENV_VAR, "BOGUS")
    with pytest.raises(ValueError, match="Unknown log level"):
        configure_logging()


def test_critical_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown log level"):
        configure_logging("CRITICAL")


def test_non_canonical_int_rejected() -> None:
    # CRITICAL's numeric value is outside the canonical set.
    with pytest.raises(ValueError, match="Unknown log level"):
        configure_logging(logging.CRITICAL)


# --------------------------------------------------------------------------- #
# Stream routing
# --------------------------------------------------------------------------- #


def test_routing_stdout_vs_stderr(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging("DEBUG")
    _emit_all(logging.getLogger("otter.test"))

    out, err = capfd.readouterr()
    assert "DEBUG debug message" in out
    assert "INFO info 7" in out
    assert "WARNING warning message" in out
    assert "ERROR" not in out  # stdout stays clean of error-grade output
    assert "ERROR error message" in err


def test_error_not_mirrored_to_stdout(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging("DEBUG")
    logging.getLogger("otter.test").error("boom")
    out, err = capfd.readouterr()
    assert "boom" in err
    assert "boom" not in out


def test_third_party_critical_routes_to_stderr(
    capfd: pytest.CaptureFixture[str],
) -> None:
    # A dependency's stray CRITICAL (above the canonical set our own code never
    # emits) must still land on stderr, never stdout — the stderr handler's
    # ERROR floor catches it and the stdout handler's _MaxLevelFilter rejects
    # it. This locks in the contract documented in the package docstring.
    configure_logging("DEBUG")
    logging.getLogger("third.party").critical("kaboom")
    out, err = capfd.readouterr()
    assert "kaboom" in err
    assert "kaboom" not in out


def test_level_gating_warning(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING")
    _emit_all(logging.getLogger("otter.test"))

    out, err = capfd.readouterr()
    assert "debug message" not in out  # DEBUG suppressed by root level
    assert "INFO" not in out
    assert "WARNING warning message" in out
    assert "ERROR error message" in err


# --------------------------------------------------------------------------- #
# Format (UTC)
# --------------------------------------------------------------------------- #


def test_line_format_utc(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    logging.getLogger("otter.test").info("hello %d", 42)

    out, _ = capfd.readouterr()
    line = out.strip()
    match = _LINE_RE.match(line)
    assert match is not None, f"line does not match UTC format: {line!r}"

    # Ends in Z and carries the message (args interpolated).
    assert match.group(1).endswith("Z")
    assert line.endswith("INFO hello 42")

    # Timestamp is the current UTC time, within a couple of minutes.
    # calendar.timegm treats the struct as UTC (time.mktime would apply a
    # local-timezone / DST correction and corrupt the comparison).
    parsed = time.strptime(match.group(1), "%Y-%m-%dT%H:%M:%SZ")
    delta = abs(calendar.timegm(parsed) - time.time())
    assert delta < 120


# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #


def _count_owned_handlers() -> int:
    """Count root-logger handlers tagged by ``configure_logging``.

    pytest's logging plugin attaches its own capture handlers to the root
    logger during a test, so the raw handler count is not a reliable signal of
    what ``configure_logging`` attached. Counting only tagged handlers isolates
    the idempotency contract from that pollution.
    """
    return sum(1 for h in logging.getLogger().handlers if getattr(h, _HANDLER_TAG, False))


def test_idempotent_no_duplicate_handlers() -> None:
    configure_logging("DEBUG")
    first = _count_owned_handlers()
    assert first == 2

    configure_logging("INFO")
    assert _count_owned_handlers() == first  # no duplicate handlers attached
    assert logging.getLogger().level == logging.INFO  # level still updated


def test_reconfigure_self_heals_after_partial_handler_removal() -> None:
    # If one of our handlers is removed elsewhere, a repeat call must restore
    # the full pair rather than short-circuiting on the surviving one.
    configure_logging("DEBUG")
    owned = [h for h in logging.getLogger().handlers if getattr(h, _HANDLER_TAG, False)]
    assert len(owned) == 2
    logging.getLogger().removeHandler(owned[0])
    assert _count_owned_handlers() == 1

    configure_logging("INFO")
    assert _count_owned_handlers() == 2  # full pair restored
    assert logging.getLogger().level == logging.INFO


def test_reconfigure_preserves_foreign_handlers() -> None:
    # Handlers we did not attach (e.g. an application's own handler) are left in
    # place across repeat calls.
    foreign = logging.StreamHandler()
    logging.getLogger().addHandler(foreign)

    configure_logging("DEBUG")
    assert foreign in logging.getLogger().handlers
    assert _count_owned_handlers() == 2

    configure_logging("INFO")
    assert foreign in logging.getLogger().handlers  # still there
    assert _count_owned_handlers() == 2


# --------------------------------------------------------------------------- #
# _MaxLevelFilter (unit)
# --------------------------------------------------------------------------- #


def test_max_level_filter_passes_at_or_below() -> None:
    filt = _MaxLevelFilter(logging.WARNING)
    assert filt.filter(_record(logging.DEBUG)) is True
    assert filt.filter(_record(logging.INFO)) is True
    assert filt.filter(_record(logging.WARNING)) is True


def test_max_level_filter_rejects_above() -> None:
    filt = _MaxLevelFilter(logging.WARNING)
    assert filt.filter(_record(logging.ERROR)) is False
    assert filt.filter(_record(logging.CRITICAL)) is False


# --------------------------------------------------------------------------- #
# Scoped context — text formatter (default)
# --------------------------------------------------------------------------- #


def test_text_no_suffix_outside_scope() -> None:
    # Byte-identical to the pre-refactor core-fields line when no context is
    # bound: no trailing ``key=value`` suffix.
    f = TextFormatter()
    record = logging.LogRecord("x", logging.INFO, "", 0, "hello %d", (42,), None)
    line = f.format(record)
    assert _LINE_RE.match(line) is not None
    assert line.endswith("INFO hello 42")


def test_text_context_suffix_when_bound(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    log = logging.getLogger("otter.test.ctx")
    with logging_context(session_id="call-123", user_id=42):
        log.info("authenticated")
    out, _ = capfd.readouterr()
    line = out.strip()
    # reserved fields stay positional (level precedes the message); the suffix
    # is absorbed by _LINE_RE's trailing ``.*$``.
    assert _LINE_RE.match(line) is not None
    assert line.endswith("INFO authenticated session_id=call-123 user_id=42")


def test_text_reserved_fields_stay_positional() -> None:
    # A context field named like a reserved core field renders as a trailing
    # ``key=value`` and never displaces the positional ``INFO``.
    f = TextFormatter()
    record = logging.LogRecord("x", logging.INFO, "", 0, "msg", (), None)
    with logging_context(level="bogus"):
        line = f.format(record)
    assert line.index(" INFO ") < line.index("level=bogus")


def test_text_logger_exception_appends_traceback(
    capfd: pytest.CaptureFixture[str],
) -> None:
    configure_logging("ERROR")
    log = logging.getLogger("otter.test.exc")
    try:
        raise ValueError("boom")
    except ValueError:
        log.exception("db refused")
    _, err = capfd.readouterr()
    assert "ERROR db refused" in err
    assert "Traceback (most recent call last):" in err
    assert "ValueError: boom" in err


def test_text_message_ending_in_newline_single_newline_before_trace() -> None:
    # The byte-identical edge case: a record whose message already ends in
    # ``\n`` paired with ``exc_info`` must still produce exactly ONE newline
    # before the traceback — never a blank line. Only ``formatMessage`` is
    # overridden, so the base ``format()``'s ``if s[-1:] != "\n"`` guard still
    # applies. (Reimplementing ``format()`` by hand would risk diverging here.)
    f = TextFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord("x", logging.ERROR, "", 0, "db refused\n", (), sys.exc_info())
    out = f.format(record)
    assert "ERROR db refused\n\nTraceback" not in out  # no blank line
    assert "ERROR db refused\nTraceback" in out  # exactly one newline


# --------------------------------------------------------------------------- #
# Scoped context — JSON formatter (opt-in)
# --------------------------------------------------------------------------- #


def _owned_handlers() -> list[logging.Handler]:
    return [h for h in logging.getLogger().handlers if getattr(h, _HANDLER_TAG, False)]


def test_json_context_before_reserved_fields() -> None:
    f = JsonFormatter()
    record = logging.LogRecord("x", logging.INFO, "", 0, "hello", (), None)
    with logging_context(session_id="call-123", user_id=42):
        payload = json.loads(f.format(record))
    keys = list(payload)
    # context keys are written FIRST, before level/time/msg.
    assert keys.index("session_id") < keys.index("level")
    assert keys.index("user_id") < keys.index("level")
    assert payload["level"] == "info"
    assert payload["msg"] == "hello"
    assert "traceback" not in payload


def test_json_reserved_keys_not_clobbered() -> None:
    # A caller binding a reserved name cannot clobber the reserved field: the
    # context update happens first, then the reserved keys overwrite it. With
    # exc_info set, all four reserved keys (level/time/msg/traceback) are
    # protected — the bogus context values do not survive.
    f = JsonFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord("x", logging.ERROR, "", 0, "real msg", (), sys.exc_info())
    with logging_context(level="bogus", time="bogus", msg="bogus", traceback="bogus"):
        payload = json.loads(f.format(record))
    assert payload["level"] == "error"
    assert payload["msg"] == "real msg"
    assert payload["time"] != "bogus"
    assert "Traceback (most recent call last):" in payload["traceback"]


def test_json_default_str_for_non_serialisable() -> None:
    # default=str so a non-serialisable value never crashes a log call.
    f = JsonFormatter()
    record = logging.LogRecord("x", logging.INFO, "", 0, "hi", (), None)
    when = datetime(2026, 7, 23, 20, 4, 5)
    with logging_context(when=when):
        payload = json.loads(f.format(record))
    assert payload["when"] == "2026-07-23 20:04:05"  # str(datetime)


def test_json_traceback_present_with_exc_info() -> None:
    f = JsonFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord("x", logging.ERROR, "", 0, "db refused", (), sys.exc_info())
    payload = json.loads(f.format(record))
    assert "Traceback (most recent call last):" in payload["traceback"]
    assert "ValueError: boom" in payload["traceback"]


def test_json_traceback_absent_without_exc_info() -> None:
    f = JsonFormatter()
    record = logging.LogRecord("x", logging.INFO, "", 0, "hi", (), None)
    payload = json.loads(f.format(record))
    assert "traceback" not in payload


def test_json_none_renders_as_null() -> None:
    f = JsonFormatter()
    record = logging.LogRecord("x", logging.INFO, "", 0, "hi", (), None)
    with logging_context(n=None):
        payload = json.loads(f.format(record))
    assert payload["n"] is None


def test_json_time_is_utc() -> None:
    f = JsonFormatter()
    record = logging.LogRecord("x", logging.INFO, "", 0, "hi", (), None)
    payload = json.loads(f.format(record))
    t = payload["time"]
    # millisecond precision, ISO-8601 UTC.
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", t)
    parsed = calendar.timegm(time.strptime(t[:19], "%Y-%m-%dT%H:%M:%S"))
    assert abs(parsed - time.time()) < 120


def test_json_routes_by_level(capfd: pytest.CaptureFixture[str]) -> None:
    # Context/format is orthogonal to routing: JSON lines still split across
    # stdout/stderr by level (the handlers are unchanged).
    configure_logging("DEBUG", format="json")
    log = logging.getLogger("otter.test.json")
    log.info("ok")
    log.error("boom")
    out, err = capfd.readouterr()
    assert json.loads(out.strip())["level"] == "info"
    assert json.loads(err.strip())["level"] == "error"


# --------------------------------------------------------------------------- #
# Formatter selection / swap (configure_logging format=)
# --------------------------------------------------------------------------- #


def test_default_format_is_text() -> None:
    configure_logging("DEBUG")
    assert all(isinstance(h.formatter, TextFormatter) for h in _owned_handlers())


def test_format_json_selects_json_formatter() -> None:
    configure_logging("DEBUG", format="json")
    assert all(isinstance(h.formatter, JsonFormatter) for h in _owned_handlers())


def test_format_swap_json_then_text() -> None:
    # format is keyword-only; swapping re-attaches the tagged pair with the new
    # formatter (idempotent pair count unchanged).
    configure_logging("DEBUG", format="json")
    assert len(_owned_handlers()) == 2
    assert all(isinstance(h.formatter, JsonFormatter) for h in _owned_handlers())

    configure_logging("INFO", format="text")
    assert len(_owned_handlers()) == 2
    assert all(isinstance(h.formatter, TextFormatter) for h in _owned_handlers())


def test_positional_level_call_unaffected() -> None:
    # ``format`` is keyword-only: an existing positional level call still works
    # and selects the text default.
    configure_logging("DEBUG")
    assert logging.getLogger().level == logging.DEBUG
    assert all(isinstance(h.formatter, TextFormatter) for h in _owned_handlers())
