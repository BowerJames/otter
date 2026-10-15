"""An agent session's world: a model, a session log, tools, and plugins."""

from collections.abc import Sequence

from otter.core.agent_session import AgentSessionPort, SessionControls, SessionEvent
from otter.core.domain.messages import AssistantMessage, ContextEntry, ToolCall, ToolSpec
from otter.core.model import Model, ModelInput
from otter.core.session_log import SessionLog

from .errors import DuplicateTool, UnknownTool
from .plugin import AgentTool, Plugin, SessionSetup, ToolOutcome


class PluginHostAdapter(AgentSessionPort):
    """Runs a session on `model`, keeps its context in `log`, and hosts its tools and plugins.

    The session starts with the entries `log` holds, and everything that joins it is
    appended to `log`. `model` is opened as the session starts and closed as it stops.
    It is shown `system_prompt` and told of `tools`, as `plugins` leave them before the
    session starts (see `Plugin`). Each tool call is put to `plugins`, and run by the
    tool of that name unless one of them denies it.
    """

    def __init__(
        self,
        model: Model,
        log: SessionLog,
        *,
        system_prompt: str | None,
        tools: Sequence[AgentTool],
        plugins: Sequence[Plugin],
    ) -> None:
        self._model = model
        self._log = log
        self._setup = SessionSetup(system_prompt, tuple(tools))
        self._plugins = tuple(plugins)
        # Set as the session starts, once the plugins have had their say on the setup.
        self._session: SessionControls | None = None
        self._system_prompt: str | None = None
        self._tools: dict[str, AgentTool] = {}
        self._tool_specs: tuple[ToolSpec, ...] = ()

    async def start(self, session: SessionControls) -> Sequence[ContextEntry]:
        """Have the plugins settle the setup, open the model, and return the log's entries.

        Two tools of one name in the setup raise `DuplicateTool`, and the model is not
        opened.
        """
        setup = self._setup
        for plugin in self._plugins:
            setup = await plugin.before_start(session, setup)
        tools: dict[str, AgentTool] = {}
        for tool in setup.tools:
            if tool.name in tools:
                raise DuplicateTool(tool.name)
            tools[tool.name] = tool
        context = self._log.entries()
        await self._model.__aenter__()
        self._session = session
        self._system_prompt = setup.system_prompt
        self._tools = tools
        self._tool_specs = tuple(
            ToolSpec(tool.name, tool.description, tool.parameters) for tool in setup.tools
        )
        return context

    async def stop(self) -> None:
        """Ask every plugin `after_end`, and close the model even if one fails."""
        try:
            for plugin in self._plugins:
                await plugin.after_end(self._started())
        finally:
            await self._model.__aexit__(None, None, None)

    async def generate(self, context: Sequence[ContextEntry]) -> AssistantMessage:
        return await self._model.generate(
            ModelInput(self._system_prompt, self._tool_specs, tuple(context))
        )

    async def run_tool(self, call: ToolCall) -> str:
        """Run `call` past the plugins, and return the text the model is shown for it.

        Raises the error the call came out with, if no plugin returned text for it: a
        call to a tool the session does not have comes out as `UnknownTool`.
        """
        session = self._started()
        reasons: list[str] = []
        for plugin in self._plugins:
            denial = await plugin.before_tool(session, call)
            if denial is not None:
                reasons.append(denial.reason)
        if reasons:
            return "\n".join(reasons)
        outcome = await self._outcome_of(call)
        for plugin in self._plugins:
            outcome = await plugin.after_tool(session, call, outcome)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def _outcome_of(self, call: ToolCall) -> ToolOutcome:
        tool = self._tools.get(call.name)
        if tool is None:
            return UnknownTool(call.name)
        try:
            return await tool.execute(call.arguments)
        except Exception as error:
            # Handed to the plugins, who decide how the call comes out.
            return error

    def record(self, entry: ContextEntry) -> None:
        self._log.append(entry)

    async def before_idle(self) -> None:
        for plugin in self._plugins:
            await plugin.before_idle(self._started())

    async def on_event(self, event: SessionEvent) -> None:
        for plugin in self._plugins:
            await plugin.on_event(self._started(), event)

    def _started(self) -> SessionControls:
        assert self._session is not None, "the session calls only start before it has started"
        return self._session
