---
name: testing
description: Discipline for testing modules through their interfaces. Use when writing or structuring tests, deciding what to test, substituting adapters at seams, fixing tests that break under refactor, or test-driving a change. Requires the codebase-design skill.
---

# Prerequisites

- **[codebase-design](../codebase-design/SKILL.md)** — read it first. This skill uses its vocabulary (module, interface, behaviour, implementation, seam, adapter, factory, resource) exactly, especially two of its principles: a module's interface and factories are the test surface, and a resource is reached through a seam, satisfied by the real adapter in production and a test adapter in tests.

# Testing

## Glossary

**Module under test** — The module whose factories and interface tests are driven through.

_Avoid_: unit under test, system under test, SUT, code under test.

**Test adapter** — an adapter that satisfies a **Seam** of the **Module under test** in place of a production adapter.

_Avoid_: test double (an outside taxonomy; **Adapter** already names the role), stub and spy, mock as a verb for all substitution.

**Test harness** — the software that executes tests and reports behaviour present or absent; the framework but also helper functions, defaults and test adapters.

_Avoid_: test framework (too restrictive, doesn't cover the helper functions and test adapters), test suite, mocking library.

**Unit test** _(Michael Feathers)_ — a test that verifies a **Behaviour** of the **Module under test** through its interface, with every seam satisfied by **test adapters**: it talks to no **Resource**, runs in under 0.1 seconds, and localises errors to the module under test and not its dependencies.

## What makes a good test

A good test verifies one **Behaviour** of one **Module under test** — nothing else.

- **Through the factory and interface.** It drives the module under test and observes outcomes only through its interface (including test adapters at seams), the same surface every caller crosses. The implementation can change entirely while behaviour holds; the test doesn't notice.
- **Reads like a specification.** Named for the capability it verifies — "charges the gateway the order total" — so the suite is a list of behaviours, and the **test harness** reports each present or absent. A name promising one behaviour while the assertions check another is a test carrying two behaviours.
- **One behaviour, one set of conditions.** A test is one exercise of one behaviour; a second condition is a second test.
- **Independent expectations.** The expected outcome comes from an independent source of truth: a worked example, a known-good value, test harness code, the spec. Never from running the implementation.

## Test through seams

A test lives at a seam, never against internals: pick the **Module under test**, construct an entity through a factory, drive and observe through the interface and test adapters.

- **Substitute at every seam.** Whatever the seam fronts — a **Resource** or a collaborator — a **test adapter** satisfies it in the test: to control what crosses inward, to observe what crosses outward, and to localise failures to the module under test.

## Anti-patterns

Each is a good-test criterion violated:

- **Tautological test.** The expected value comes from the implementation itself — the test calls the source to compute what to assert — so it agrees by construction and can never disagree with the code. The fix is an independent oracle: compute the expectation in the test, or take it from a worked example, a known-good value, the spec — never from the source code.
- **Implementation-coupled test.** It verifies something that isn't **Behaviour** — reaching past the interface to mock private internals, call private methods, or check outcomes through a side channel the interface doesn't expose. The tell: it breaks under refactor while behaviour is unchanged. The test is on the wrong side of the seam: either it goes through the interface, or the module under test is the wrong shape.

## Language idioms

The sections above are language-agnostic. When implementing, read the file for the target language:

- [python.md](python.md) — pytest as the harness, a fake as the test adapter, a helper wrapping the factory, both anti-patterns
- [typescript.md](typescript.md) — vitest as the harness, a fake as the test adapter, a helper wrapping the factory, both anti-patterns
