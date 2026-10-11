"""A chat screen drawn on the terminal with Textual."""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from ._chat_screen import ChatScreen

if TYPE_CHECKING:
    from textual.app import App

type TextualTerminal = Callable[[App[None]], Awaitable[None]]
"""Runs a Textual app on a terminal, returning once the app has exited."""


async def _this_terminal(app: "App[None]") -> None:
    await app.run_async()


def create_textual_chat_screen(
    title: str, *, terminal: TextualTerminal = _this_terminal
) -> ChatScreen:
    """Return a chat screen drawn on the terminal with Textual, under `title`.

    The transcript fills the screen above a box the user types into: entering what is
    typed submits it and empties the box. The status is shown beside the title. The
    user quits with ctrl+q.

    Entering the screen puts it up and leaving takes it down. `terminal` is what it is
    put up on; leave it out to use the terminal this process is running in. If the
    screen cannot be put up, the error propagates.

    Textual is needed only once this is called: install otter with its `tui` extra.
    """
    # Imported here, so that the package can be imported without Textual installed.
    from ._textual_chat_screen import TextualChatScreen

    return TextualChatScreen(title, terminal)
