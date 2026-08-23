from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager

from .signature import Provider

# A ProviderFactory yields a fresh Provider. Checks arrange all state they
# need through the interface itself.
type ProviderFactory = Callable[[], Provider]
type ProviderContractCheck = Callable[[ProviderFactory], Awaitable[None]]


@contextmanager
def _raises_runtime_error() -> Iterator[None]:
    try:
        yield
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError, none was raised")


async def check_factory_yields_fresh_models(make_provider: ProviderFactory) -> None:
    provider = make_provider()
    factory = provider.get_model_factory("some-model", "sk-test")
    first = factory("system prompt", [])
    second = factory("system prompt", [])

    async with first, second:
        await second.add_user_message("hello")
        await first.generate()

    with _raises_runtime_error():
        await first.add_user_message("hello")


PROVIDER_CONTRACT_CHECKS: list[ProviderContractCheck] = [
    check_factory_yields_fresh_models,
]
