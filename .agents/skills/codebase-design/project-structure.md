# Project Structure

This file uses the vocabulary of [codebase-design](SKILL.md) exactly, and the kinds of test from [testing](testing.md) and where they point: entity under test, fake, unit test, integration test, end-to-end test.

Project structure is the mapping of entities onto files. Each role in the assembly has a directory of its own: components are the nodes, adapters are the edges between them, contracts are the vocabulary they share, factories build the assembly, and entrypoints start it. The edge components are components like any other: they are the only ones that meet a foreign component, and nothing else in the program needs to know one is there.

```
src/<package>/
  contracts/                         # interfaces and data carriers promoted out of one component
  components/
    <component_name>/
      interface                      # the component's interface, unless it is foreign
      ports                          # the interfaces its ports are typed by, unless they are contracts
      data                           # the data carriers in its interface and ports
      errors                         # the errors it determines, if any
      views                          # an edge component's views, if it has any
      implementation                 # the component's implementation and constructor, in one file or many
  adapters/
    <component_name>/
      <port_name>/
        <adapter_name>/              # an adapter for that port of that component
    <contract_name>/
      <adapter_name>/                # an adapter of that contract
  factories/
    components/
      <component_name>/              # the factories, composites included, that return that component's interface
    adapters/
      <component_name>/<port_name>/<adapter_name>/ or <contract_name>/<adapter_name>/
  entrypoints/                       # one file for each way the program is started
tests/
  unit/                              # mirrors src/
  integration/                       # mirrors src/
  e2e/
```

## Glossary

**Package** — the directory that holds the code of one component, one adapter, one entity's factories, or the contracts. One component, one package; one adapter, one package; one entity's factories, one package.

_Avoid_: folder (says nothing about ownership), module (overloaded with what a language calls a file).

**Export file** — the one file in a package that other packages import from.

_Avoid_: public API (interface already names what callers must know), barrel (names the mechanism, not the role), entry point (too close to entrypoint).

**Contracts package** — the `contracts` package, holding contracts and nothing else: one file per concept, named for the concept, such as `currency` and `agent_tool`. Nothing with behaviour goes in it: an interface has none, only a shape. `contracts` is a reserved name: no component is called `contracts`.

_Avoid_: domain, utils, common, shared, helpers (names that say only where something sits, or that it is shared, so they accept anything).

**Component name** — the name of a component's package, and of the directories under `adapters` and `factories` that serve it. An edge component is named for what it faces and what it is for: `stripe_payments`, `openai_model`, `orders_router`. A component that faces legacy code is named `legacy_<name>`.

**Contract name** — the name of a contract's file in the contracts package, and of the directory under `adapters` that holds its adapters: `agent_tool` for `contracts/agent_tool`. Component and contract names share the `adapters` directory, so no name is used twice.

**Factory package** — a package under `factories`, holding the factories of one entity at the same path as the entity: `factories/components/<component_name>` for a component, and `factories/adapters/<component_name>/<port_name>/<adapter_name>` or `factories/adapters/<contract_name>/<adapter_name>` for an adapter.

_Avoid_: container, composition root, bootstrap.

## Rules

### 1. Imports point inward

- **The contracts package imports nothing** from outside itself: not the rest of the project, not a foreign library. A contract may use other contracts.
- **A component's package imports its own files, the contracts, the language and foreign libraries.** It never imports another component's package, an adapter, a factory or an entrypoint. A component facing legacy code also imports that code.
- **An adapter's package imports the contracts and the export files of the components it joins.** It never imports another adapter, a factory, an entrypoint or a constructor.
- **A factory package imports whatever it builds from:** components, adapters, other factory packages, the contracts, and the foreign libraries whose objects it builds.
- **An entrypoint imports whatever it needs to start the program.** Nothing imports an entrypoint.

This improves **locality for maintainers** since a change to an adapter, a factory, an entrypoint or another component cannot reach into a component's package.

This improves **testability for everyone** since a component can be constructed with nothing but its own package, the contracts and fakes.

### 2. The components directory holds components, nothing else

- **Every package in `components` is a component.** It has one interface, an implementation, a constructor and a port for each dependency. The directory holds no adapters, factories or entrypoints.
- **A component never imports another component.** A component that needs another adds a port for it. The other component's interface is passed to that port directly when it satisfies it, or through an adapter in `adapters/<component_name>/<port_name>` when it does not.
- **Only an edge component meets a foreign interface.** An inbound edge component presents one; an outbound edge component takes one in its constructor. Every other component reaches what a foreign component offers through a port, satisfied by the edge component facing it. An edge component should face one foreign component: where it faces more, say why in its package.

This improves **locality for maintainers** since every behaviour sits behind a component's interface, every foreign library is confined to the edge components that face it, and every connection between two components is a port.

This improves **testability for everyone** since no component needs another component, or a resource, to be constructed in a test.

### 3. One package per component, with each part in its own file

