# Testing

This file uses the vocabulary of [codebase-design](SKILL.md) exactly, especially one of its principles: an entity's interface and constructor are the test surface.

## Glossary

**Entity under test** — the entity whose constructor and interface tests are driven through: a component, an edge component included, or an adapter.

_Avoid_: module under test, unit under test, system under test, SUT, code under test.

**Fake** — a stand-in that satisfies an interface the **Entity under test**'s constructor takes, in place of what satisfies it in production: a port's interface, a component's interface, a contract, or a view. Like every implementation of an interface, it satisfies the whole of it.

_Avoid_: test adapter (an adapter is an edge between components), test double (an outside taxonomy), stub and spy, mock as a verb for all substitution.

**Test hook** — what a foreign component offers for its own testing, reaching no resource: `httpx.MockTransport`, a web framework's test client, a CLI runner's in-process runner. A test passes it to an edge component, or drives an edge component through it, in place of the real resource.

**Test harness** — the software that executes tests and reports behaviour present or absent; the framework but also helper functions, defaults and fakes.

_Avoid_: test framework (too restrictive, doesn't cover the helper functions and fakes), test suite, mocking library.

**Unit test** _(Michael Feathers)_ — a test that verifies a **Behaviour** of the **Entity under test** through its interface, with every port satisfied by **fakes** and every foreign object replaced by a **test hook** or a fake of a view: it talks to no **Resource**, runs in under 0.1 seconds, and localises errors to the entity under test and not its dependencies.

**Integration test** — a test that verifies a **Behaviour** of an edge component against the **Resource** it reaches. It is used only when the behaviour cannot be measured with fakes or a test hook.

_Avoid_: contract test (a contract is already a shared interface), and integration test as a name for any test that covers more than one entity.

**End-to-end test** — a test that runs an entrypoint with the production factories, to show that the assembly is wired together correctly. Optional: a project has them only when it wants that check.

_Avoid_: acceptance test, system test, smoke test.

## What makes a good test

A good test verifies one **Behaviour** of one **Entity under test** — nothing else.

- **Through the constructor and interface.** It calls the constructor of the entity under test with fakes and configuration, drives the entity through its interface, and observes outcomes only through the interface and the fakes. The implementation can change entirely while behaviour holds; the test doesn't notice.
- **Never through a factory.** A factory builds production entities, and they reach resources when called, so a unit test never calls one.
- **Reads like a specification.** Named for the behaviour it verifies — "charges the payments port the order total" — so the suite is a list of behaviours, and the **test harness** reports each present or absent. A name promising one behaviour while the assertions check another is a test carrying two behaviours.
- **One behaviour, one set of conditions.** A test is one exercise of one behaviour; a second condition is a second test.
- **Independent expectations.** The expected outcome comes from an independent source of truth: a worked example, a known-good value, test harness code, the spec. Never from running the implementation.

## Test through ports

A test never works against internals: pick the **Entity under test**, call its constructor with a fake for every port, then drive and observe through the interface and the fakes.

- **A port is satisfied by a production component or adapter in production, and a fake in tests.** A test cannot decide the outcome of an interaction with a **Resource**, so nothing that reaches one is passed to a port in a unit test.
- **Pass a fake for every port.** Each port has its own fake: to control what comes in, to observe what goes out, and to localise failures to the entity under test. A behaviour that only touches one port is arranged and observed through that port's fake alone.
- **Set configuration through the constructor.** A behaviour that depends on a configuration value is tested by constructing the entity with that value.
- **An error the entity determines is a behaviour.** It is tested like any other: arrange the conditions through a fake, and observe the error at the interface. An error that only propagates from a port belongs to whatever determined it, and is not tested again here.
- **A lifecycle is a behaviour.** For a component that opens sessions, what the session does once opened, and what is released when it closes, is tested through the opening call, as a caller uses it.

## Testing at the edge

- **Adapters.** An adapter is an entity under test like any other: its interface is the port's interface or the contract it satisfies, and it is constructed with fakes of the interfaces of the components it calls. It reaches no resource, so its tests are unit tests. A decorator is constructed with a fake of the interface it wraps.
- **Outbound edge components.** An outbound edge component's constructor takes a foreign object, so the test passes the library's own test hook, such as an HTTP client on a fake transport, or a fake of the component's view where the library has none. Where that measures the behaviour, the test is a **unit test**. Where the behaviour can only be measured against the real resource — a query that only the database can judge — it is an **integration test**. The plain functions an edge component keeps its translation in are measured through the component's interface, like any other implementation.
- **Inbound edge components.** An inbound edge component's interface is foreign, so it is driven the way its foreign component calls it: through the framework's test client, given an instance built by the component's constructor with a fake for each port. Where the framework offers no test hook, the test calls the component through its view. Where the test client reaches no resource, as a web framework's in-process client does not, the test is a **unit test**.
- **Foreign components.** A foreign component is not the project's code, so it has no tests of its own. Legacy code is treated the same way: it is reached through an edge component, which is tested like any other.
- **Factories, composites and entrypoints.** They hold no behaviour, so they have no unit tests. Only an end-to-end test exercises them.

## Data carriers

A data carrier is not an entity under test. It holds no behaviour, and its only invariants are the ones its types express, so it has no tests of its own. A contract has none either: it is an interface or a data carrier, and is tested through the entities that implement or use it.

## Kinds of test

Unit tests are the default, and they carry the behaviours. An integration test is written only where a behaviour of an edge component can only be measured against the real resource. End-to-end tests are optional. A project adds them when it wants a check that the assembly is wired together, and a behaviour is never measured only there.

Integration and end-to-end tests are kept apart from the unit tests, so the unit tests stay fast and need no environment.

Where tests and fakes live on disk is covered by [project-structure](project-structure.md).

## Anti-patterns

Each is a good-test criterion violated:

- **Tautological test.** The expected value comes from the implementation itself — the test calls the source to compute what to assert — so it agrees by construction and can never disagree with the code. The fix is an independent oracle: compute the expectation in the test, or take it from a worked example, a known-good value, the spec — never from the source code.
- **Implementation-coupled test.** It verifies something that isn't **Behaviour** — reaching past the interface to mock private internals, call private methods, or check outcomes through a side channel the interface doesn't expose. The tell: it breaks under refactor while behaviour is unchanged. The test is on the wrong side of the interface: either it goes through the interface, or the entity under test is the wrong shape.
- **Faked foreign component.** A hand-written fake of a library's whole client stands in where the library offers a test hook. The fake agrees with what its author believed the library does, not with what it does. The fix: pass the library's own object on its test hook, and declare a view, faked in tests, only where it has none.

## Language idioms

The sections above are language-agnostic. When implementing, read the file for the target language:

- [python/testing.md](python/testing.md) — pytest as the harness, a fake for each port, a helper wrapping the constructor, unit tests of an error, an adapter, an outbound edge component on `httpx.MockTransport`, a view, an inbound edge component through FastAPI's `TestClient`, a component that opens sessions, markers for integration and end-to-end tests, the anti-patterns
- [typescript/testing.md](typescript/testing.md) — vitest as the harness, a fake for each port, a helper wrapping the constructor, unit tests of an error, an adapter, an outbound edge component on undici's `MockAgent`, a view, an inbound edge component through Fastify's `inject` and a command through its view, a component that opens sessions, directories for integration and end-to-end tests, the anti-patterns
