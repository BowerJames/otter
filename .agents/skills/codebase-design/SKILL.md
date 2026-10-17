---
name: codebase-design
description: Designing, wiring, testing and laying out simple, flexible, maintainable codebases as components joined by adapters, with one shared vocabulary for dependency injection, testing, test-driven development and project structure. Use when the user wants to design or implement changes in the codebase, such as creating or changing components, adapters, factories or entrypoints, wiring dependencies, writing or structuring tests, test-driving a change, deciding where code belongs, or adding code to a codebase that does not follow this structure yet.
---

# Codebase Design

Design components that can represent a wide range of capability behind a small interface, fully testable through their interface and constructor. A program is an assembly: components are its nodes, each declaring the one interface it provides and a port for each dependency it needs, and adapters are its edges, joining a port to the components that satisfy it. Use this language and these principles wherever code is being designed or restructured.

The aim is to provide:

- leverage for callers
- locality for maintainers
- flexibility for designers
- testability for everyone.

## Topics

This file holds the vocabulary and principles. Each topic file builds on them; read the one for the work at hand:

- **[dependency-injection](dependency-injection.md)** — how entities get their dependencies: what a constructor receives, and the factories and composites that call it. Read it when wiring dependencies, deciding whether a dependency belongs in a component's constructor or its interface, writing or changing a factory or a composite, or fixing components that create or fetch what they need.
- **[testing](testing.md)** — testing entities through their constructors and interfaces: one behaviour per test, a fake for every port, foreign components through their own test hooks, unit tests by default. Read it when writing or structuring tests, deciding what to test, passing fakes for ports, testing edge components against foreign components, or fixing tests that break under refactor.
- **[test-driven-development](test-driven-development.md)** — driving development through tests: the red → green → refactor loop, one behaviour per cycle, the constructor, interface and ports evolving with the tests. Read it when adding, enhancing or amending components, edge components or adapters.
- **[project-structure](project-structure.md)** — where code lives on disk: components, adapters, contracts, factories and entrypoints each in their own directory, imports pointing inward, tests mirroring the source tree, legacy code met as a foreign component. Read it when creating components, adapters, contracts, factories, entrypoints or tests, deciding where code belongs, or adding code to a codebase that does not follow this structure yet.

## Glossary

Use these terms exactly — don't substitute "module," "service," "API," or "boundary." Consistent language is the whole point.

### Entities and their surfaces

**Entity** — a code construct: a class, function, type or any other structure that exists within the language syntax.

**Interface** — everything a caller must know to use an entity correctly: the type signature, but also invariants, ordering constraints, lifecycle, error modes and performance characteristics. A component's error modes include the errors its ports let propagate.

_Avoid_: API, signature (too narrow — they refer only to the type-level surface).

**Implementation** — the body of code that sits behind an interface.

**Constructor** — the one function that creates an entity. It takes everything required to measure the entity's behaviours, and it reaches no resource.

**Configuration** — values in the constructor of an entity that alter behaviour without editing the implementation. Distinct from a port, which is an interface, not a value.

**Behaviour** — something measurable and verifiable by a test through an entity's interface and constructor.

**Capability** — what an entity can do for a caller through its interface, counting what the entities passed to its constructor provide. The same behaviour gives a different capability for each entity that can satisfy a port.

### The assembly

**Component** — a package with one interface, an implementation, a constructor, and a port for each of its dependencies. It is self-contained: it depends on its own package, the contracts, the language and foreign libraries, never on another component or an adapter. Only these packages are components: code inside an implementation is not a component, whatever its shape.

_Avoid_: module, unit, service.

**Port** — one named dependency of a component, declared in its constructor and typed by an interface: one the component declares itself, or a contract. A component has one port for each thing it depends on, and each port holds only what the component calls on that dependency. A port can take a sequence of implementations of its interface, as a tool runner takes the tools it offers.

_Avoid_: dependency interface, required interface (a port is named; its type is an interface).

