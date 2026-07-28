from enum import StrEnum

from pydantic import BaseModel


class Event[TEventType: StrEnum](BaseModel):
    type: TEventType
