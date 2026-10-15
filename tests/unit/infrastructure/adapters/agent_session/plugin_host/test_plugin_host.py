"""Behaviour of the plugin host, driven through the agent session's port and observed at a fake
model, a fake session log, tools and plugins.
"""

from collections.abc import Sequence
from dataclasses import replace

import pytest

from otter.core.agent_session import AgentSessionPort, Idle, SessionControls
from otter.core.domain.messages import (
    AssistantMessage,
    ContextEntry,
    TextPart,
    ToolCall,
    ToolResultMessage,
    ToolSpec,
    UserMessage,
)
from otter.core.model import ModelInput
from otter.infrastructure.adapters.agent_session.plugin_host import (
    AgentTool,
    Deny,
    DuplicateTool,
    Plugin,
    PluginHostAdapter,
    SessionSetup,
    ToolOutcome,
    UnknownTool,
)

from .adapters import (
    FakeFiles,
    FakeModel,
    FakeSession,
    FakeSessionLog,
    Recorder,
    UnreadableFiles,
)

READ_FILE = ToolSpec(
    "read_file", "Read a file", {"type": "object", "properties": {"path": {"type": "string"}}}
)
CALL = ToolCall("call-1", "read_file", {"path": "a.txt"})
HELLO = UserMessage((TextPart("Hello"),))


def setup(
    model: FakeModel,
    log: FakeSessionLog | None = None,
    *,
    system_prompt: str | None = None,
    tools: Sequence[AgentTool] = (),
    plugins: Sequence[Plugin] = (),
) -> AgentSessionPort:
    return PluginHostAdapter(
        model,
        log if log is not None else FakeSessionLog(),
        system_prompt=system_prompt,
        tools=tools,
        plugins=plugins,
    )


@pytest.fixture
def model() -> FakeModel:
    return FakeModel()


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def files() -> FakeFiles:
    return FakeFiles()


async def started(port: AgentSessionPort, session: SessionControls) -> AgentSessionPort:
    await port.start(session)
    return port


# Starting and stopping


async def test_starting_opens_the_model_and_gives_the_entries_the_log_holds(
    model: FakeModel, session: FakeSession
) -> None:
    held: list[ContextEntry] = [HELLO, AssistantMessage((TextPart("Hi there"),))]

    context = await setup(model, FakeSessionLog(held)).start(session)

    assert list(context) == held
    assert model.calls == ["open"]


async def test_stopping_closes_the_model(model: FakeModel, session: FakeSession) -> None:
    port = await started(setup(model), session)

    await port.stop()

    assert model.calls == ["open", "close"]


async def test_starting_raises_what_opening_the_model_raises(
    model: FakeModel, session: FakeSession
) -> None:
    model.fail_to_open = ConnectionError("no route")

    with pytest.raises(ConnectionError, match=r"^no route$"):
        await setup(model).start(session)


# The model


async def test_the_model_is_shown_the_system_prompt_the_tools_and_the_context(
    model: FakeModel, session: FakeSession, files: FakeFiles
) -> None:
    port = await started(setup(model, system_prompt="Be brief.", tools=[files]), session)

    await port.generate([HELLO])

    assert model.shown == [ModelInput("Be brief.", (READ_FILE,), (HELLO,))]


async def test_the_turn_is_the_one_the_model_produces(
    model: FakeModel, session: FakeSession
) -> None:
    model.reply = AssistantMessage((TextPart("Four."),))
    port = await started(setup(model), session)

    assert await port.generate([HELLO]) == AssistantMessage((TextPart("Four."),))


# The log


async def test_a_recorded_entry_is_appended_to_the_log(
    model: FakeModel, session: FakeSession
) -> None:
    log = FakeSessionLog([HELLO])
    port = await started(setup(model, log), session)

    port.record(ToolResultMessage("call-1", "file contents"))

    assert log.held == [HELLO, ToolResultMessage("call-1", "file contents")]


# Tools


async def test_a_tool_call_is_run_by_the_tool_it_names_with_its_arguments(
    model: FakeModel, session: FakeSession, files: FakeFiles
) -> None:
    port = await started(setup(model, tools=[files]), session)

    assert await port.run_tool(CALL) == "file contents"
    assert files.runs == [{"path": "a.txt"}]


async def test_a_call_to_a_tool_the_session_does_not_have_raises_unknown_tool(
    model: FakeModel, session: FakeSession
) -> None:
    port = await started(setup(model), session)

    with pytest.raises(UnknownTool, match=r"^the session has no tool named 'read_file'$") as raised:
        await port.run_tool(CALL)

    assert raised.value.name == "read_file"


async def test_a_failed_tool_raises_what_it_raised(model: FakeModel, session: FakeSession) -> None:
    port = await started(setup(model, tools=[UnreadableFiles()]), session)

    with pytest.raises(PermissionError, match=r"^a\.txt is not readable$"):
        await port.run_tool(CALL)