**Adapter** — an entity that joins components: it satisfies one component's port, or a contract, by calling other components through their interfaces. Its constructor takes the interfaces of the components it calls, contracts and configuration. It exists only to translate or to wrap: where a component's interface already satisfies a port, the component is passed to the port directly and there is no adapter. It reaches no resource and takes no foreign object.

**Decorator** — an adapter that takes the very interface it satisfies, a port's interface or a contract, and wraps it: `retrying`, `truncated`. It is the one adapter whose constructor takes the interface of a port.

**Contract** — an interface or data carrier that more than one component uses, and that means the same thing to each of them: `AgentTool`, a tool a model can call; `Currency`. It starts in the component that needs it and is promoted to the contracts package when a second component needs it and it means the same thing to both. Where two components need the same shape for different meanings, each keeps its own and an adapter translates between them. A contract has no behaviour.

_Avoid_: shared interface, common interface, domain interface (names that say only that something is shared, or where it sits).

**Data carrier** — a type that holds data and reaches no resource: `Order`, `Receipt`, `Currency`. It has fields and no methods, and its only invariants are the ones its types express. Validation beyond the types, and any computation over a data carrier, however small, belongs in the implementation of a component. It has no implementation behind it, so entities take and return it as its concrete type, not through an interface of its own, and it has no tests of its own.

_Avoid_: model (overloaded with ORMs and machine learning), DTO, entity (already means any code construct).

**Factory** — anything that calls the constructor of an entity and returns the entity.

**Composite** — an assembly of components and adapters presented as one component: a factory whose parameters are the composite's ports and whose return value is one interface, with everything it builds inside hidden from its callers.

**Assembly** — the graph of components and adapters that factories build: the whole program, as an entrypoint builds it, or part of it, inside a composite.

_Avoid_: configuration (already means the values in a constructor), container, wiring.

### The edge of the program

**Foreign component** — a library, framework or runtime the project uses but did not write, the standard library included. It sits outside the assembly and meets it only through foreign interfaces. Some provide to the project: an HTTP client, a model provider's SDK, the clock. Some require from it: a web framework calls routes, a CLI runner calls commands, the logging system calls handlers, an SDK's tool runner calls tools.

