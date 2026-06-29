"""Smoke + conformance tests."""

from __future__ import annotations

from otter_ai_core.model_connection import ModelConnectionFn
from otter_ai_realtime import (
    RealtimeCost,
    RealtimeHooks,
    RealtimeModel,
    RealtimeModelOptions,
    RealtimeSessionConfig,
    __version__,
    create_realtime_model_connection,
)


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_public_surface_imports() -> None:
    # Constructing each public type exercises the data model.
    model = RealtimeModel(
        id="m",
        name="M",
        provider="openai",
        base_url="https://api.openai.com/v1",
        input_modalities=["text"],
        context_window=1000,
        max_tokens=100,
        cost=RealtimeCost(input=1.0, output=2.0, cache_read=0.0, cache_write=0.0),
    )
    options = RealtimeModelOptions(
        model=model, session_config=RealtimeSessionConfig(), hooks=RealtimeHooks()
    )
    assert options.model.id == "m"


def test_seam_is_a_model_connection_fn() -> None:
    # Structural conformance: assignability to the typed alias at runtime via
    # the generic's __class_getitem__ is not checked here (mypy/_typechecks.py
    # enforces it); this just asserts the alias resolves and the seam exists.
    alias = ModelConnectionFn[RealtimeModelOptions]
    assert alias is not None
    assert callable(create_realtime_model_connection)
