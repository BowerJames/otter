"""Shared test fixtures.

Restores the package to a clean built-in-only state before every test, so a
test that registers a custom provider/model/api-fn does not leak into others.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from otter_ai_assistant_provider_stream import reset


@pytest.fixture(autouse=True)
def _reset_registries() -> Iterator[None]:
    reset()
    yield