_Avoid_: external component (external already describes a composite's ports, seen from outside), third-party (excludes the standard library and the runtime).

**Foreign interface** — an interface a foreign component defines: the `httpx.Client` a component calls, the `APIRouter` a framework mounts.

**Edge component** — a component with a foreign interface on one side. An edge component should face one foreign component: where it faces more, say why.

- An **inbound edge component** has a foreign interface: a foreign component calls it, on its own initiative. A FastAPI router, a Click command, a `logging.Handler`.
- An **outbound edge component** has a foreign dependency: it calls a foreign component, which its constructor takes. `StripePayments` takes an `httpx.Client`; `OpenAIModel` takes the SDK's client. A callback the foreign component makes during that call, such as a tool the SDK runs, is part of the same conversation, so this component presents it in the foreign shape.

**View** — a minimal interface the project declares for the part of a foreign interface an edge component touches, declared only when the foreign component offers no test hook of its own. Outbound, it describes what the component uses: a `send` and `recv` view of a socket connection. Inbound, it describes what the framework calls on the component: a command as a function from arguments to an exit code. The foreign object satisfies it by shape, and tests satisfy it with a fake.

_Avoid_: wrapper port, adapter port (a view is not a port: no behaviour of the project's sits behind it).

**Entrypoint** — the code the outside world is pointed at to start the program: a script, a server's app object, the file a worker loads. It reads the environment, acquires the resources whose lifetime is the process, such as secrets, settings and connection pools, calls the factories that build the assembly, registers the inbound edge components with the foreign components that call them, starts those foreign components, and closes what it acquired. It holds no behaviour. A program has one for each way it is started; a library has none.

_Avoid_: startup, bootstrap, composition root, main (one entrypoint among several).

**Resource** — something external from the software's environment or a test's control: the filesystem, the network, the clock, randomness, environment variables, a database. A test cannot decide the outcome of an interaction with a resource, so behaviour that crosses one must be tested by substituting it.

**Legacy code** — project code that does not follow this structure yet. It is treated as a foreign component.

_Avoid_: old code, tech debt (both judge the code instead of naming its role).

### What each role wants

**Leverage** — what callers want from a component: a higher range of capability per unit of interface they learn.

**Locality** — what maintainers want from a component: change, bugs, knowledge, and verification concentrate in one place rather than spreading across callers. Fix once, fixed everywhere.

**Flexibility** — what designers want from a component: the ease with which one can extend or broaden the range of capabilities sitting behind an interface.

## Design Considerations

When designing an interface, ask whether you can maintain the range of capabilities but:

- Reduce the number of methods
- Simplify the parameters
- Hide more complexity behind the interface
- Add sensible defaults

## When to make a component

A component is the unit that tests are written against, and a connection between two components costs a port, often an adapter, wiring in a factory and a fake. So the default is not to make one.

**Default:** new behaviour goes inside an existing component's implementation. An implementation can grow to as many files as it needs without becoming a second component, and its internal code is structured however suits it.

Split behaviour out into its own component when one of these holds:

- **It needs its own test surface.** Its behaviours are worth measuring on their own, through their own constructor and interface, and not only through the component that uses it.
- **A second component needs it.** Two components cannot share implementation code, so behaviour both need has to sit behind an interface of its own.
- **It must be swappable.** The component that uses it should work with more than one version of it, each passed to the same port.
- **It faces a foreign component.** Code that calls a library which reaches a resource, or that a framework calls, is an edge component, so the components behind it never meet the foreign interface.

**Watch for code shared between adapters.** It is not forbidden, but it is often the first sign of one of these reasons. Before sharing, ask what the code is:

- **Behaviour, including the translation of a provider's format**, is usually a component, passed to the constructors of the adapters that need it, rather than code they each copy or import.
- **Something too small for a component**, a line of formatting or a constant, is often best left as two copies, especially when they are likely to change apart.

When neither fits, sharing is a judgement call. Where the shared code goes is covered by [project-structure](project-structure.md#8-name-a-package-for-what-it-is-not-for-being-shared).

## Principles

- **Capability is passed as a dependency.** Only data carriers, configuration values, interfaces and, for an edge component, foreign objects appear in a constructor, so wherever an interface appears, any implementation of it can be passed instead. Capability is never shared by importing code.
- **Capability is measured against the interface, not the implementation.** A component can provide a large range of capabilities through what is passed to its ports.
- **An entity's constructor is not part of its interface.** Adding complexity to the constructor of a component does not increase the complexity of its interface and therefore does not reduce the leverage.
- **An entity's interface and constructor are the test surface.** Callers and tests drive through the same interface. Behaviours can be measured through the interface and constructor.
- **A component is self-contained.** It depends on nothing but its own package, the contracts, the language and foreign libraries: no other component, no adapter. Anything else it needs is a port.
- **A port between two components is a cost paid for independence.** It should buy something: a separate test surface, a second user, the ability to swap, or a foreign component kept at the edge.
- **A component's interface is either the project's or foreign, never a mix.** Foreign types appear only in the foreign interface they belong to, and a foreign interface is used by only one project component: the edge component facing that foreign component. An entrypoint uses them too, but only to register and start foreign components.
- **The code bound to a foreign interface is a humble shell.** An edge component keeps the code that calls, or is called by, the foreign component as thin as it can, puts its translation in plain functions in its own package, and reaches everything else through its ports.
- **Who acquires a resource follows its lifetime.** A resource that lives as long as the process is acquired by the entrypoint. A resource that lives for one use, such as a call, a session or a conversation, is acquired by the component whose behaviour defines that use, through what its constructor took, when it is called. Building the assembly never reaches a resource.
- **A component with a lifecycle opens sessions; it is not a session.** Its interface returns the session from an opening call, so the component stays stateless and every method of the session is always valid. Where a foreign interface forces the component itself to be the session, it may be one: say why, and avoid it wherever there is a choice.

## Errors

- **An error propagates by default.** Code that cannot handle an error lets it pass through unchanged.
- **An error is handled or propagated, never wrapped.** Catching an error to raise a different one in its place hides where it came from. Handling means deciding the outcome: an edge component that turns a card decline into a `false`, or a router that turns a declined payment into an HTTP 402, has handled it.
- **An entity defines an error only when its own implementation determines it, and then it owns it.** A component that refuses an order defines that error in its own package. An adapter that determines an error of its own defines it in the adapter's package. Neither defines errors for failures that belong to something else.

## Designing for testability

Good entities make testing natural:

1. **Constructors accept dependencies, they don't create them.**
2. **Side effects go through a port.** The implementation returns results, and anything else it causes is a call on a port, where a fake can observe it.
3. **Small surface area.** Fewer methods = fewer tests needed. Fewer params = simpler test setup.

## Relationships

- A **Component** has exactly one **Interface** (the surface it presents to callers and tests) and one **Port** for each dependency.
- **Capability** is a property of an **Entity**, measured against its **Interface**.
- An entity can have many **Factories** but only one **Constructor**.
- A **Port** belongs to the component that declares it. It is typed by an interface the component declares itself, or by a **Contract**; never by another component's interface.
- A port is satisfied by a component whose interface satisfies it as it is, by an **Adapter** that translates for one, by a **Decorator** wrapping either, or by a foreign object that already has its shape and needs no translation, such as the standard library's clock.
- An **Adapter** satisfies the whole of one component's port, or one contract, and belongs to its owner. It defines no port of its own: anything with behaviour behind it that the adapter needs is a component or a contract, passed to its constructor.
- An adapter is combined with another at runtime, never by importing it: a factory passes one to the other's constructor, typed as the interface it satisfies.
- A **Composite** is a factory: its parameters are its ports, and it returns one interface.
- A **Foreign component** meets the assembly only through **Edge components**, and an **Entrypoint**, which registers and starts it. **Legacy code** is met the same way.
- An **Adapter** is told apart from a **Component** by its role, not its shape: it exists to join components, and reaches no resource.

## Rejected framings

- **Capability as a ratio of implementation-lines to interface-lines** (Ousterhout): rewards padding the implementation. We measure capability against the interface instead: the range of capability per unit of interface a caller has to learn.
- **One port per component, holding everything it needs**: it ties together dependencies that change, and are swapped, apart. A component that pays with Stripe and reads the clock would need one adapter satisfying both, so swapping the payment provider would mean touching the clock. A port per dependency lets each be satisfied, swapped and faked on its own.
- **An adapter as anything that satisfies an interface**: it gives one name to two roles. Code that reaches a resource, or that a framework calls, has behaviour of its own and is a component at the edge; an adapter only joins components.
- **The entrypoint as the framework that calls in**: the framework is a foreign component. Calling it the entrypoint clashes with what Python packaging, Docker and `__main__` all call an entry point: the project's own code they are pointed at.
- **The entrypoint as anything whose interface the project did not define**: it would make every library an entrypoint. A library the project calls is a foreign component an outbound edge component faces.

## Language idioms

The vocabulary above, and every topic file, is language-agnostic. Each language has a directory with one file per topic, and each topic file links to its own. When implementing, start with the vocabulary file for the target language:

- [python/codebase-design.md](python/codebase-design.md) — Protocols and Callables as interfaces and ports, a worked `OrderProcessor` component with its ports, an error it owns, an outbound edge component and its factories, a decorator, an inbound edge component, and a component that opens sessions
- [typescript/codebase-design.md](typescript/codebase-design.md) — no classes: interfaces and function types as interfaces and ports, a worked `OrderProcessor` component with its ports, an error it owns, an outbound edge component and its factories, a decorator, an inbound edge component, and a component that opens sessions
