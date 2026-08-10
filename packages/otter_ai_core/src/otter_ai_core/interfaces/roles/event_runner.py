from typing import Protocol

from ..capabilities.emitter import Emitter
from ..capabilities.subscribable import Subscribable
from ..capabilities.task_runner import TaskRunner


class EventRunner(Subscribable, Emitter, TaskRunner, Protocol):
    def register(
        self, hook_name: str, event_trigger_type: type[object], event_response_type: type[object]
    ) -> None: ...