A component's package is `components/<component_name>`. It holds:

- **interface** — one file with the component's interface, and nothing else. An inbound edge component has no interface file: its interface is foreign.
- **ports** — one file with the interfaces its ports are typed by, unless those are contracts. A component that needs nothing from outside itself has no ports file.
- **data** — one file with the data carriers that appear in the component's interface or ports, unless they are contracts.
- **errors** — one file with the errors the component's implementation determines, if there are any.
- **views** — one file with an edge component's views, if it declares any.
- **implementation** — the component's implementation and its constructor. A package can organise its implementation however it wants: one file, or as many files and directories as it needs. In an edge component, the humble shell and the plain functions it calls are kept apart.
- **the export file** — exports the interface, the ports' interfaces, the data carriers, the errors, the views and the constructor. Nothing else in the implementation is exported.

Each export has its own importers:

- **The interface, the data carriers and the errors** may be imported by the adapters that call the component, by factories, and by entrypoints.
- **The ports' interfaces** are imported by the adapters that satisfy them, by factories, and by fakes.
- **The views** are imported by the component's factories and its tests.
- **The constructor** is imported only by factories and by the component's tests. An adapter or an entrypoint never imports it.

This improves **leverage for callers** since the interface, data and errors files show everything a caller must know and nothing else.

This improves **flexibility for designers** since the ports file shows everything that must be passed to the component to extend its capability.

### 4. An adapter lives under the port or contract it satisfies

| What it satisfies | Its package |
|---|---|
| a component's port | `adapters/<component_name>/<port_name>/<adapter_name>`, where `<component_name>` is the component that declares the port and `<port_name>` is the port's name in its constructor |
| a contract | `adapters/<contract_name>/<adapter_name>`, where `<contract_name>` matches the contract's file in the contracts package |

