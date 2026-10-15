"""Behaviour of the responses adapter, driven through the model's port and observed at a fake
endpoint.
"""

from json import JSONDecodeError

import pytest

from otter.core.domain.messages import (
    AssistantMessage,
    AudioPart,
    ContextEntry,
    ImagePart,
    ImageUrlPart,
    TextPart,
    ThinkingPart,
    ToolCall,
    ToolResultMessage,
    ToolSpec,
    UserMessage,
)
from otter.core.model import ModelInput, ModelPort
from otter.infrastructure.adapters.model.openai_responses import (
    ModelFailed,
    OpenAIResponsesAdapter,
)

from .adapters import FakeResponsesEndpoint, reasoning_item, text_item, tool_call_item

READ_FILE = ToolSpec(
    name="read_file",
    description="Read a file from disk.",
    parameters={"type": "object", "properties": {"path": {"type": "string"}}},
)
ASKS = UserMessage((TextPart("What is in my notes?"),))
ASKS_ON_THE_WIRE = {
    "role": "user",
    "content": [{"type": "input_text", "text": "What is in my notes?"}],
}


def asking(*context: ContextEntry, system: str | None = None) -> ModelInput:
    return ModelInput(system, (), context)


@pytest.fixture
def endpoint() -> FakeResponsesEndpoint:
    return FakeResponsesEndpoint()


@pytest.fixture
def adapter(endpoint: FakeResponsesEndpoint) -> ModelPort:
    return OpenAIResponsesAdapter(endpoint.client(), "gpt-5.1")


async def test_the_context_is_sent_to_the_model_it_was_made_for(
    endpoint: FakeResponsesEndpoint, adapter: ModelPort
) -> None:
    await adapter.generate(asking(ASKS))

    assert endpoint.request_bodies[0]["model"] == "gpt-5.1"
    assert endpoint.request_bodies[0]["input"] == [ASKS_ON_THE_WIRE]


async def test_the_system_prompt_is_sent_as_the_models_instructions(
    endpoint: FakeResponsesEndpoint, adapter: ModelPort
) -> None:
    await adapter.generate(asking(ASKS, system="Be brief."))

    assert endpoint.request_bodies[0]["instructions"] == "Be brief."


async def test_no_instructions_are_sent_without_a_system_prompt(
    endpoint: FakeResponsesEndpoint, adapter: ModelPort
) -> None:
    await adapter.generate(asking(ASKS))

    assert "instructions" not in endpoint.request_bodies[0]


async def test_the_provider_is_asked_to_keep_nothing_and_return_reasoning_that_can_be_sent_back(
    endpoint: FakeResponsesEndpoint, adapter: ModelPort
) -> None:
    await adapter.generate(asking(ASKS))

    assert endpoint.request_bodies[0]["store"] is False
    assert endpoint.request_bodies[0]["include"] == ["reasoning.encrypted_content"]


async def test_the_tools_are_offered_as_functions_held_to_no_strict_rules(
    endpoint: FakeResponsesEndpoint, adapter: ModelPort
) -> None:
    await adapter.generate(ModelInput(None, (READ_FILE,), (ASKS,)))

    assert endpoint.request_bodies[0]["tools"] == [
        {
            "type": "function",
            "name": "read_file",
            "description": "Read a file from disk.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            "strict": False,
        }
    ]


async def test_the_turn_holds_the_models_thinking_text_and_tool_calls_in_order(
    endpoint: FakeResponsesEndpoint, adapter: ModelPort
) -> None:
    endpoint.replies = [
        [
            reasoning_item(summary=[{"type": "summary_text", "text": "Check the notes."}]),
            text_item("Let me look."),
            tool_call_item("call_1", "read_file", '{"path": "notes.txt"}'),
        ]
    ]

    assert await adapter.generate(asking(ASKS)) == AssistantMessage(
        (
            ThinkingPart("Check the notes."),
            TextPart("Let me look."),
            ToolCall("call_1", "read_file", {"path": "notes.txt"}),
        )
    )


async def test_reasoning_shown_as_content_is_the_turns_thinking(
    endpoint: FakeResponsesEndpoint, adapter: ModelPort
) -> None:
    endpoint.replies = [
        [
            reasoning_item(content=[{"type": "reasoning_text", "text": "Two and two."}]),
            text_item("4"),
        ]
    ]

    assert await adapter.generate(asking(ASKS)) == AssistantMessage(
        (ThinkingPart("Two and two."), TextPart("4"))
    )


async def test_reasoning_the_model_did_not_show_is_no_thinking(
    endpoint: FakeResponsesEndpoint, adapter: ModelPort
) -> None:
    endpoint.replies = [[reasoning_item(), text_item("4")]]

    assert await adapter.generate(asking(ASKS)) == AssistantMessage((TextPart("4"),))