async def test_two_tools_of_one_name_raise_and_the_model_is_not_opened(
    model: FakeModel, session: FakeSession, files: FakeFiles
) -> None:
    with pytest.raises(DuplicateTool, match=r"^two tools are named 'read_file'$"):
        await setup(model, tools=[files, FakeFiles()]).start(session)

    assert model.calls == []


# Plugins before start


class Suffixing(Recorder):
    """A plugin that adds its name to the end of the system prompt."""

    async def before_start(self, session: SessionControls, setup: SessionSetup) -> SessionSetup:
        await super().before_start(session, setup)
        return replace(setup, system_prompt=f"{setup.system_prompt} {self.name}")


async def test_the_model_is_shown_the_setup_the_plugins_return_before_start(
    model: FakeModel, session: FakeSession, files: FakeFiles
) -> None:
    class AddsFiles(Plugin):
        async def before_start(self, session: SessionControls, setup: SessionSetup) -> SessionSetup:
            return SessionSetup("Be thorough.", (*setup.tools, files))

    port = await started(setup(model, system_prompt="Be brief.", plugins=[AddsFiles()]), session)
    await port.generate([HELLO])

    assert model.shown[0].system == "Be thorough."
    assert model.shown[0].tools == (READ_FILE,)


async def test_a_tool_a_plugin_adds_before_start_is_run_when_the_model_asks_for_it(
    model: FakeModel, session: FakeSession, files: FakeFiles
) -> None:
    class AddsFiles(Plugin):
        async def before_start(self, session: SessionControls, setup: SessionSetup) -> SessionSetup:
            return replace(setup, tools=(*setup.tools, files))

    port = await started(setup(model, plugins=[AddsFiles()]), session)

    await port.run_tool(CALL)

    assert files.runs == [{"path": "a.txt"}]


async def test_each_plugin_is_given_the_setup_the_plugin_before_it_returned(
    model: FakeModel, session: FakeSession
) -> None:
    port = await started(
        setup(model, system_prompt="Be brief.", plugins=[Suffixing("a"), Suffixing("b")]), session
    )
    await port.generate([HELLO])

    assert model.shown[0].system == "Be brief. a b"


async def test_a_plugin_that_fails_before_start_propagates_and_the_model_is_not_opened(
    model: FakeModel, session: FakeSession
) -> None:
    class Failing(Plugin):
        async def before_start(self, session: SessionControls, setup: SessionSetup) -> SessionSetup:
            raise ValueError("no rules found")

    with pytest.raises(ValueError, match=r"^no rules found$"):
        await setup(model, plugins=[Failing()]).start(session)

    assert model.calls == []


# Plugins around a tool call


class Denying(Recorder):
    """A plugin that denies every tool call, giving its name as the reason."""

    async def before_tool(self, session: SessionControls, call: ToolCall) -> Deny | None:
        await super().before_tool(session, call)
        return Deny(f"{self.name} says no")


class Reporting(Recorder):
    """A plugin that turns a tool call's error into text for the model."""

    async def after_tool(
        self, session: SessionControls, call: ToolCall, outcome: ToolOutcome
    ) -> ToolOutcome:
        await super().after_tool(session, call, outcome)
        if isinstance(outcome, Exception):
            return f"{call.name} failed: {outcome}"
        return outcome


async def test_a_tool_call_a_plugin_denies_is_not_run_and_the_model_is_shown_the_reason(
    model: FakeModel, session: FakeSession, files: FakeFiles
) -> None:
    port = await started(setup(model, tools=[files], plugins=[Denying("guard")]), session)

    assert await port.run_tool(CALL) == "guard says no"
    assert files.runs == []


async def test_every_plugin_is_asked_about_a_tool_call_and_the_model_is_shown_every_reason(
    model: FakeModel, session: FakeSession, files: FakeFiles
) -> None:
    watching = Recorder("watching")
    plugins = [Denying("first"), watching, Denying("second")]
    port = await started(setup(model, tools=[files], plugins=plugins), session)

    assert await port.run_tool(CALL) == "first says no\nsecond says no"
    assert watching.asked_at("before_tool") == [("watching", "before_tool", CALL)]


async def test_a_denied_tool_call_is_not_put_to_plugins_after_the_tool(
    model: FakeModel, session: FakeSession, files: FakeFiles
) -> None:
    guard = Denying("guard")
    port = await started(setup(model, tools=[files], plugins=[guard]), session)

    await port.run_tool(CALL)

    assert guard.asked_at("after_tool") == []


