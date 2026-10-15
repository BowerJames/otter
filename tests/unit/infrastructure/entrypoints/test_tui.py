"""Behaviour of the TUI command, observed at the chat it opens."""

import pytest

from otter.infrastructure.entrypoints.tui import ChatSettings, Tui

from .adapters import FakeOpenChat

ARGV = ["--model-name", "glm-5.3", "--model-type", "chat-completions", "--provider", "zai"]
ENVIRON = {"ZAI_API_KEY": "zai-key"}


@pytest.fixture
def open_chat() -> FakeOpenChat:
    return FakeOpenChat()


async def test_the_chat_is_opened_with_the_settings_the_arguments_and_environment_give(
    open_chat: FakeOpenChat,
) -> None:
    await Tui(open_chat)(
        [*ARGV, "--system-prompt", "Be brief.", "--session-file", "session.jsonl"], ENVIRON
    )

    assert open_chat.opened == [
        ChatSettings(
            model_type="chat-completions",
            provider="zai",
            model_name="glm-5.3",
            api_key="zai-key",
            system_prompt="Be brief.",
            session_file="session.jsonl",
            title="glm-5.3 (zai)",
        )
    ]


async def test_the_chat_is_held_and_nothing_is_reported(open_chat: FakeOpenChat) -> None:
    assert await Tui(open_chat)(ARGV, ENVIRON) is None
    assert open_chat.chat.held


async def test_left_out_the_system_prompt_is_a_helpful_assistants_and_no_session_file_is_kept(
    open_chat: FakeOpenChat,
) -> None:
    await Tui(open_chat)(ARGV, ENVIRON)

    assert open_chat.opened[0].system_prompt == "You are a helpful assistant."
    assert open_chat.opened[0].session_file is None


@pytest.mark.parametrize(
    "provider, variable",
    [
        ("openai", "OPENAI_API_KEY"),
        ("open-router", "OPEN_ROUTER_API_KEY"),
        ("z.ai", "Z_AI_API_KEY"),
    ],
)
async def test_the_api_key_is_read_from_the_providers_variable(
    provider: str, variable: str, open_chat: FakeOpenChat
) -> None:
    argv = ["--model-name", "m", "--model-type", "responses", "--provider", provider]

    await Tui(open_chat)(argv, {variable: "the-key"})

    assert open_chat.opened[0].api_key == "the-key"


@pytest.mark.parametrize("environ", [{}, {"ZAI_API_KEY": ""}], ids=["unset", "empty"])
async def test_a_missing_api_key_is_reported_with_the_variable_to_set_and_no_chat_is_opened(
    environ: dict[str, str], open_chat: FakeOpenChat
) -> None:
    reported = await Tui(open_chat)(ARGV, environ)

    assert reported == "error: no API key for provider 'zai': set ZAI_API_KEY"
    assert open_chat.opened == []


async def test_settings_no_chat_can_be_opened_with_are_reported(open_chat: FakeOpenChat) -> None:
    open_chat.refusing = ValueError("provider 'zai' serves no 'realtime' models")

    reported = await Tui(open_chat)(ARGV, ENVIRON)

    assert reported == "error: provider 'zai' serves no 'realtime' models"


async def test_a_chat_that_cannot_be_held_is_reported(open_chat: FakeOpenChat) -> None:
    open_chat.chat.failing = OSError("not a terminal")

    assert await Tui(open_chat)(ARGV, ENVIRON) == "error: not a terminal"


async def test_arguments_that_cannot_be_read_exit(open_chat: FakeOpenChat) -> None:
    with pytest.raises(SystemExit):
        await Tui(open_chat)(["--model-name", "glm-5.3"], ENVIRON)

    assert open_chat.opened == []
