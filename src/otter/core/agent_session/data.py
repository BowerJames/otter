"""What happens in an agent session."""

from dataclasses import dataclass

from otter.core.domain.messages import ContextEntry


@dataclass(frozen=True)
class Idle:
    """The session has come to rest: nothing is queued and the model is owed nothing."""


type SessionEvent = ContextEntry | Idle
"""One thing that happens in a session: an entry joins its conversation, or it comes to rest."""
