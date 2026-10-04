---
name: testing
description: Discipline for testing modules through their interfaces. Use when writing or structuring tests, deciding what to test, substituting adapters at seams, fixing tests that break under refactor, or test-driving a change. Requires the codebase-design skill.
---

# Prerequisites

- **[codebase-design](../codebase-design/SKILL.md)** — read it first. This skill uses its vocabulary (module, interface, implementation, seam, adapter, resource) exactly, especially two of its principles: a module's interface is the test surface, and a resource is reached through a seam, satisfied by the real adapter in production and a test adapter in tests.

# Testing

## Glossary

Use these terms exactly. The prerequisite terms (module, interface, implementation, seam, adapter, resource) are defined in [codebase-design](../codebase-design/SKILL.md); these are this skill's own.

**Behaviour** — a capability of a module as observable through its interface: an input at the interface, the outcome it produces, and the conditions under which it produces it. Outcomes are observable wherever the interface makes them visible: returned, raised, or crossing a **Seam** (seen by whichever **Adapter** receives them). Behaviour is the thing a test exercises and verifies — if it can't be observed through the interface, it isn't behaviour, it's **Implementation**, and it earns no test of its own.

_Avoid_: functionality (implies no observation point), feature (product scope, not module scope), case/scenario (a test is one exercise of a behaviour, not the behaviour itself), logic (lives in the implementation).

**Module under test** — the module whose behaviour a test exercises: whatever sits behind the interface the test drives. A role, not a kind of module — anything that is a **Module** can occupy it, at any scale. The test reaches it only through that interface, never into its **Implementation**. In a test, its seams are satisfied by test adapters, whatever they front: a **Resource**'s outcomes cannot be decided from inside a test; a production adapter is built for production, not for recording what crosses it; and a collaborator kept real fails the test for its own bugs, not the module under test's. The test adapters draw its boundary — everything inside them runs for real — while a real adapter deliberately kept in place widens the module under test past it, that collaborator's bugs included: choosing what to substitute is choosing what is under test.

_Avoid_: unit under test, system under test, SUT, code under test.

**Test adapter** — an adapter that satisfies a **Seam** of the **Module under test** in place of a production adapter.

_Avoid_: test double (an outside taxonomy; **Adapter** already names the role), stub and spy, mock as a verb for all substitution.

**Test harness** — the software that executes tests and reports behaviour present or absent; the framework but also helper functions, defaults and test adapters.

_Avoid_: test framework (too restrictive, doesn't cover the helper functions and test adapters), test suite, mocking library.

**Unit test** _(Michael Feathers)_ — a test that verifies a **Behaviour** of the **Module under test** through its interface, with every seam satisfied by **test adapters**: it talks to no **Resource**, runs in under 0.1 seconds, and localises errors to the module under test and not its dependencies.

## What makes a good test

A good test verifies one **Behaviour** of one **Module under test** — nothing else.

- **Through the interface.** It drives the module under test and observes outcomes only through its interface (including test adapters at seams), the same surface every caller crosses. The implementation can change entirely while behaviour holds; the test doesn't notice.
- **Reads like a specification.** Named for the capability it verifies — "checking out charges the gateway the cart total" — so the suite is a list of behaviours, and the **test harness** reports each present or absent. A name promising one behaviour while the assertions check another is a test carrying two behaviours.
- **One behaviour, one set of conditions.** A test is one exercise of one behaviour; a second condition is a second test.
- **Independent expectations.** The expected outcome comes from an independent source of truth: a worked example, a known-good value, the spec. Never from running the implementation.

## Test through seams

A test lives at a seam, never against internals: pick the **Module under test**, then drive and observe it only through its interface.

- **Substitute at every seam.** Whatever the seam fronts — a **Resource** or a collaborator — a **test adapter** satisfies it in the test: for control, for observation, for localisation (the three reasons, per the glossary).
- **The cut is the choice.** The substituted seams draw the module under test's boundary; substituting at every seam is the default. A real adapter kept in place widens it past that seam, that collaborator's bugs included — a looser cut, taken only when the real adapter earns its place, not a different kind of test.
- **Any shape, one constant.** A working fake or a verifying mock — whichever the situation wants — provided behaviour crossing the seam stays observable through it.
- **Pre-agree the seams.** Before writing tests, name the seams under test and confirm them — testing everything is testing nothing; agreed seams put effort on the critical paths.

## Test-driven development

TDD is the red → green loop, and the loop is a feedback loop: the rate of feedback is the speed limit. Each cycle writes one failing test for one **Behaviour**, then only enough implementation to turn it green.

- **Red before green.** Write the failing test first — a behaviour specified before it exists. Then only enough implementation to pass it: no anticipated tests, no speculative features.
- **Red fails for the right reason.** The code compiles, the test runs, and it fails on the missing behaviour — never on a missing symbol. Build just enough skeleton for the test to reach its assertion: a signature, a stub, nothing more.
- **One slice at a time.** One behaviour, one test, one minimal implementation per cycle — a vertical slice from interface to implementation. Each cycle teaches the next; committing to a bulk of tests up front is testing imagined behaviour.
- **Green stays green.** A new red means the last change broke a behaviour the suite already promised; fix backwards before writing forwards.

## Anti-patterns

Each is a good-test criterion violated:

- **Tautological test.** The expected value comes from the implementation itself — the test calls the source to compute what to assert — so it agrees by construction and can never disagree with the code. The fix is an independent oracle: compute the expectation in the test, or take it from a worked example, a known-good value, the spec — never from the source code.
- **Implementation-coupled test.** It verifies something that isn't **Behaviour** — reaching past the interface to mock private internals, call private methods, or check outcomes through a side channel the interface doesn't expose. The tell: it breaks under refactor while behaviour is unchanged. The test is on the wrong side of the seam: either it goes through the interface, or the module under test is the wrong shape.
- **Horizontal slicing.** All the tests first, then all the implementation. Bulk-written tests verify imagined behaviour — the shape you guessed, not the behaviour that emerged — and commit to test structure before the implementation has taught you anything. One vertical slice at a time instead.

## Language idioms

The sections above are language-agnostic. When implementing, read the file for the target language:

- [python.md](python.md) — pytest as the harness, mypy as the compile step, fixtures wiring test adapters, fakes by shape, Python gotchas
- [typescript.md](typescript.md) — TypeScript idioms (not yet written)
