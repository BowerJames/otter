"""Mutable controller state: the idle/busy latch and the closing flag.

A :class:`State` is the small mutable scratch pad a
:class:`~otter_ai_core.model_controller.ModelController` reads and writes while
it drives a :data:`~otter_ai_core.model_connection.ModelConnectionClient`:

* :attr:`is_idle` — an :class:`asyncio.Event` acting as the idle/busy latch.
  The controller starts **idle** (the event is set in :meth:`__post_init__`),
  flips to busy (:meth:`set_busy`) when a ``response.create`` is pushed, and
  back to idle (:meth:`set_idle`) when the matching ``response.done`` arrives.
  Idle is an :class:`~asyncio.Event` (not a plain ``bool``) so a consumer can
  ``await state.is_idle.wait()`` / :meth:`State.is_idle.wait`-via-controller
  for generation completion.
* :attr:`is_closing` — a ``bool`` flipped by the controller's
  :meth:`~otter_ai_core.model_controller.ModelController.close`. Once ``True``
  the controller rejects new commands (``generate`` / ``add_message`` /
  ``abort`` / ``compact`` / ``branch``); teardown has begun. It is a plain
  ``bool`` (not an :class:`~asyncio.Event`) because nothing awaits the closed transition —
  :meth:`~otter_ai_core.model_controller.ModelController.aclose` awaits the
  controller's run task directly for completion.

The two fields are deliberately separate concerns (idle/busy is *event-driven*;
closing is *command-driven*), kept together because they are the controller's
complete mutable state.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass(slots=True)
class State:
    """The mutable state of a :class:`ModelController`.

    ``_is_idle`` starts **set** (a fresh controller is idle and ready to
    generate). ``_is_closing`` starts ``False`` and is flipped once
    :meth:`~otter_ai_core.model_controller.ModelController.close` begins
    teardown.
    """

    _is_idle: asyncio.Event = field(default_factory=asyncio.Event)
    _is_closing: bool = False

    def __post_init__(self) -> None:
        # A fresh controller is idle: a ``generate()`` must be the first usable
        # command. ``asyncio.Event()`` starts unset (busy), so set it here.
        self._is_idle.set()

    @property
    def is_idle(self) -> asyncio.Event:
        """The idle/busy latch. Set when idle; cleared when a response is in flight."""
        return self._is_idle

    @property
    def is_closing(self) -> bool:
        """``True`` once teardown has begun (commands are then rejected)."""
        return self._is_closing

    def set_idle(self) -> None:
        """Mark the controller idle (the current generation finished)."""
        self._is_idle.set()

    def set_busy(self) -> None:
        """Mark the controller busy (a generation is now in progress)."""
        self._is_idle.clear()

    def begin_closing(self) -> None:
        """Mark teardown begun. Idempotent; subsequent commands are rejected."""
        self._is_closing = True

    async def wait_for_idle(self) -> None:
        await self._is_idle.wait()
