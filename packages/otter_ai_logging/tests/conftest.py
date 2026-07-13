"""Shared fixtures for the otter-ai-logging test suite.

These fixtures are autouse and scoped to this package's tests only. They keep
each test isolated from global logging state (root-logger handlers) and from a
leaked ``LOG_LEVEL`` environment variable, so assertions about handler count,
level, and routing are deterministic.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from otter_ai_logging import LOG_LEVEL_ENV_VAR


@pytest.fixture(autouse=True)
def _isolate_root_logger() -> Iterator[None]:
    """Clear root-logger handlers around each test.

    :func:`otter_ai_logging.configure_logging` binds the ``stdout``/``stderr``
    stream objects at call time and tags the handlers it attaches; clearing
    handlers before each test means every test re-attaches fresh handlers
    (bound to that test's capture streams) and handler-count assertions start
    from zero.
    """
    root = logging.getLogger()
    root.handlers.clear()
    yield
    root.handlers.clear()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Remove any inherited ``LOG_LEVEL`` around each test."""
    monkeypatch.delenv(LOG_LEVEL_ENV_VAR, raising=False)
    yield
