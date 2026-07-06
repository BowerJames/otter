from dataclasses import dataclass

from .phase import Phase


@dataclass
class ModelStateMachine:
    phase: Phase = Phase.IDLE
    running: bool = True

    def set_idle(self) -> None:
        self.phase = Phase.IDLE

    def set_working(self) -> None:
        self.phase = Phase.WORKING

    def set_aborting(self) -> None:
        self.phase = Phase.ABORTING

    def close_connection(self) -> None:
        self.running = False
