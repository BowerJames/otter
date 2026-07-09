"""In-memory steering / follow-up message queues.

Direct port of pi's ``PendingMessageQueue``. Two instances live on an
:class:`~otter_ai_agent.Agent`:

* **steering** — drained after each turn's tool execution, before the next
  ``create_response`` (inject a user item mid-run to "steer" the agent).
* **follow-up** — drained when the agent would otherwise stop (no tool calls,
  no steering), to continue with another turn.

Drain semantics are governed by :data:`QueueMode`:

* ``"all"`` — drain every queued item at a drain point.
* ``"one-at-a-time"`` — drain only the oldest item, leaving the rest queued for
  the next drain point.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal

from otter_ai_core.context import UserMessage

QueueMode = Literal["all", "one-at-a-time"]
"""Controls how many queued items a single drain removes."""


class PendingMessageQueue:
    """A small FIFO of :class:`UserMessage`\\ s with mode-aware draining."""

    _messages: list[UserMessage]
    mode: QueueMode

    def __init__(self, mode: QueueMode = "one-at-a-time") -> None:
        self.mode = mode
        self._messages = []

    def enqueue(self, message: UserMessage) -> None:
        self._messages.append(message)

    def has_items(self) -> bool:
        return bool(self._messages)

    def drain(self) -> list[UserMessage]:
        """Remove and return items according to :attr:`mode`.

        ``"all"`` returns every queued item; ``"one-at-a-time"`` returns just
        the oldest, leaving the rest queued.
        """
        if not self._messages:
            return []
        if self.mode == "all":
            drained = list(self._messages)
            self._messages = []
            return drained

        first = self._messages[0]
        self._messages = self._messages[1:]
        return [first]

    def peek(self) -> Iterator[UserMessage]:
        """Iterate queued items without removing them (for introspection)."""
        return iter(list(self._messages))

    def clear(self) -> None:
        self._messages = []
