import asyncio
from collections.abc import Callable

import pytest

from ..conversation import AssistantMessage, TextContent, ThinkingContent
from .signature import Model


class ModelConformanceSuite:
    @pytest.fixture
    def make_model(self) -> Callable[[], Model]:
        raise NotImplementedError("conformance suite requires a make_model fixture")

    @pytest.fixture
    def make_tool_calling_model(self) -> Callable[[], Model] | None:
        return None

    @pytest.fixture
    def make_failing_model(self) -> Callable[[], Model] | None:
        return None

    @pytest.fixture
    def make_gated_model(self) -> Callable[[], tuple[Model, asyncio.Event]] | None:
        return None

    async def test_methods_rejected_before_enter(self, make_model: Callable[[], Model]) -> None:
        model = make_model()
        with pytest.raises(RuntimeError):
            await model.add_user_message("hello")
        with pytest.raises(RuntimeError):
            await model.add_tool_result_message("call-1", "result")
        with pytest.raises(RuntimeError):
            await model.generate()

    async def test_methods_rejected_after_exit(self, make_model: Callable[[], Model]) -> None:
        model = make_model()
        async with model:
            await model.add_user_message("hello")
        with pytest.raises(RuntimeError):
            await model.add_user_message("again")
        with pytest.raises(RuntimeError):
            await model.add_tool_result_message("call-1", "result")
        with pytest.raises(RuntimeError):
            await model.generate()

    async def test_exit_does_not_suppress_exceptions(self, make_model: Callable[[], Model]) -> None:
        class Boom(Exception): ...

        model = make_model()
        with pytest.raises(Boom):
            async with model:
                raise Boom()

    async def test_session_is_single_use(self, make_model: Callable[[], Model]) -> None:
        model = make_model()
        async with model:
            await model.add_user_message("hello")
        with pytest.raises(RuntimeError):
            await model.__aenter__()

    async def test_add_user_message_echo(self, make_model: Callable[[], Model]) -> None:
        model = make_model()
        async with model:
            message = await model.add_user_message("hello")
        assert message.role == "user"
        assert message.content == [TextContent(text="hello")]
        assert message.id

    async def test_add_tool_result_message_echo(self, make_model: Callable[[], Model]) -> None:
        model = make_model()
        async with model:
            message = await model.add_tool_result_message("call-abc-123", "the result")
        assert message.role == "tool_result"
        assert message.tool_call_id == "call-abc-123"
        assert message.content == [TextContent(text="the result")]
        assert message.id

    async def test_message_ids_unique_within_session(self, make_model: Callable[[], Model]) -> None:
        model = make_model()
        async with model:
            user = await model.add_user_message("hello")
            tool_result = await model.add_tool_result_message("call-1", "result")
            assistant = await model.generate()
            follow_up = await model.add_user_message("again")
        ids = [user.id, tool_result.id, assistant.id, follow_up.id]
        assert len(set(ids)) == len(ids)

    async def test_generate_returns_valid_assistant_message(
        self, make_model: Callable[[], Model]
    ) -> None:
        model = make_model()
        async with model:
            await model.add_user_message("hello")
            message = await model.generate()
        assert message.role == "assistant"
        for item in message.content:
            assert isinstance(item, ThinkingContent | TextContent)
        if message.stop_reason == "final_response":
            assert message.content

    async def test_stop_reason_matches_tool_calls(self, make_model: Callable[[], Model]) -> None:
        model = make_model()
        async with model:
            await model.add_user_message("hello")
            message = await model.generate()
        if message.tool_calls:
            assert message.stop_reason == "tool_call"
        else:
            assert message.stop_reason == "final_response"

    async def test_tool_call_ids_unique(
        self, make_tool_calling_model: Callable[[], Model] | None
    ) -> None:
        if make_tool_calling_model is None:
            pytest.skip("adapter does not provide a tool-calling model factory")
        model = make_tool_calling_model()
        async with model:
            await model.add_user_message("please use the tool")
            first = await model.generate()
        assert first.tool_calls
        ids = [call.id for call in first.tool_calls]
        assert len(set(ids)) == len(ids)

    async def test_tool_round_trip_cycle(
        self, make_tool_calling_model: Callable[[], Model] | None
    ) -> None:
        if make_tool_calling_model is None:
            pytest.skip("adapter does not provide a tool-calling model factory")
        model = make_tool_calling_model()
        async with model:
            await model.add_user_message("please use the tool")
            first = await model.generate()
            first_ids = {call.id for call in first.tool_calls}
            for call in first.tool_calls:
                await model.add_tool_result_message(call.id, f"result for {call.tool_name}")
            second = await model.generate()
        assert second.role == "assistant"
        assert (second.stop_reason == "tool_call") == bool(second.tool_calls)
        assert not (first_ids & {call.id for call in second.tool_calls})

    async def test_generate_failure_propagates(
        self, make_failing_model: Callable[[], Model] | None
    ) -> None:
        if make_failing_model is None:
            pytest.skip("adapter does not provide a failing model factory")
        model = make_failing_model()
        async with model:
            try:
                await model.generate()
            except Exception:
                pass
            else:
                pytest.fail("generate() must propagate failures as exceptions")

    async def test_overlapping_generate_rejected(
        self, make_gated_model: Callable[[], tuple[Model, asyncio.Event]] | None
    ) -> None:
        if make_gated_model is None:
            pytest.skip("adapter does not provide a gated model factory")
        model, release = make_gated_model()
        async with model:
            first: asyncio.Future[AssistantMessage] = asyncio.ensure_future(model.generate())
            await asyncio.sleep(0)
            try:
                with pytest.raises(RuntimeError):
                    await model.generate()
            finally:
                release.set()
                await first
