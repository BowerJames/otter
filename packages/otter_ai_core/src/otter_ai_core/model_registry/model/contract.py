from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager

from .signature import EnterableModel

type ModelContractCheck = Callable[[ModelConstructor], Awaitable[None]]
type ModelConstructor = Callable[[], EnterableModel]


@contextmanager
def _raises_runtime_error() -> Iterator[None]:
    try:
        yield
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError, none was raised")


@contextmanager
def _propagates(exc_type: type[BaseException]) -> Iterator[None]:
    try:
        yield
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__} to propagate, it did not")


async def check_methods_gated_by_session_lifecycle(make_model: ModelConstructor) -> None:
    model = make_model()
    with _raises_runtime_error():
        await model.add_user_message("hello")
    with _raises_runtime_error():
        await model.add_tool_result_message("tool-call-1", "result")
    with _raises_runtime_error():
        await model.generate()

    async with model:
        await model.add_user_message("hello")
        await model.add_tool_result_message("tool-call-1", "result")
        await model.generate()

    with _raises_runtime_error():
        await model.add_user_message("hello")
    with _raises_runtime_error():
        await model.add_tool_result_message("tool-call-1", "result")
    with _raises_runtime_error():
        await model.generate()


async def check_session_cannot_be_reentered(make_model: ModelConstructor) -> None:
    model = make_model()
    async with model:
        pass
    with _raises_runtime_error():
        await model.__aenter__()


async def check_exit_does_not_suppress_exceptions(make_model: ModelConstructor) -> None:
    model = make_model()
    with _propagates(ZeroDivisionError):
        async with model:
            await model.add_user_message("hello")
            raise ZeroDivisionError


MODEL_CONTRACT_CHECKS: list[ModelContractCheck] = [
    check_methods_gated_by_session_lifecycle,
    check_session_cannot_be_reentered,
    check_exit_does_not_suppress_exceptions,
]