async def test_each_plugin_is_given_the_outcome_the_plugin_before_it_returned(
    model: FakeModel, session: FakeSession, files: FakeFiles
) -> None:
    class Tagging(Plugin):
        def __init__(self, tag: str) -> None:
            self.tag = tag

        async def after_tool(
            self, session: SessionControls, call: ToolCall, outcome: ToolOutcome
        ) -> ToolOutcome:
            return f"{outcome} {self.tag}"

    port = await started(setup(model, tools=[files], plugins=[Tagging("a"), Tagging("b")]), session)

    assert await port.run_tool(CALL) == "file contents a b"


async def test_a_failed_tool_a_plugin_returns_text_for_comes_out_as_that_text(
    model: FakeModel, session: FakeSession
) -> None:
    port = await started(setup(model, tools=[UnreadableFiles()], plugins=[Reporting()]), session)

    assert await port.run_tool(CALL) == "read_file failed: a.txt is not readable"


async def test_a_failed_tool_is_put_to_the_plugins_as_the_error_it_raised(
    model: FakeModel, session: FakeSession
) -> None:
    watching = Recorder()
    port = await started(setup(model, tools=[UnreadableFiles()], plugins=[watching]), session)

    with pytest.raises(PermissionError):
        await port.run_tool(CALL)

    [(_, _, _, outcome)] = watching.asked_at("after_tool")
    assert isinstance(outcome, PermissionError)


async def test_a_call_to_a_tool_the_session_does_not_have_is_put_to_plugins_as_unknown_tool(
    model: FakeModel, session: FakeSession
) -> None:
    port = await started(setup(model, plugins=[Reporting()]), session)

    assert await port.run_tool(CALL) == (
        "read_file failed: the session has no tool named 'read_file'"
    )


async def test_an_error_a_plugin_returns_after_a_tool_is_raised(
    model: FakeModel, session: FakeSession, files: FakeFiles
) -> None:
    class Rejecting(Plugin):
        async def after_tool(
            self, session: SessionControls, call: ToolCall, outcome: ToolOutcome
        ) -> ToolOutcome:
            return ValueError("the result holds a secret")

    port = await started(setup(model, tools=[files], plugins=[Rejecting()]), session)

    with pytest.raises(ValueError, match=r"^the result holds a secret$"):
        await port.run_tool(CALL)


async def test_a_plugin_that_fails_after_a_tool_propagates_past_the_plugins_after_it(
    model: FakeModel, session: FakeSession, files: FakeFiles
) -> None:
    class Failing(Plugin):
        async def after_tool(
            self, session: SessionControls, call: ToolCall, outcome: ToolOutcome
        ) -> ToolOutcome:
            raise RuntimeError("plugin broke")

    reporting = Reporting()
    port = await started(setup(model, tools=[files], plugins=[Failing(), reporting]), session)

    with pytest.raises(RuntimeError, match=r"^plugin broke$"):
        await port.run_tool(CALL)

    assert reporting.asked_at("after_tool") == []


# Plugins as the session runs and stops


async def test_every_plugin_is_asked_before_idle_in_order_with_the_session(
    model: FakeModel, session: FakeSession
) -> None:
    log: list[tuple[object, ...]] = []
    port = await started(setup(model, plugins=[Recorder("a", log), Recorder("b", log)]), session)

    await port.before_idle()

    assert log[-2:] == [("a", "before_idle", session), ("b", "before_idle", session)]


async def test_a_plugin_may_prompt_the_session_it_is_asked_by(
    model: FakeModel, session: FakeSession
) -> None:
    class ChecksWork(Plugin):
        async def before_idle(self, session: SessionControls) -> None:
            session.prompt("Check your work")

    port = await started(setup(model, plugins=[ChecksWork()]), session)

    await port.before_idle()

    assert session.prompts == ["Check your work"]


async def test_every_plugin_is_told_each_event_in_order_with_the_session(
    model: FakeModel, session: FakeSession
) -> None:
    log: list[tuple[object, ...]] = []
    port = await started(setup(model, plugins=[Recorder("a", log), Recorder("b", log)]), session)

    await port.on_event(Idle())

    assert log[-2:] == [("a", "on_event", session, Idle()), ("b", "on_event", session, Idle())]


async def test_every_plugin_is_asked_after_end_as_the_session_stops(
    model: FakeModel, session: FakeSession
) -> None:
    log: list[tuple[object, ...]] = []
    port = await started(setup(model, plugins=[Recorder("a", log), Recorder("b", log)]), session)

    await port.stop()

    assert log[-2:] == [("a", "after_end", session), ("b", "after_end", session)]


async def test_a_plugin_that_fails_after_end_propagates_and_the_model_is_closed(
    model: FakeModel, session: FakeSession
) -> None:
    class Failing(Plugin):
        async def after_end(self, session: SessionControls) -> None:
            raise OSError("could not flush")

    port = await started(setup(model, plugins=[Failing()]), session)

    with pytest.raises(OSError, match=r"^could not flush$"):
        await port.stop()

    assert model.calls == ["open", "close"]
