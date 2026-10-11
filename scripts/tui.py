"""A terminal chat with an agent session, for trying otter out during development.

    uv run python scripts/tui.py --model-name glm-5.3 --model-type chat-completions --provider zai

The provider's API key is read from `<PROVIDER>_API_KEY`, which may be set in a `.env`
file at the root of the repository; a variable already set in the environment wins.

With `--session-file`, the session's context is kept in that JSON Lines file: a file that
already holds a session is picked up where it left off, its turns shown in the transcript.
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass

from dotenv import load_dotenv

from otter.agent_session import AgentSession, create_agent_session
from otter.auth_resolver import MissingApiKeyError
from otter.chat_screen import ChatScreen, create_textual_chat_screen
from otter.session_manager import (
    SessionManager,
    create_file_system_session_manager,
    create_in_memory_session_manager,
)
from otter.tui import Tui, create_session_tui


@dataclass(frozen=True)
class Model:
    model_name: str
    model_type: str
    provider: str


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with an otter agent session.")
    parser.add_argument("--model-name", required=True, help='such as "glm-5.3"')
    parser.add_argument(
        "--model-type", required=True, help='"chat-completions", "responses" or "realtime"'
    )
    parser.add_argument("--provider", required=True, help='such as "zai" or "openai"')
    parser.add_argument(
        "--system-prompt", default="You are a helpful assistant.", help="the system prompt"
    )
    parser.add_argument(
        "--session-file",
        help="a .jsonl file to keep the session in; one that already holds a session is resumed",
    )
    args = parser.parse_args()

    load_dotenv()
    model = Model(args.model_name, args.model_type, args.provider)
    session_manager: SessionManager = (
        create_file_system_session_manager(args.session_file)
        if args.session_file
        else create_in_memory_session_manager()
    )
    try:
        # Read before the session can add to it: this is what the session starts with.
        context = session_manager.entries()
        session = create_agent_session(
            args.system_prompt, [], model, session_manager=session_manager
        )
    except (MissingApiKeyError, ValueError, OSError) as error:
        sys.exit(f"error: {error}")
    screen = create_textual_chat_screen(f"{model.model_name} ({model.provider})")
    asyncio.run(_chat(session, screen, create_session_tui(session, screen, context=context)))


async def _chat(session: AgentSession, screen: ChatScreen, tui: Tui) -> None:
    async with session, screen:
        await tui()


if __name__ == "__main__":
    main()
