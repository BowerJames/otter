"""A chat's session, held on a screen drawn on the terminal with Textual."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from contextlib import aclosing

from otter.core.agent_session import AgentSession
from otter.core.agent_session import Idle as SessionIdle
from otter.core.chat import ChatPort, SessionUpdate, Status, TranscriptLine
from otter.core.chat import Idle as ChatIdle
from otter.core.domain.messages import ContextEntry

from .app import ChatApp
from .terminal import TextualTerminal


class TextualAdapter(ChatPort):
    """`session`, held on a screen drawn under `title` on `terminal` with Textual.

    Opening enters the session and then puts the screen up; closing takes the screen
    down and then leaves the session. Once the user has quit, what is shown is dropped.
    """

    def __init__(self, session: AgentSession, title: str, terminal: TextualTerminal) -> None:
        self._session = session
        self._app = ChatApp(title)
        self._terminal = terminal
        self._running: asyncio.Future[None] | None = None

    async def open(self) -> None:
        await self._session.__aenter__()
        try:
            await self._put_up()
        except BaseException:
            await self._session.__aexit__(None, None, None)
            raise

    async def _put_up(self) -> None:
        running = asyncio.ensure_future(self._terminal(self._app))
        running.add_done_callback(lambda _: self._app.submitted.put_nowait(None))
        mounted = asyncio.ensure_future(self._app.mounted.wait())
        try:
            await asyncio.wait([running, mounted], return_when=asyncio.FIRST_COMPLETED)
        finally:
            mounted.cancel()
        if running.done():
            # The app went down before it was up: whatever brought it down propagates.
            running.result()
        self._running = running

    async def close(self) -> None:
        try:
            if self._running is not None:
                self._app.exit()
                await self._running
        finally:
            await self._session.__aexit__(None, None, None)

    def history(self) -> Sequence[ContextEntry]:
        return self._session.history()

    def prompt(self, text: str) -> None:
        self._session.prompt(text)

    async def updates(self) -> AsyncGenerator[SessionUpdate, None]:
        async with aclosing(self._session.stream()) as events:
            async for event in events:
                yield ChatIdle() if isinstance(event, SessionIdle) else event

    def show(self, line: TranscriptLine) -> None:
        if self._app.is_running:
            self._app.draw(line)

    def set_status(self, status: Status) -> None:
        if self._app.is_running:
            self._app.sub_title = status

    async def submissions(self) -> AsyncIterator[str]:
        while (text := await self._app.submitted.get()) is not None:
            yield text
        # Left for whoever asks next: the user has quit for them too.
        self._app.submitted.put_nowait(None)
