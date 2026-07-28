from __future__ import annotations

from pydantic import BaseModel

from .apis import KnownApis
from .providers import KnownProviders
from .thinking_level import ThinkingLevel


class ProviderModelOption(BaseModel):
    model: str
    provider: KnownProviders
    api: KnownApis
    api_key: str | None = None
    thinking_level: ThinkingLevel = ThinkingLevel.Low
