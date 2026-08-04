from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class UsageCost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: float
    output: float
    cache_read: float
    cache_write: float
    total: float


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: int
    output: int
    cache_read: int
    cache_write: int
    #: Optional split of ``cache_write`` written with long (1h) retention.
    #: Only some providers (e.g. Anthropic) report this split.
    cache_write_1h: int | None = None
    total_tokens: int
    cost: UsageCost
