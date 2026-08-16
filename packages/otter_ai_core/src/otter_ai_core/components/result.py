from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Ok[T]:
    value: T
    is_error: Literal[False] = False


@dataclass(frozen=True)
class Err[E: Exception]:
    value: E
    is_error: Literal[True] = True


type Result[T, E] = Ok[T] | Err[E]
