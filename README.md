# otter

A lightweight framework for building AI agents.

## Using otter

An agent session runs on a model. Get both from their factories, then prompt the session and
read its stream inside `async with`:

```python
from otter.core.agent_session import Idle
from otter.infrastructure.factories.modules.agent_session import create_agent_session
from otter.infrastructure.factories.modules.model import create_model

model = create_model("chat-completions", "openai", "gpt-5.1", api_key)
session = create_agent_session(model, system_prompt="Be brief.", tools=[...], plugins=[...])

async with session:
    session.prompt("What is in notes.txt?")
    async for event in session.stream():
        if isinstance(event, Idle):
            break
        print(event)  # each UserMessage, AssistantMessage and ToolResultMessage as it joins
```

`create_model` reaches `"chat-completions"` and `"responses"` models served by `"openai"` and
`"zai"`, and `"realtime"` models served by `"openai"`. Pass `session_log=create_file_session_log(path)`
(from `otter.infrastructure.factories.modules.session_log`) to keep the session in a JSON Lines
file and pick it up later.

Tools (`AgentTool`) and plugins (`Plugin`, with hooks before start, around each tool call,
before coming to rest, on each event and after the end) are defined in
`otter.infrastructure.adapters.agent_session.plugin_host`.

## How the code is laid out

The code follows the skills in `.agents/skills`: modules in the core reach nothing outside the
language, and everything that reaches a resource is in the infrastructure around them.

```
src/otter/
  core/
    domain/            # the messages every module speaks in
    agent_session/     # the session loop: queueing, streaming, coming to rest, ending
    model/             # a model shown a whole conversation; what it can take in
    session_log/       # context entries kept as JSON Lines
    chat/              # a chat between a user and a session, shown as a transcript
  infrastructure/
    adapters/
      agent_session/plugin_host/    # a session's model, log, tools and plugins
      model/openai_*/               # chat completions, responses and realtime formats
      session_log/{local_file,in_memory}/
      chat/textual/                 # a session held on a screen drawn with Textual
    factories/{modules,adapters}/   # the only places constructors are called
    entrypoints/tui.py              # the terminal chat, and its startup code
tests/{unit,integration}/           # mirroring src/
tests/e2e/                          # the startup code and production factories
```

`just lint-imports` checks the import rules, and Ruff checks that each constructor is called
only from its factories.

## Development

This project uses [uv](https://docs.astral.sh/uv/) for dependency management.

```sh
uv sync          # create venv and install dev dependencies
```

If you have [just](https://github.com/casey/just) installed:

```sh
just sync    # create venv and install dev dependencies
just check   # lint + import rules + format check + typecheck + every kind of test
just fix     # auto-fix lint issues and reformat
```

Or run the tools directly:

```sh
uv run pytest                 # run the unit tests
uv run pytest -m integration  # run the integration tests
uv run pytest -m e2e          # run the end-to-end tests
uv run lint-imports           # check the import rules
uv run mypy src tests         # type check
uv run ruff check .           # lint
uv run ruff format .          # format
```

### Trying a session out

The `tui` entrypoint opens a terminal chat with an agent session, drawn with
[Textual](https://textual.textualize.io/): outside this repository, install otter with its
`tui` extra to get it.

```sh
just tui --model-name glm-5.3 --model-type chat-completions --provider zai
```

`--model-type` is `chat-completions`, `responses` or `realtime`; the providers `openai` and `zai`
serve the first two, and `openai` alone serves `realtime`.

Add `--session-file session.jsonl` to keep the session in a file: running again with the same
file picks the session up where it left off.

The provider's API key is read from `<PROVIDER>_API_KEY`, which can be set in a `.env` file
at the root of the repository.
