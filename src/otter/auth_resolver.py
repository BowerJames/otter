"""How the API key for a model provider is found."""

import os
import re
from collections.abc import Callable, Mapping

type Provider = str
"""The name a provider is known by, such as "openai" or "zai"."""

type ApiKey = str

type AuthResolver = Callable[[Provider], ApiKey]
"""Returns the API key to use with a provider, or raises `MissingApiKeyError`."""


class MissingApiKeyError(LookupError):
    """No API key could be found for a provider."""


def create_environment_auth_resolver(environ: Mapping[str, str] = os.environ) -> AuthResolver:
    """Return an auth resolver that takes API keys from environment variables.

    A provider's key is read from `<PROVIDER>_API_KEY`: the provider's name in upper
    case, with anything that is not a letter or digit turned into an underscore, so
    "open-router" is read from `OPEN_ROUTER_API_KEY`. The variable is read each time a
    key is resolved. One that is unset or empty raises `MissingApiKeyError`, which names
    the variable to set. `environ` is where variables are looked up; leave it out to use
    the process environment.
    """

    def resolve(provider: Provider) -> ApiKey:
        variable = re.sub(r"[^A-Z0-9]", "_", provider.upper()) + "_API_KEY"
        key = environ.get(variable)
        if not key:
            raise MissingApiKeyError(f"no API key for provider {provider!r}: set {variable}")
        return key

    return resolve
