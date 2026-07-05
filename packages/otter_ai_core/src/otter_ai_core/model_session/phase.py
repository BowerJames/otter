from enum import StrEnum


class Phase(StrEnum):
    IDLE = "idle"
    WORKING = "working"
    ABORTING = "aborting"
