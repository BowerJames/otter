from pydantic import BaseModel

from .apis import KnownApis
from .providers import KnownProviders


class ProviderModelOption(BaseModel):
    model: str
    provider: KnownProviders
    api: KnownApis
    api_key: str | None
