"""Shared dummy event for the generic runtime tests.

The surviving generic runtimes (``DefaultChannel`` and the test-local
in-memory connection pair) are parameterised over an arbitrary ``TEvent``.
These tests need only a small comparable stand-in with a ``type``
discriminator + payload — not a real protocol event — so they do not depend
on any domain event family.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class DummyEventType(StrEnum):
    """The ``type`` discriminator of a :class:`DummyEvent`."""

    START = "start"
    UPDATE = "update"
    DONE = "done"


class DummyEvent(BaseModel):
    """Minimal comparable event used as ``TEvent`` in the generic-runtime tests."""

    type: DummyEventType
    payload: str = ""


def dummy_events() -> list[DummyEvent]:
    """A small ordered list of dummy events ending in a ``DONE`` terminal."""
    return [
        DummyEvent(type=DummyEventType.START, payload="s"),
        DummyEvent(type=DummyEventType.UPDATE, payload="u"),
        DummyEvent(type=DummyEventType.DONE, payload="d"),
    ]
