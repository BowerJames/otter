from collections.abc import Awaitable, Callable

from .signature import Provider

# A ProviderFactory yields a fresh Provider. Checks arrange all state they
# need through the interface itself.
type ProviderFactory = Callable[[], Provider]
type ProviderContractCheck = Callable[[ProviderFactory], Awaitable[None]]

PROVIDER_CONTRACT_CHECKS: list[ProviderContractCheck] = []