async def test_a_refusal_is_the_text_of_the_turn(
    endpoint: FakeResponsesEndpoint, adapter: ModelPort
) -> None:
    endpoint.replies = [
        [
            {
                **text_item(""),
                "content": [{"type": "refusal", "refusal": "I can't help with that."}],
            }
        ]
    ]

    assert await adapter.generate(asking(ASKS)) == AssistantMessage(
        (TextPart("I can't help with that."),)
    )


async def test_a_response_reporting_that_the_model_failed_raises(
    endpoint: FakeResponsesEndpoint, adapter: ModelPort
) -> None:
    endpoint.error_next = {"code": "server_error", "message": "overloaded"}

    with pytest.raises(ModelFailed, match="overloaded"):
        await adapter.generate(asking(ASKS))


async def test_tool_arguments_that_are_not_json_raise(
    endpoint: FakeResponsesEndpoint, adapter: ModelPort
) -> None:
    endpoint.replies = [[tool_call_item("call_1", "read_file", "{not json")]]

    with pytest.raises(JSONDecodeError):
        await adapter.generate(asking(ASKS))


async def test_the_parts_of_a_user_turn_are_sent_in_order_with_a_note_in_place_of_audio(
    endpoint: FakeResponsesEndpoint, adapter: ModelPort
) -> None:
    await adapter.generate(
        asking(
            UserMessage(
                (
                    TextPart("Look"),
                    ImagePart(data="iVBORw==", media_type="image/png"),
                    ImageUrlPart(url="https://example.test/cat.png"),
                    AudioPart(data="UklGRg==", format="wav"),
                )
            )
        )
    )

    assert endpoint.request_bodies[0]["input"][0]["content"] == [
        {"type": "input_text", "text": "Look"},
        {"type": "input_image", "image_url": "data:image/png;base64,iVBORw==", "detail": "auto"},
        {"type": "input_image", "image_url": "https://example.test/cat.png", "detail": "auto"},
        {"type": "input_text", "text": "[audio omitted: this model cannot hear audio]"},
    ]


async def test_the_models_own_turn_is_sent_back_as_it_produced_it_reasoning_included(
    endpoint: FakeResponsesEndpoint, adapter: ModelPort
) -> None:
    endpoint.replies = [
        [reasoning_item(), tool_call_item("call_1", "read_file", '{"path": "notes.txt"}')]
    ]
    turn = await adapter.generate(ModelInput(None, (READ_FILE,), (ASKS,)))

    await adapter.generate(
        ModelInput(None, (READ_FILE,), (ASKS, turn, ToolResultMessage("call_1", "buy milk")))
    )

    assert endpoint.request_bodies[1]["input"] == [
        ASKS_ON_THE_WIRE,
        {"id": "rs_1", "type": "reasoning", "summary": [], "encrypted_content": "gAAAAB-opaque"},
        {
            "id": "fc_call_1",
            "type": "function_call",
            "status": "completed",
            "call_id": "call_1",
            "name": "read_file",
            "arguments": '{"path": "notes.txt"}',
        },
        {"type": "function_call_output", "call_id": "call_1", "output": "buy milk"},
    ]


async def test_a_turn_it_did_not_produce_is_sent_as_its_text_and_tool_calls(
    endpoint: FakeResponsesEndpoint, adapter: ModelPort
) -> None:
    await adapter.generate(
        asking(
            ASKS,
            AssistantMessage(
                (
                    ThinkingPart("The notes will say."),
                    TextPart("Let me look."),
                    ToolCall("call_1", "read_file", {"path": "notes.txt"}),
                )
            ),
            ToolResultMessage("call_1", "buy milk"),
        )
    )

    assert endpoint.request_bodies[0]["input"][1:] == [
        {"role": "assistant", "content": "Let me look."},
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "read_file",
            "arguments": '{"path": "notes.txt"}',
        },
        {"type": "function_call_output", "call_id": "call_1", "output": "buy milk"},
    ]


async def test_a_context_started_over_is_sent_as_it_stands(
    endpoint: FakeResponsesEndpoint, adapter: ModelPort
) -> None:
    endpoint.replies = [[reasoning_item(), text_item("Milk.")]]
    await adapter.generate(asking(ASKS))
    other = UserMessage((TextPart("Something else"),))

    await adapter.generate(asking(other, AssistantMessage((TextPart("Milk."),)), ASKS))

    assert endpoint.request_bodies[1]["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "Something else"}]},
        {"role": "assistant", "content": "Milk."},
        ASKS_ON_THE_WIRE,
    ]
