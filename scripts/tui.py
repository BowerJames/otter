"""A terminal chat with an agent session, for trying otter out during development.

    uv run python scripts/tui.py --model-name glm-5.3 --model-type chat-completions --provider zai

The provider's API key is read from `<PROVIDER>_API_KEY`, which may be set in a `.env`
file at the root of the repository; a variable already set in the environment wins.
"""

import argparse
import json
import sys
from dataclasses import dataclass

from dotenv import load_dotenv
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Input, RichLog

from otter.agent_session import AgentSession, AssistantTurn, Idle, ToolResult, UserTurn
from otter.auth_resolver import MissingApiKeyError
from otter.create_agent_session import create_agent_session
from otter.messages import TextPart, ThinkingPart, ToolCall


@dataclass(frozen=True)
class Model:
    model_name: str
    model_type: str
    provider: str


class SessionApp(App[None]):
    """A transcript of one agent session above a box to prompt it from."""

    CSS = """
    RichLog { padding: 0 1; }
    Input { dock: bottom; }
    """

    def __init__(self, session: AgentSession, title: str) -> None:
        super().__init__()
        self._session = session
        self._title = title
        self._reading = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield RichLog(wrap=True)
        yield Input(placeholder="Message the agent, then press Enter")
        yield Footer()

    def on_mount(self) -> None:
        self.title = self._title
        self.query_one(Input).focus()
        self._read_session()

    def on_unmount(self) -> None:
        self._session.end()

    def on_input_submitted(self, message: Input.Submitted) -> None:
        if not message.value.strip():
            return
        message.input.clear()
        try:
            self._session.prompt(message.value)
        except RuntimeError as error:
            self._show(f"error: {error}", "bold red")
            return
        self.sub_title = "working"
        # The stream stops when the model fails; the next prompt starts it again, which
        # also retries the turn that failed.
        self._read_session()

    def _read_session(self) -> None:
        if not self._reading:
            self._reading = True
            self.run_worker(self._show_events())

    async def _show_events(self) -> None:
        try:
            async for event in self._session.stream():
                match event:
                    case UserTurn(content):
                        text = " ".join(
                            part.text if isinstance(part, TextPart) else "[attachment]"
                            for part in content
                        )
                        self._show(f"you: {text}", "bold cyan")
                    case AssistantTurn(message):
                        for part in message.content:
                            match part:
                                case ThinkingPart(text):
                                    self._show(text, "dim italic")
                                case TextPart(text):
                                    self._show(text)
                                case ToolCall(_, name, arguments):
                                    self._show(f"tool: {name}({json.dumps(arguments)})", "yellow")
                    case ToolResult(_, text):
                        self._show(f"result: {text}", "dim yellow")
                    case Idle():
                        self.sub_title = "idle"
        except Exception as error:
            self._show(f"error: {error}", "bold red")
            self._show("Send another message to try again.", "dim")
            self.sub_title = "stopped"
        finally:
            self._reading = False

    def _show(self, text: str, style: str = "") -> None:
        self.query_one(RichLog).write(Text(text, style=style))


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with an otter agent session.")
    parser.add_argument("--model-name", required=True, help='such as "glm-5.3"')
    parser.add_argument(
        "--model-type", required=True, help='such as "chat-completions" or "responses"'
    )
    parser.add_argument("--provider", required=True, help='such as "zai" or "openai"')
    parser.add_argument(
        "--system-prompt", default="You are a helpful assistant.", help="the system prompt"
    )
    args = parser.parse_args()

    load_dotenv()
    model = Model(args.model_name, args.model_type, args.provider)
    try:
        session = create_agent_session(args.system_prompt, [], model)
    except (MissingApiKeyError, ValueError) as error:
        sys.exit(f"error: {error}")
    SessionApp(session, f"{model.model_name} ({model.provider})").run()


if __name__ == "__main__":
    main()