An adapter defines no port of its own, as [Relationships](SKILL.md#relationships) sets out, so there is no third row.

An adapter satisfies the whole interface. It is named for the component it calls (`order_processor`), or for what it does instead when it is a decorator (`retrying`, `limited`, `truncated`). It translates between the data carriers of the components it joins, or wraps what it is given.

- An adapter imports the port's interface it satisfies, and that component's data carriers, from the component's export file, or the contract it satisfies from the contracts package.
- It imports the interfaces and data carriers of the components it calls from their export files, and receives those components through its own constructor.
- It never imports another adapter. Adapters are combined at runtime: a factory passes one to another's constructor, typed as the interface it satisfies.
- Code that reaches a resource or takes a foreign object is not an adapter but an edge component, in `components`.
- Its export file exports its constructor. Within `src`, only factories import it. Its unit tests import it too.
- An adapter's package organises its contents however it wants. Any error it determines is defined inside its package.

This improves **locality for maintainers** since the path of an adapter names the component and port, or the contract, it serves, and everything one adapter knows is in one package.

This improves **flexibility for designers** since adding a capability to a port is adding one package beside the existing adapters, or passing a component directly.

### 5. A data carrier or interface belongs to the component that declares it, until it is promoted

A data carrier that appears in a component's interface or ports is defined in that component's data file and exported with it, and an interface its ports are typed by is defined in its ports file. A second component that needs the same data declares its own, and the adapter that joins the two translates between them.

A data carrier or interface is promoted to the contracts package when a second component needs it and it means the same thing to both: `Currency`, `AgentTool`. Where the shapes match but the meanings differ, each component keeps its own. Promotion moves the definition into its own file in `contracts`, and each component that used it imports it from there; a component's export file may re-export a contract its interface uses.

A type used only inside one component's implementation stays in that implementation and is not exported. A foreign type stays in the edge component whose foreign interface it belongs to.

This improves **locality for maintainers** since a change to a component's data reaches only that component, its callers and its adapters, and never another component. A change to a contract reaches every entity that uses it, which is why only what means the same everywhere is promoted.

This improves **flexibility for designers** since nothing has to be predicted up front: a contract appears when real use shows that two components share it.

### 6. Factories live in the factories directory, under what they build

Every factory lives in `factories`, at the path of what it builds:

- **A component's factories** live in `factories/components/<component_name>`. They return the component's interface, or the foreign interface an inbound edge component presents. A composite is a factory of the component whose interface it returns, and lives with that component's other factories.
- **An adapter's factories** live in `factories/adapters/<component_name>/<port_name>/<adapter_name>` or `factories/adapters/<contract_name>/<adapter_name>`, the same path as the adapter's package under `adapters`.

No factory lives in a component's or an adapter's package, so the factories directory is the one place where the program is wired.

What a factory may and may not do, including why it is synchronous and reaches no resource, is covered by [dependency-injection](dependency-injection.md#the-factory).

This improves **locality for maintainers** since every factory is found in one directory, and the path of each one names what it builds.

This improves **testability for everyone** since a test can skip the factories, call a constructor and pass fakes.

### 7. Entrypoints start the program

An entrypoint is a file in `entrypoints`, one for each way the program is started, named for it: `cli`, `fastapi`, `worker`. It is what the outside world is pointed at: a `[project.scripts]` entry, the app object a server is given, the file a worker loads.

What an entrypoint does, and why it holds no behaviour, is defined by [Entrypoint](SKILL.md#the-edge-of-the-program). It builds the assembly only by calling factories, never a constructor, and anything worth testing belongs in a component.

A project that is a library, with no process of its own to start, has no entrypoints: its factories are where its users begin.

This improves **locality for maintainers** since how the program starts, and what it reads from its environment, is found in one file per way of starting it, and a change of framework touches only its inbound edge components and its entrypoint.

This improves **testability for everyone** since everything an entrypoint calls can be built in a test without it.

### 8. Name a package for what it is, not for being shared

There is no `utils`, `common`, `shared` or `helpers` package. A helper used by one package stays in that package. Duplicate a small helper until its second or third use, then decide:

- If it meets one of the reasons in [When to make a component](SKILL.md#when-to-make-a-component), it is a component: give it an interface, ports if it needs them, and a package named for what it does (`retry`). Other components reach it through their ports.
- Otherwise the duplication was the right call.

A helper never goes in the contracts package: it carries behaviour, and the contracts package holds contracts only.

**Watch for code shared between adapters**, as [When to make a component](SKILL.md#when-to-make-a-component) describes. Where sharing turns out to be the call, name the shared package for what it does, and never make one adapter import another.

This improves **leverage for callers** since a package's name says what it offers.

This improves **locality for maintainers** since nothing accumulates in a place with no owner.

### 9. Tests mirror the source tree

Tests live in `tests`, outside `src`, split at the top by kind of test: `unit`, `integration` and `e2e`.

- **A test mirrors the path of the entity under test.** The unit tests for `src/<package>/components/<component_name>` are in `tests/unit/components/<component_name>`. The integration tests for an edge component are at the same mirrored path under `tests/integration`. End-to-end tests, where a project has them, are named for the entrypoint they run.
- **A fake lives beside the tests of the entity whose port it satisfies.** It is never under `src`, and never in a shared `fakes` package.
- **A fake needed by the tests of a second entity is duplicated, not shared.** Each entity's tests own their fakes, as each component owns its ports.
- **A stand-in with real behaviour is a component, not a fake.** An in-memory implementation used for local development, or by several entities' tests, lives in `components/in_memory_<name>`, is tested on its own, and is imported from there.

This improves **locality for maintainers** since the tests and fakes for an entity are found from its path alone.

This improves **testability for everyone** since the unit tests can be run on their own by path, with no environment.

### 10. Legacy code is a foreign component

In a codebase that does not follow this structure yet, new code follows it and legacy code stays where it is. The structure meets legacy code the way it meets any foreign component.

- **A component that needs legacy code reaches it through a port.** An outbound edge component in `components/legacy_<name>` satisfies the port by calling the legacy code. The component's unit tests use a fake in its place, as for any port.
- **Legacy code that needs a component calls one of its factories and uses its interface,** as an entrypoint does. It never calls a constructor, and never imports from inside a component.
- **Legacy code that a foreign component calls stays wired as it is.** An existing route keeps working as it is, and becomes an inbound edge component only when a task moves it.

This improves **locality for maintainers** since every crossing between legacy code and the structure is a port or a factory call, so moving a piece of legacy code later changes one place.

### 11. Move toward the structure only along the path of the task

- **The task sets the scope.** Code the task does not change is not moved, renamed or restructured, however far it is from the structure.
- **Make the change easy, then make the easy change.** Where a task changes legacy behaviour, it may move that behaviour into the structure as part of making the change: the behaviour becomes a component, and its old location calls the component's factory.
- **Move only as far as the change needs.** When a move would pull in code the change does not touch, it stops at a port: the rest stays legacy, reached through an edge component.
- **A move changes no behaviour.** It is its own step, done with the tests passing, before or after the behavioural change and never mixed with it.
- **When moving costs more than the task, change the code in place,** and record the move as a follow-up instead of doing it.
- **Restructuring beyond this happens only when asked.**

This improves **flexibility for designers** since the structure grows where the work is happening, without a rewrite up front.

## Language idioms

The rules above are language-agnostic. When implementing, read the file for the target language:

- [python/project-structure.md](python/project-structure.md) — packages with `__init__.py` as the export file, a worked `OrderProcessor` component with its ports, an outbound edge component and its factory, an adapter joining two components, inbound edge components and their entrypoints, a contract with its adapters and a decorator, the tests, legacy code, and checking the rules
- [typescript/project-structure.md](typescript/project-structure.md) — directories with `index.ts` as the export file, a worked `OrderProcessor` component with its ports, an outbound edge component with a view and its factory, an adapter joining two components, inbound edge components and their entrypoints, a contract with its adapters and a decorator, the tests, legacy code, and checking the rules
