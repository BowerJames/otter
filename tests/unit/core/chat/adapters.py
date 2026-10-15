"""Test adapters for the chat's port."""

import asyncio
from collections.abc import AsyncGenerator, Sequence

from otter.core.chat import ChatPort, SessionUpdate, Status, TranscriptLine
from otter.core.domain.messages import ContextEntry


class FakeChatAdapter(ChatPort):
    """A session and a screen, both scripted and recorded.

    The session starts with `history`, records the prompts put to it, and its updates
    are whatever the test says `happens`, as it says so; it `fails` by raising the error
    given. Once `refusing` is set, a prompt raises it. The screen records the lines and
    statuses it is shown, and hands over what the test has the user `submit`, until the
    user `quit`s. `calls` records each opening and closing. While `fail_to_open` is
    set, opening raises it.
    """

    def __init__(self, history: Sequence[ContextEntry] = ()) -> None:
        self.started_with = list(history)
        self.prompts: list[str] = []
        self.refusing: Exception | None = None
        self.transcript: list[TranscriptLine] = []
        self.statuses: list[Status] = []
        self.calls: list[str] = []
        self.reads_started = 0
        self.reads_finished = 0
        self.fail_to_open: Exception | None = None
        self._happening: asyncio.Queue[SessionUpdate | Exception] = asyncio.Queue()
        self._submitted: asyncio.Queue[str | None] = asyncio.Queue()

    def happens(self, *updates: SessionUpdate) -> None:
        for update in updates:
            self._happening.put_nowait(update)

    def fails(self, error: Exception) -> None:
        self._happening.put_nowait(error)

    def submit(self, text: str) -> None:
        self._submitted.put_nowait(text)

    def quit(self) -> None:
        self._submitted.put_nowait(None)

    async def open(self) -> None:
        if self.fail_to_open is not None:
            raise self.fail_to_open
        self.calls.append("open")

    async def close(self) -> None:
        self.calls.append("close")

    def history(self) -> Sequence[ContextEntry]:
        return tuple(self.started_with)

    def prompt(self, text: str) -> None:
        if self.refusing is not None:
            raise self.refusing
        self.prompts.append(text)

    async def updates(self) -> AsyncGenerator[SessionUpdate, None]:
        self.reads_started += 1
        try:
            while True:
                happening = await self._happening.get()
                if isinstance(happening, Exception):
                    raise happening
                yield happening
        finally:
            self.reads_finished += 1

    def show(self, line: TranscriptLine) -> None:
        self.transcript.append(line)

    def set_status(self, status: Status) -> None:
        self.statuses.append(status)

    async def submissions(self) -> AsyncGenerator[str, None]:
        while (text := await self._submitted.get()) is not None:
            yield text
