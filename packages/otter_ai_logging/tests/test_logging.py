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
import logging
import re
import time

import pytest

from otter_ai_logging import (
    _HANDLER_TAG,  # implementation detail under test
    LOG_LEVEL_ENV_VAR,
    _MaxLevelFilter,  # implementation detail under test
    configure_logging,
)

_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) (DEBUG|INFO|WARNING|ERROR) .*$"
)


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
    return sum(
        1 for h in logging.getLogger().handlers if getattr(h, _HANDLER_TAG, False)
    )


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
