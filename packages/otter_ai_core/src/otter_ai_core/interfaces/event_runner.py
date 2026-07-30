from typing import Protocol

from .emitter import Emitter
from .subscribable import Subscribable


class EventRunner(Subscribable, Emitter, Protocol):
    def register(
        self, hook_name: str, event_trigger_type: type[object], event_response_type: type[object]
    ) -> None: ...
