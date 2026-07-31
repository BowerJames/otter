# otter

Otter AI — Python monorepo (a [uv](https://docs.astral.sh/uv/) workspace).

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (package manager)
- [just](https://just.systems/) (task runner; runs recipes in the [`justfile`](./justfile))
- Python 3.12+ (managed by uv via `.python-version`)

`uv` and `just` are not Python packages, so they can't be pinned in `uv.lock`; they are installed automatically by [`scripts/bootstrap.sh`](./scripts/bootstrap.sh) if missing (see [Setup](#setup)).

## Setup

### Quick start (recommended)

A single, idempotent command installs any missing prerequisites (`uv`, `just`),
syncs the workspace against `uv.lock`, and enables the pre-commit hook. It is
safe to re-run:

```bash
./scripts/bootstrap.sh
```

### Manual setup

Install dependencies and create the virtual environment:

```bash
uv sync
```

Enable the local pre-commit hook (run once per clone):

```bash
git config core.hooksPath .githooks
```

Install [just](https://github.com/casey/just#installation) if you intend to use
the task-runner recipes (for example `brew install just`, or the upstream
installer `scripts/bootstrap.sh` uses).

## Monorepo layout

Packages live under [`packages/`](./packages):

```
packages/
├── otter_ai_core/     # the otter-ai-core package (import as `otter_ai_core`)
└── otter_ai_logging/  # the otter-ai-logging package (import as `otter_ai_logging`)
```

The repository root is a [virtual uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/)
(`members = ["packages/*"]`), so additional packages can be dropped under
`packages/` without further configuration.

## `otter-ai-core`

`otter-ai-core` is the **driving package** of the monorepo: it owns the core
types and data models a conversation is built from, plus the generic async
streaming runtimes built on top of them. It defines **no LLMs, providers,
APIs, transports, API registry, or `stream()` dispatch** — only the Pydantic v2
data structures, generic async channel and typed event-bus runtimes, an
abortable stream facade layered over the channel, and the seam types a
provider/transport package will implement.

### Context model

- [`Context`](./packages/otter_ai_core/src/otter_ai_core/context/context.py) — the top-level
  conversation (`system_prompt`, `items`, `tools`), JSON-serializable so a
  context can be persisted and replayed elsewhere.
- [`ContextItem`](./packages/otter_ai_core/src/otter_ai_core/context/context_item.py) — the
  `{id, message}` wrapper layer between `Context` and `Message`. The `id` is
  caller/provider-supplied; it is **not** generated inside assistant message
  streams.
- [`Message`](./packages/otter_ai_core/src/otter_ai_core/context/messages.py) — a discriminated
  union of `UserMessage`, `AssistantMessage`, and `ToolResultMessage`.
- Content blocks in [`content.py`](./packages/otter_ai_core/src/otter_ai_core/context/content.py):
  `TextContent`, `ImageContent`, `ThinkingContent`, `ToolCall`.
- [`Tool`](./packages/otter_ai_core/src/otter_ai_core/context/tool.py) — tool definitions whose
  `parameters` accept a JSON-Schema `dict` or a Pydantic `BaseModel` subclass.
- [`Usage`](./packages/otter_ai_core/src/otter_ai_core/context/usage.py) and diagnostics for
  per-turn accounting.

`AssistantMessage` also carries inert provenance (`api`, `provider`, `model`,
`response_model`, `response_id`) and accounting (`usage`, `stop_reason`,
`error_message`) fields. Otter never interprets these — they are preserved so a
context can be replayed by a provider package built on top.

### Quick example

```python
from otter_ai_core import Context, UserMessage, context_item

context = Context(
    system_prompt="You are helpful.",
    items=[
        context_item(
            message=UserMessage(role="user", content="Hi!", timestamp=0),
            id="u1",
        )
    ],
)

# A Context round-trips through plain JSON.
restored = Context.model_validate_json(context.model_dump_json())
assert restored == context
```

### Generic channel runtime

[`channel.py`](./packages/otter_ai_core/src/otter_ai_core/channel.py) is a faithful
Python/`asyncio` port of pi-ai's `EventStream` push-queue. The runtime is a
single-consumer queue split into a read end and a write end sharing one queue:

- `ChannelReader[TEvent]` — the read end; iterate with `async for`.
- `ChannelWriter[TEvent]` — the write end; call `push(event)` for every event
  (including the terminal `done`/`error`), then `end()`.
- `create_channel()` — returns a `ChannelPair[TEvent]` whose `.writer` is
  the `ChannelWriter` and `.reader` is the `ChannelReader`.

Layered over the channel is an **abortable stream facade**
([`stream.py`](./packages/otter_ai_core/src/otter_ai_core/stream.py)):
`StreamClient[TEvent]` (iterate with `async for` / `await anext()`, and call
`abort()` to signal the producer) paired with `StreamBackend[TEvent]` (push /
end, and observe `abort_signal`), sharing one queue and one `asyncio.Event`;
`create_stream()` returns a `StreamPair`. The abort signal is **intrinsic to
the stream** (not a function argument): the producer creates it with
`create_stream()`, the consumer drives it with `abort()`. There
is **no `result()`** — consumers read the terminal `done`/`error` event
directly.

`ChannelReader`, `ChannelWriter`, `StreamClient`, and `StreamBackend` are
runtime objects and are **not** JSON-serializable (unlike `Context`); the
serializable data model is unchanged.

### Other core subpackages

- [`bus.py`](./packages/otter_ai_core/src/otter_ai_core/bus.py) — a structurally
  typed pub/sub bus keyed by a `StrEnum` discriminator. Handlers retain the
  complete event union for variant narrowing, while runtime validation ensures
  each event belongs to the configured discriminator family. The bus is
  programmed to the
  [`Channel`](./packages/otter_ai_core/src/otter_ai_core/interfaces/channel.py)
  interface: it stores a single `_channel: Channel[tuple[str, object]]` (a
  one-way self-loop `Connection[T, T]`) built via an injected factory whose
  default is
  [`create_default_channel`](./packages/otter_ai_core/src/otter_ai_core/default_channel.py).
- [`bidirectional_channel.py`](./packages/otter_ai_core/src/otter_ai_core/bidirectional_channel.py)
  — the bidirectional queue primitive (two cross-wired channels) for APIs that
  keep a live connection (Realtime / Responses):
  `BidirectionalChannelClient` / `BidirectionalChannelBackend` / `create_bidirectional_channel`.
- [`connection.py`](./packages/otter_ai_core/src/otter_ai_core/connection.py) —
  the abortable bidirectional facade layered over it
  (`ConnectionClient` / `ConnectionBackend` / `create_connection`): a two-way
  consumer handle that can iterate, push, and abort — the bidirectional peer
  of `stream.py`.
- [`default_channel.py`](./packages/otter_ai_core/src/otter_ai_core/default_channel.py)
  — the self-contained, `asyncio.Queue`-backed default implementation of the
  [`Channel`](./packages/otter_ai_core/src/otter_ai_core/interfaces/channel.py)
  protocol (`DefaultChannel` / `create_default_channel`). A `Channel[TEvent]`
  is a one-way self-loop `Connection[TEvent, TEvent]` — a single object that is
  both the reader and the writer over one queue. Do not confuse the three
  near-names: `Channel` is the **protocol** (in `interfaces/`), `channel.py` is
  the underlying **queue primitive** (`ChannelReader` / `ChannelWriter` /
  `create_channel`, still used by `stream.py` / `bidirectional_channel.py`), and
  `DefaultChannel` is its **default implementation**.
- [`model_connection/`](./packages/otter_ai_core/src/otter_ai_core/model_connection/)
  — the typed two-way event protocol (`ClientContextEvent` /
  `ServerContextEvent`) and typed connection aliases
  (`ModelConnectionClient` / `ModelConnectionBackend`); it specializes
  [`connection.py`](./packages/otter_ai_core/src/otter_ai_core/connection.py)
  with otter's model-connection event protocol. `CreateResponse` carries
  advisory per-request `model` / `thinking_level`
  overrides, and the protocol adds two **stateful-connection** session ops —
  `compaction.create` / `compaction.done` and `branch.move` / `branch.moved` —
  whose `*.done` / `*.moved` confirms carry `error_message` so a server can
  report an unsupported op. (Stateless providers rebuild context each turn and
  ignore these; see #118.)
- [`default_model_controller/`](./packages/otter_ai_core/src/otter_ai_core/default_model_controller/)
  — the high-level conversation driver built on a `ModelConnectionClient`:
  `DefaultModelController` (implements the `ModelController` Protocol defined in
  [`interfaces/`](./packages/otter_ai_core/src/otter_ai_core/interfaces/); async,
  confirmation-awaiting `add_message` / `generate` / `abort` / `compact` /
  `branch`, idle/busy tracking, no-strand teardown of in-flight commands) and
  `State` (the idle/busy latch + closing flag). Its `bus` is a generic `Bus`
  keyed on `ServerContextEventType`. `compact` / `branch` target **stateful**
  connections and return the confirm verbatim (`error_message` = refusal).
  `AgentLoop` depends on the `ModelController` Protocol, not the concrete class.
  Re-exported at the top level (`ModelController` / `DefaultModelController` /
  `State`).
- [`builder.py`](./packages/otter_ai_core/src/otter_ai_core/builder.py) — the
  generic `BuilderFn[TOptions, TResult]` alias a producer seam folds onto.
- [`provider_api_model_options/`](./packages/otter_ai_core/src/otter_ai_core/provider_api_model_options/) —
  pure-data enumerations/types (`KnownApis`, `KnownProviders`, `ThinkingLevel`)
  a dispatch layer keys on.

No provider-side seam type is defined for the bidirectional/connection runtime
yet; a connection-level seam will be added in a future dispatch package.

```python
import asyncio

from otter_ai_core import create_channel


async def main() -> None:
    wiring = create_channel()
    reader = wiring.reader
    writer = wiring.writer

    async def produce() -> None:
        for i in range(3):
            writer.push(i)
        writer.end()  # signal end-of-stream (idempotent)

    task = asyncio.create_task(produce())
    received = [event async for event in reader]  # [0, 1, 2]; iteration ends at end()
    await task
```

Otter defines the runtime and types only — **no providers, no registry, no
`stream()` dispatch**.

### Session manager

[`session_manager/`](./packages/otter_ai_core/src/otter_ai_core/session_manager/)
adds a **per-session persistence layer**: a conversation that is **persisted**
(by a swappable backend), **restorable** (rebuilt from the store),
**observable** (typed `Bus` notifications), **branchable** (rewind/diverge
without mutating history), **compactable** (collapse a long history to a
summary + retained tail), and **updatable** (amend a recorded item in a
strictly append-only fashion — the one capability upstream `pi` lacks, made
first-class here).

It is pure logic + a backend seam — **no LLM, no connection, no catalog, and
no concrete backend** (the in-memory store exists only as test infrastructure).

```
session_manager/
├── entries.py        # SessionEntry union + variants + SessionEntryType (append-only tree)
├── projection.py     # PURE functions: project / apply_compaction_transform /
│                     #   entries_to_items / apply_updates / derive_state
├── store.py          # SessionStore protocol (backend seam — the first generic Protocol in core)
├── controller.py     # SessionStoreController CONCRETE class (owns Bus + asyncio.Lock)
├── events.py         # Bus notifications (ENTRY_APPENDED / ITEM_ADDED / … / TREE_CHANGED)
├── metadata.py       # SessionMetadata / SessionStats / BranchSummaryInput
└── errors.py         # SessionError + SessionErrorCode
```

- [`SessionStore`](./packages/otter_ai_core/src/otter_ai_core/session_manager/store.py)
  *(generic `Protocol`)* — the per-session backend seam (memory / JSONL /
  SQLite / Postgres). The first generic `Protocol` in `otter-ai-core`: a backend
  seam needs both structural typing and a metadata type parameter, which a
  `type` alias cannot express.
- [`SessionStoreController`](./packages/otter_ai_core/src/otter_ai_core/session_manager/controller.py)
  *(concrete)* — an open session: `append_message` / `update_message` /
  `append_compaction` / `move_to` (branch) / `append_*_change` / `append_label` /
  `append_session_name`. Pure logic over a `SessionStore`; observable via its
  `bus`; concurrency-safe via an append `Lock`. Lock-free snapshot reads
  (`projection` / `build_context` / `get_branch`). Tear down with `aclose`
  (or `async with`), mirroring `DefaultModelController`.
- **Pure projection functions** *(concrete, loop-free)* — `project(path)`,
  `derive_state(path)`, `apply_compaction_transform`, `entries_to_items`,
  `apply_updates`: sync, unit-testable with a hand-built list and no store. A
  `SessionProjection` carries an items-only `Context` (`system_prompt=None`,
  `tools=None`) plus derived state (model / thinking level / active tools).

A session is **restorable by construction**: `SessionStoreController(store)` +
`await controller.projection()` rebuilds the current `Context` from any
populated store; re-constructing over the same store always yields an identical
projection.

```python
from otter_ai_core import SessionStoreController, UserMessage, context_item

controller = SessionStoreController(my_store)  # any SessionStore impl
await controller.append_message(context_item(UserMessage(role="user", content="hi", timestamp=0), id="u1"))
await controller.append_model_change("anthropic", "claude-3")
projection = await controller.projection()
print(projection.context.items)        # the projected ContextItems
print(projection.state.model)          # ("anthropic", "claude-3")

# Branch: rewind to an earlier item and diverge — history is never mutated.
await controller.move_to(earlier_tree_id)
```

### Faux model producer

[`faux/`](./packages/otter_ai_core/src/otter_ai_core/faux/) ships a concrete,
**deterministic, API-key-free** model-connection producer
([`FauxModelProducer`](./packages/otter_ai_core/src/otter_ai_core/faux/producer.py))
that pumps a real
[`ModelConnectionBackend`](./packages/otter_ai_core/src/otter_ai_core/model_connection/model_connection.py)
with scriptable, protocol-conformant `ServerContextEvent` sequences — so a
downstream package can write true end-to-end integration tests of the
connection → controller → agent-loop stack with **no network and no flakiness**.
It is a test double, **not a provider**: no inference, no transport, no
registry, no new seam. The one-call entry point
[`create_faux_model(script)`](./packages/otter_ai_core/src/otter_ai_core/faux/producer.py)
wires a real `DefaultModelController` over a real `create_connection()` pair in one
line.

```
faux/
├── __init__.py    # subpackage facade + __all__
├── script.py      # FauxModelScript + frozen value objects + determinism
│                  #   factories (state-free: factories only; the producer
│                  #   materialises its own counters per instance)
└── producer.py    # FauxModelProducer (drain/pump + spy surface) + FauxModel
                   #   harness + create_faux_model
```

- **Deterministic by default** — monotonic server-assigned item ids
  (`"item-1"`, …), an injectable clock (default opaque ordered ints), zero-cost
  `Usage`, and stable provenance — all materialised **on the producer**, so one
  `FauxModelScript` is shareable across producers without cross-contaminating
  counters. Realism is injectable (`clock_factory=real_clock`, custom ids/usage).
- **Scriptable, not stubbed** — a `FauxModelScript` is an ordered list of
  `FauxResponse`s (text / tool calls / thinking); `stop_reason` is inferred
  (`ToolUse` if any `ToolCall`, else `Stop`) unless set. Script exhaustion is
  **loud** (a terminal `Error` `response.done` — never a hang) or **repeating**
  (`FauxResponseRepeat.LAST`).
- **Abort is integration-testable** — an opt-in per-response or script-level
  `delay` inserts a real in-flight window between `response.started` and
  `response.done`, so a concurrent `controller.abort()` is observable and the
  generation closes with an `Aborted` done. This needs no backend-facade
  changes — it leans on the controller's single-flight contract.
- **Session ops honoured** — `compaction.create` / `branch.move` resolve to
  confirms built from the script, with client-supplied summaries echoed and
  refusals returned (not raised).
- **Spy surface** — `producer.requests` / `.response_count` / `.last_create`
  record the client→server traffic so a test asserts "the loop requested two
  generations and fed back one tool result" without instrumenting the controller.

```python
from otter_ai_core import FauxModelScript, create_faux_model, faux_text_response
from otter_ai_core.context import Role, UserMessage
from otter_ai_core.model_connection import AddUserMessage

script = FauxModelScript(responses=[faux_text_response("hi there")])

async with create_faux_model(script) as model:
    await model.controller.add_message(
        AddUserMessage(message=UserMessage(role=Role.User, content="hello", timestamp=0))
    )
    item = await model.controller.generate()
    assert item.message.content[0].text == "hi there"
    assert [type(e).__name__ for e in model.producer.requests] == [
        "AddUserMessage", "CreateResponse",
    ]
```

## `otter-ai-logging`

`otter-ai-logging` configures the stdlib [`logging`](https://docs.python.org/3/library/logging.html)
module for the monorepo's logging conventions. It depends on nothing but the
standard library.

- **Line format** — `<timestamp_utc> <level> <message>` (ISO-8601 UTC), e.g.
  `2026-07-09T10:56:29Z INFO user 42 authenticated`. Pass `format="json"` to
  `configure_logging` to render each line as a single-line JSON object instead
  (`{"level": ..., "time": ..., "msg": ...}`).
- **Scoped context** — `logging_context(**fields)` binds structured fields (a
  session/request ID, a user ID, a hook name, …) to the current scope for the
  lifetime of a block; every log line within it carries them. In text they
  appear as a trailing `key=value …` suffix; in JSON as top-level keys written
  *before* the reserved fields. Fields merge on nesting and unwind cleanly on
  exit, and propagate across `asyncio` tasks with no per-call-site plumbing.
- **Stream routing** — `DEBUG`/`INFO`/`WARNING` → stdout, `ERROR` → stderr
  (stderr only; never mirrored). `ERROR` is the alertable channel.
- **Level** — driven by the `LOG_LEVEL` environment variable (one of
  `DEBUG`/`INFO`/`WARNING`/`ERROR`), defaulting to `INFO`. The canonical level
  set is four levels; `CRITICAL`/unknown values raise `ValueError`.

Application code configures logging once at startup; libraries and modules
obtain a logger with the stdlib idiom `logging.getLogger(__name__)`.

```python
from otter_ai_logging import configure_logging, logging_context

configure_logging()  # reads LOG_LEVEL (default INFO); idempotent
# configure_logging(format="json")  # opt in to single-line JSON output

import logging

log = logging.getLogger(__name__)
log.info("user %s authenticated", 42)        # -> stdout
log.error("database connection refused")     # -> stderr (alertable)

# bind scope-bound structured fields; every line inside carries them
with logging_context(session_id="call-123", user_id=42):
    log.info("authenticated")
    # -> stdout: ... INFO authenticated session_id=call-123 user_id=42
```

## Tooling

| Tool        | Purpose                 | Config                         |
| ----------- | ----------------------- | ------------------------------ |
| [ruff]      | Linting + formatting    | `[tool.ruff]` in `pyproject.toml`  |
| [mypy]      | Static type checking    | `[tool.mypy]` in `pyproject.toml`  |
| [pytest]    | Testing (incl. `async`) | `[tool.pytest.ini_options]`    |
| [semgrep]   | Docstring policy        | `semgrep.yml`                  |

[ruff]: https://docs.astral.sh/ruff/
[mypy]: https://mypy-lang.org/
[pytest]: https://docs.pytest.org/
[semgrep]: https://semgrep.dev/

### Run checks

```bash
uv run pytest                         # run tests (async tests run automatically)
uv run ruff check .                   # lint
uv run ruff format --check .          # format check (use without --check to apply)
uv run mypy                           # type check
```

### Pre-commit hook

Once enabled, every `git commit` runs:

1. `ruff check --fix` and `ruff format` on staged Python files, **auto-staging** the fixes, then
2. `mypy` on the whole workspace.

The commit is rejected if any check fails. Tool versions are pinned via `uv run` (see `uv.lock`).

### Docstring policy (coding without comments)

Docstrings are not used in `*/src/*.py`: documentation comments go stale when code changes, so the codebase favours self-documenting code instead. The `no-module-docstring`, `no-class-docstring`, and `no-function-docstring` rules in [`semgrep.yml`](semgrep.yml) error whenever a module-, class-, or function/method-level docstring is present under any `*/src/` directory.

```bash
uv run semgrep scan --config semgrep.yml --error .
# or
just semgrep-rules
```
