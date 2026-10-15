"""Behaviour of a model, observed at a fake provider and the turns it returns."""

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
from otter.core.model import Model, ModelImpl, ModelInput, ModelNotOpen

from .adapters import FakeModelAdapter

IMAGE = ImagePart(data="iVBORw==", media_type="image/png")
IMAGE_URL = ImageUrlPart(url="https://example.test/cat.png")
AUDIO = AudioPart(data="UklGRg==", format="wav")
IMAGE_NOTE = TextPart("[image omitted: this model cannot view images]")
AUDIO_NOTE = TextPart("[audio omitted: this model cannot hear audio]")
LOOKUP = ToolSpec("lookup", "Look a word up.", {"type": "object"})


def setup(
    port: FakeModelAdapter, *, accepts_images: bool = True, accepts_audio: bool = True
) -> Model:
    return ModelImpl(port, accepts_images=accepts_images, accepts_audio=accepts_audio)


def asking(*entries: ContextEntry) -> ModelInput:
    return ModelInput("Be brief.", (LOOKUP,), entries)


@pytest.fixture
def port() -> FakeModelAdapter:
    return FakeModelAdapter()


async def test_the_turn_is_the_one_the_provider_produces(port: FakeModelAdapter) -> None:
    port.reply = AssistantMessage((ThinkingPart("Easy."), TextPart("Four.")))

    async with setup(port) as model:
        turn = await model.generate(asking(UserMessage((TextPart("2 + 2?"),))))

    assert turn == AssistantMessage((ThinkingPart("Easy."), TextPart("Four.")))


async def test_the_provider_is_shown_the_system_prompt_tools_and_context_given(
    port: FakeModelAdapter,
) -> None:
    model_input = asking(
        UserMessage((TextPart("Define otter."),)),
        AssistantMessage((ThinkingPart("Look it up."), ToolCall("call-1", "lookup", {}))),
        ToolResultMessage("call-1", "A mammal."),
    )

    async with setup(port) as model:
        await model.generate(model_input)

    assert port.calls[1] == model_input


async def test_the_provider_is_opened_on_entry_and_closed_on_exit(port: FakeModelAdapter) -> None:
    async with setup(port):
        assert port.calls == ["open"]

    assert port.calls == ["open", "close"]


async def test_a_model_not_entered_refuses_to_generate(port: FakeModelAdapter) -> None:
    with pytest.raises(ModelNotOpen):
        await setup(port).generate(asking())

    assert port.calls == []


async def test_a_model_that_has_been_left_refuses_to_generate(port: FakeModelAdapter) -> None:
    model = setup(port)
    async with model:
        pass

    with pytest.raises(ModelNotOpen):
        await model.generate(asking())


async def test_a_model_whose_provider_fails_to_open_is_not_open(port: FakeModelAdapter) -> None:
    model = setup(port)
    port.failing_to_open = ConnectionError("no route to host")
    with pytest.raises(ConnectionError):
        await model.__aenter__()

    with pytest.raises(ModelNotOpen):
        await model.generate(asking())


@pytest.mark.parametrize(
    "accepts_images, accepts_audio, sent",
    [
        (False, True, (TextPart("Look"), IMAGE_NOTE, IMAGE_NOTE, AUDIO)),
        (True, False, (TextPart("Look"), IMAGE, IMAGE_URL, AUDIO_NOTE)),
        (False, False, (TextPart("Look"), IMAGE_NOTE, IMAGE_NOTE, AUDIO_NOTE)),
        (True, True, (TextPart("Look"), IMAGE, IMAGE_URL, AUDIO)),
    ],
)
async def test_what_the_model_cannot_take_in_is_replaced_by_a_note(
    accepts_images: bool,
    accepts_audio: bool,
    sent: tuple[TextPart | ImagePart | ImageUrlPart | AudioPart, ...],
    port: FakeModelAdapter,
) -> None:
    model = setup(port, accepts_images=accepts_images, accepts_audio=accepts_audio)

    async with model:
        await model.generate(asking(UserMessage((TextPart("Look"), IMAGE, IMAGE_URL, AUDIO))))

    assert port.calls[1] == asking(UserMessage(sent))


async def test_an_entry_the_model_takes_whole_is_passed_on_as_it_was_given(
    port: FakeModelAdapter,
) -> None:
    entry = UserMessage((TextPart("Hello"),))

    async with setup(port, accepts_images=False, accepts_audio=False) as model:
        await model.generate(asking(entry))

    sent = port.calls[1]
    assert isinstance(sent, ModelInput)
    assert sent.context[0] is entry
