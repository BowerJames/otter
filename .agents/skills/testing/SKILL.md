---
name: testing
description: Discipline for testing entities through their constructors and interfaces. Use when writing or structuring tests, deciding what to test, passing test adapters for ports, fixing tests that break under refactor, or test-driving a change. Requires the codebase-design skill.
---

# Prerequisites

- **[codebase-design](../codebase-design/SKILL.md)** — read it first. This skill uses its vocabulary (entity, module, interface, behaviour, implementation, constructor, port, configuration, adapter, factory, data carrier, resource) exactly, especially one of its principles: an entity's interface and constructor are the test surface.

# Testing

## Glossary

**Entity under test** — The entity whose constructor and interface tests are driven through: a module, or an adapter.

_Avoid_: module under test (too narrow — an adapter is tested the same way), unit under test, system under test, SUT, code under test.

**Test adapter** — an adapter that satisfies a **Port** of the **Entity under test** in place of a production adapter. Like every adapter, it satisfies the whole port.

_Avoid_: test double (an outside taxonomy; **Adapter** already names the role), stub and spy, mock as a verb for all substitution.

**Test harness** — the software that executes tests and reports behaviour present or absent; the framework but also helper functions, defaults and test adapters.

_Avoid_: test framework (too restrictive, doesn't cover the helper functions and test adapters), test suite, mocking library.

**Unit test** _(Michael Feathers)_ — a test that verifies a **Behaviour** of the **Entity under test** through its interface, with every port satisfied by **test adapters**: it talks to no **Resource**, runs in under 0.1 seconds, and localises errors to the entity under test and not its dependencies.

**Integration test** — a test that verifies a **Behaviour** of an adapter against the **Resource** it reaches. It is used only when the behaviour cannot be measured with test adapters.

_Avoid_: contract test, and integration test as a name for any test that covers more than one entity.

**End-to-end test** — a test that runs an entrypoint's startup code with the production factories, to show that the entities are wired together correctly. Optional: a project has them only when it wants that check.

_Avoid_: acceptance test, system test, smoke test.

## What makes a good test

A good test verifies one **Behaviour** of one **Entity under test** — nothing else.

- **Through the constructor and interface.** It calls the constructor of the entity under test with test adapters and configuration, drives the entity through its interface, and observes outcomes only through the interface and the test adapters. The implementation can change entirely while behaviour holds; the test doesn't notice.
- **Never through a factory.** A factory builds production entities, and they reach resources when called, so a unit test never calls one.
- **Reads like a specification.** Named for the behaviour it verifies — "charges the port the order total" — so the suite is a list of behaviours, and the **test harness** reports each present or absent. A name promising one behaviour while the assertions check another is a test carrying two behaviours.
- **One behaviour, one set of conditions.** A test is one exercise of one behaviour; a second condition is a second test.
- **Independent expectations.** The expected outcome comes from an independent source of truth: a worked example, a known-good value, test harness code, the spec. Never from running the implementation.

## Test through ports

A test never works against internals: pick the **Entity under test**, call its constructor with a test adapter for every port, then drive and observe through the interface and the test adapters.

- **A port is satisfied by a production adapter in production and a test adapter in tests.** A test cannot decide the outcome of an interaction with a **Resource**, so no production adapter that reaches one is used in a unit test.
- **Pass a test adapter for every port.** Whatever satisfies the port in production, a **test adapter** satisfies it in the test: to control what comes in, to observe what goes out, and to localise failures to the entity under test.
- **Set configuration through the constructor.** A behaviour that depends on a configuration value is tested by constructing the entity with that value.
- **An error the entity determines is a behaviour.** It is tested like any other: arrange the conditions through the test adapter, and observe the error at the interface. An error that only propagates from the port belongs to whatever determined it, and is not tested again here.

## Testing the infrastructure

- **Adapters.** An adapter is an entity under test like any other: its interface is the port it satisfies, and it is constructed with test adapters for whatever its own constructor takes. Where that measures the behaviour, the test is a **unit test**. Where the behaviour can only be measured against the real resource — a query that only the database can judge — it is an **integration test**.
- **Entrypoints.** An entrypoint's translation between the outside world and data carriers is behaviour. Its constructor takes the interfaces it drives, so it is unit tested with a test adapter for each.
- **Factories and startup code.** They hold no behaviour, so they have no unit tests. Only an end-to-end test exercises them.

## Data carriers

A data carrier is not an entity under test. It holds no behaviour, and its only invariants are the ones its types express, so it has no tests of its own.

## Kinds of test

Unit tests are the default, and they carry the behaviours. An integration test is written only where a behaviour can only be measured against the real resource. End-to-end tests are optional. A project adds them when it wants a check that the entities are wired together, and a behaviour is never measured only there.

Integration and end-to-end tests are kept apart from the unit tests, so the unit tests stay fast and need no environment.

Where tests and test adapters live on disk is covered by [project-structure](../project-structure/SKILL.md).

## Anti-patterns

Each is a good-test criterion violated:

- **Tautological test.** The expected value comes from the implementation itself — the test calls the source to compute what to assert — so it agrees by construction and can never disagree with the code. The fix is an independent oracle: compute the expectation in the test, or take it from a worked example, a known-good value, the spec — never from the source code.
- **Implementation-coupled test.** It verifies something that isn't **Behaviour** — reaching past the interface to mock private internals, call private methods, or check outcomes through a side channel the interface doesn't expose. The tell: it breaks under refactor while behaviour is unchanged. The test is on the wrong side of the interface: either it goes through the interface, or the entity under test is the wrong shape.

## Language idioms

The sections above are language-agnostic. When implementing, read the file for the target language:

- [python.md](python.md) — pytest as the harness, a fake as the test adapter, a helper wrapping the constructor, unit tests of an error, an adapter and an entrypoint, markers for integration and end-to-end tests, both anti-patterns
- [typescript.md](typescript.md) — vitest as the harness, a fake as the test adapter, a helper wrapping the constructor, unit tests of an error, an adapter and an entrypoint, directories for integration and end-to-end tests, both anti-patterns
