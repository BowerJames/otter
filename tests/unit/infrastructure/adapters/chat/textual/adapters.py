"""Test adapters for what the Textual adapter is made with: a session and a terminal."""

import asyncio
import contextvars
from collections.abc import AsyncGenerator, Coroutine, Sequence
from types import TracebackType
from typing import Self

from textual.app import App
from textual.pilot import Pilot
from textual.widgets import Input, RichLog

from otter.core.agent_session import AgentSession, SessionEvent
from otter.core.domain.messages import AudioPart, ContextEntry, ImagePart, ImageUrlPart


class FakeAgentSession(AgentSession):
    """Starts with `started_with`, records the prompts made to it, and streams `events`.

    `calls` records each entering and leaving. While `fail_to_enter` is set, entering
    raises it.
    """

    def __init__(self) -> None:
        self.started_with: list[ContextEntry] = []
        self.events: list[SessionEvent] = []
        self.prompts: list[str] = []
        self.calls: list[str] = []
        self.fail_to_enter: Exception | None = None

    def prompt(
        self,
        text: str,
        *,
        images: Sequence[ImagePart | ImageUrlPart] = (),
        audio: Sequence[AudioPart] = (),
    ) -> None:
        self.prompts.append(text)

    async def stream(self) -> AsyncGenerator[SessionEvent, None]:
        for event in self.events:
            yield event

    def history(self) -> Sequence[ContextEntry]:
        return tuple(self.started_with)

    async def wait_for_idle(self) -> None:
        pass

    def end(self) -> None:
        pass

    async def __aenter__(self) -> Self:
        if self.fail_to_enter is not None:
            raise self.fail_to_enter
        self.calls.append("enter")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.calls.append("leave")


class HeadlessTerminal:
    """Runs the app with no terminal under it, and lets the test read what the app is
    showing and press its keys.

    Textual expects its pilot to be used where the app is the active one, which a test's
    own task is not: there, a pause that gets to draw the screen before the app does
    raises `LookupError`. So the pilot is only ever used in the context the app gave it.
    """

    def __init__(self) -> None:
        self.running = False
        self._down = asyncio.Event()
        self._app: App[None] | None = None
        self._pilot: Pilot[object] | None = None
        self._pilots_context: contextvars.Context | None = None

    async def __call__(self, app: App[None]) -> None:
        self._app = app
        self.running = True
        try:
            await app.run_async(headless=True, size=(80, 24), auto_pilot=self._take)
        finally:
            self.running = False
            self._down.set()

    async def _take(self, pilot: Pilot[object]) -> None:
        self._pilot = pilot
        self._pilots_context = contextvars.copy_context()

    async def _piloting(self, action: Coroutine[object, object, None]) -> None:
        """Have the pilot do `action` in the context the app gave it."""
        assert self._pilots_context is not None, "nothing is running on the terminal"
        await asyncio.create_task(action, context=self._pilots_context)

    @property
    def app(self) -> App[None]:
        assert self._app is not None, "nothing has been run on the terminal"
        return self._app

    @property
    def pilot(self) -> Pilot[object]:
        assert self._pilot is not None, "nothing is running on the terminal"
        return self._pilot

    @property
    def title(self) -> str:
        return self.app.title

    @property
    def status(self) -> str:
        return self.app.sub_title

    @property
    def typed(self) -> str:
        """What is in the box the user types into."""
        return self.app.query_one(Input).value

    async def transcript(self) -> list[str]:
        await self._piloting(self.pilot.pause())
        return [line.text.rstrip() for line in self.app.query_one(RichLog).lines]

    async def press(self, *keys: str) -> None:
        await self._piloting(self.pilot.press(*keys))
        await self._piloting(self.pilot.pause())

    async def quit(self) -> None:
        """Press the key that quits, and wait for the app to go down."""
        await self._piloting(self.pilot.press("ctrl+q"))
        await self._down.wait()

    async def submit(self, text: str) -> None:
        await self.press(*("space" if key == " " else key for key in text), "enter")
