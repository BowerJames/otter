from typing import Protocol

from .emitter import Emitter
from .subscribable import Subscribable
from .task_runner import TaskRunner


class EventRunner(Subscribable, Emitter, TaskRunner, Protocol):
    def register(
        self, hook_name: str, event_trigger_type: type[object], event_response_type: type[object]
    ) -> None: ...
