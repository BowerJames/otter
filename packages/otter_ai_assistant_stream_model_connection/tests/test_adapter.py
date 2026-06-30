"""Smoke + conformance tests."""

from __future__ import annotations

from otter_ai_assistant_stream_model_connection import (
    __version__,
    create_assistant_stream_model_connection,
)
from otter_ai_core.assistant_message_stream import AssistantMessageStreamFn
from otter_ai_core.model_connection import ModelConnectionFnBuilder


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_seam_is_callable() -> None:
    assert callable(create_assistant_stream_model_connection)


def test_seam_is_a_model_connection_fn_builder() -> None:
    # Structural conformance is enforced by mypy in ``_typechecks.py``; this
    # just asserts the alias resolves under the builder parameterisation and
    # the seam exists.
    alias = ModelConnectionFnBuilder[AssistantMessageStreamFn]
    assert alias is not None


def test_builder_returns_a_callable_producer() -> None:
    # The builder closes over the stream_fn and returns the bound producer,
    # which itself is callable with ``(context, abort)``.
    def fake_stream_fn(context: object, abort: object) -> object:
        return None

    connection_fn = create_assistant_stream_model_connection(fake_stream_fn)  # type: ignore[arg-type]
    assert callable(connection_fn)
