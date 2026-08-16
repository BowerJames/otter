from collections.abc import AsyncGenerator

import pytest

from otter_ai_core.components.terminating_stream import TerminatingStream


class Partial: ...


class Terminal: ...


class SourceFailed(Exception): ...


def _stream_yielding(*events: Partial | Terminal) -> TerminatingStream[Partial, Terminal]:
    class ScriptedStream(TerminatingStream[Partial, Terminal]):
        terminal_event_type = Terminal

        async def _iterate_source(self) -> AsyncGenerator[Partial | Terminal, None]:
            for event in events:
                yield event

    return ScriptedStream()


def _releasing_stream(
    releases: list[str], *events: Partial | Terminal
) -> TerminatingStream[Partial, Terminal]:
    class ReleasingStream(TerminatingStream[Partial, Terminal]):
        terminal_event_type = Terminal

        async def _iterate_source(self) -> AsyncGenerator[Partial | Terminal, None]:
            try:
                for event in events:
                    yield event
            finally:
                releases.append("released")

    return ReleasingStream()


def _failing_stream(
    releases: list[str], *events: Partial | Terminal, error: BaseException
) -> TerminatingStream[Partial, Terminal]:
    class FailingStream(TerminatingStream[Partial, Terminal]):
        terminal_event_type = Terminal

        async def _iterate_source(self) -> AsyncGenerator[Partial | Terminal, None]:
            try:
                for event in events:
                    yield event
                raise error
            finally:
                releases.append("released")

    return FailingStream()


async def test_yields_events_up_to_and_including_the_terminal_event() -> None:
    first_partial = Partial()
    second_partial = Partial()
    terminal = Terminal()

    stream = _stream_yielding(first_partial, second_partial, terminal, Partial())

    collected = [event async for event in stream]

    assert collected == [first_partial, second_partial, terminal]


async def test_releases_source_resources_once_when_iteration_ends_at_the_terminal_event() -> None:
    releases: list[str] = []

    stream = _releasing_stream(releases, Partial(), Terminal())

    async for _ in stream:
        assert releases == []

    assert releases == ["released"]


async def test_releases_source_resources_once_when_iteration_ends_at_source_exhaustion() -> None:
    releases: list[str] = []

    stream = _releasing_stream(releases, Partial(), Partial())

    async for _ in stream:
        assert releases == []

    assert releases == ["released"]


async def test_propagates_a_source_failure_after_delivering_preceding_events() -> None:
    releases: list[str] = []
    error = SourceFailed("boom")
    first_partial = Partial()

    stream = _failing_stream(releases, first_partial, error=error)

    collected: list[Partial | Terminal] = []
    with pytest.raises(SourceFailed) as excinfo:
        async for event in stream:
            collected.append(event)

    assert excinfo.value is error
    assert collected == [first_partial]
    assert releases == ["released"]
