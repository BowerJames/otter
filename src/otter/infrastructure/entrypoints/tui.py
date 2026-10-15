"""A terminal chat with an agent session.

    python -m otter.infrastructure.entrypoints.tui --model-name glm-5.3 \
        --model-type chat-completions --provider zai

The provider's API key is read from `<PROVIDER>_API_KEY`, which may be set in a `.env`
file in the working directory or one above it; a variable already set in the environment
wins.

With `--session-file`, the session's context is kept in that JSON Lines file: a file that
already holds a session is picked up where it left off, its turns shown in the transcript.
"""

import argparse
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from otter.core.chat import Chat


@dataclass(frozen=True)
class ChatSettings:
    """What a chat is opened with: the model, how it is reached, and the session's setup."""

    model_type: str
    provider: str
    model_name: str
    api_key: str
    system_prompt: str
    session_file: str | None
    title: str


type OpenChat = Callable[[ChatSettings], Chat]
"""Opens the chat `ChatSettings` describe. Raises `ValueError` for settings it cannot meet."""


class Tui:
    """The command that holds a terminal chat, opened through `open_chat`."""

    def __init__(self, open_chat: OpenChat) -> None:
        self._open_chat = open_chat
        self._parser = argparse.ArgumentParser(description="Chat with an otter agent session.")
        self._parser.add_argument("--model-name", required=True, help='such as "glm-5.3"')
        self._parser.add_argument(
            "--model-type", required=True, help='"chat-completions", "responses" or "realtime"'
        )
        self._parser.add_argument("--provider", required=True, help='such as "zai" or "openai"')
        self._parser.add_argument(
            "--system-prompt", default="You are a helpful assistant.", help="the system prompt"
        )
        self._parser.add_argument(
            "--session-file",
            help="a .jsonl file to keep the session in; one that holds a session is resumed",
        )

    async def __call__(self, argv: Sequence[str], environ: Mapping[str, str]) -> str | None:
        """Hold the chat `argv` asks for, until the user quits.

        Returns what went wrong, if the chat could not be held: no API key in `environ`,
        settings no chat can be opened with, or a session that cannot be started.
        Arguments that cannot be read exit, with a word on how to use the command.
        """
        args = self._parser.parse_args(argv)
        # The provider's name in upper case, with anything that is not a letter or digit
        # turned into an underscore: "open-router" is read from OPEN_ROUTER_API_KEY.
        variable = re.sub(r"[^A-Z0-9]", "_", args.provider.upper()) + "_API_KEY"
        api_key = environ.get(variable)
        if not api_key:
            return f"error: no API key for provider {args.provider!r}: set {variable}"
        settings = ChatSettings(
            model_type=args.model_type,
            provider=args.provider,
            model_name=args.model_name,
            api_key=api_key,
            system_prompt=args.system_prompt,
            session_file=args.session_file,
            title=f"{args.model_name} ({args.provider})",
        )
        try:
            await self._open_chat(settings)()
        except (ValueError, OSError) as error:
            return f"error: {error}"
        return None


if __name__ == "__main__":
    import asyncio
    import os
    import sys

    from dotenv import find_dotenv, load_dotenv

    from otter.infrastructure.factories.modules.agent_session import create_agent_session
    from otter.infrastructure.factories.modules.chat import create_terminal_chat
    from otter.infrastructure.factories.modules.model import create_model
    from otter.infrastructure.factories.modules.session_log import create_file_session_log

    def open_chat(settings: ChatSettings) -> Chat:
        model = create_model(
            settings.model_type, settings.provider, settings.model_name, settings.api_key
        )
        session_log = (
            create_file_session_log(settings.session_file) if settings.session_file else None
        )
        session = create_agent_session(
            model, system_prompt=settings.system_prompt, session_log=session_log
        )
        return create_terminal_chat(session, settings.title)

    # Searched for from the working directory, not from where this file is installed.
    load_dotenv(find_dotenv(usecwd=True))
    sys.exit(asyncio.run(Tui(open_chat)(sys.argv[1:], os.environ)))
