"""The terminal a Textual app is run on."""

from collections.abc import Awaitable, Callable

from textual.app import App

type TextualTerminal = Callable[[App[None]], Awaitable[None]]
"""Runs a Textual app on a terminal, returning once the app has exited."""


async def this_terminal(app: App[None]) -> None:
    """Run `app` on the terminal this process is running in."""
    await app.run_async()
