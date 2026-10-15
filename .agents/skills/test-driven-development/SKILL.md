---
name: test-driven-development
description: Development methodology for driving development through tests. Use this when you are adding, enhancing or amending modules or adapters. Requires the codebase-design, testing and project-structure skills.
---

# Prerequisites

- **[codebase-design](../codebase-design/SKILL.md)** — read it first. This skill uses its vocabulary (entity, module, interface, behaviour, implementation, constructor, port, configuration, adapter, factory, data carrier, resource).
- **[testing](../testing/SKILL.md)** — read it first. This skill uses its vocabulary (entity under test, test adapter, test harness, ...).
- **[project-structure](../project-structure/SKILL.md)** — where the files created in each cycle go.

# Test-driven development

## The TDD Cycle

TDD is the red → green → refactor loop, and the loop is a feedback loop: the rate of feedback is the speed limit. Each cycle writes one failing test for one **Behaviour**, then only enough implementation to turn it green, then improves the code while the suite stays green.

- **Red before green.** Write the failing test first — a behaviour specified before it exists. Then only enough implementation to pass it: no anticipated tests, no speculative features.
- **Red fails for the right reason.** The code compiles, the test runs, and it fails because the behaviour is not implemented — never on a missing symbol or a type error. Build just enough skeleton to get there: a signature and a stub that signals not-implemented, with no implementation behind it.
- **Every cycle pins a behaviour.** The first cycle included: a test that only constructs the entity verifies nothing. The skeleton the first behaviour needs is built while getting that test to a proper red.
- **One slice at a time.** One behaviour, one test, one minimal implementation per cycle — a vertical slice from interface to implementation. Each cycle teaches the next; committing to a bulk of tests up front is testing imagined behaviour.
- **Refactor only on green.** With the suite green, improve the implementation and the tests: remove duplication, rename, restructure. A refactor changes no behaviour, so no test changes what it verifies, and the suite stays green after every step. A refactor step can be empty.
- **Green stays green.** A new red means the last change broke a behaviour the suite already promised; fix backwards before writing forwards.

## Let tests guide design

When developing with TDD you should not try to complete all the design work up front. Start with a minimal constructor and interface and evolve them gradually along with your test harness as behaviours you add require.

The module's port is added to the constructor when a behaviour first needs something from outside the module. After that, a behaviour that needs something new adds a method to that port, never a second port. The test adapter gains the method in the same cycle.

## Adapters

An adapter is driven by tests in the same way, through the port it satisfies and its own constructor. Where a behaviour can be measured with test adapters for what the adapter's constructor takes, the cycle uses unit tests. Where it can only be measured against the real resource, the cycle's test is an integration test.

## After the cycles

The cycles build a module in the core against a test adapter. Once its behaviours are pinned, its production adapters are driven by their own cycles. The adapter factories, the module factory and the startup code are written last: they hold no behaviour, so no cycle drives them.

## Language idioms

The sections above are language-agnostic. When implementing, read the file for the target language:

- [python.md](python.md) — two red → green → refactor cycles building `OrderProcessor`, mypy as the compile step, fixtures passing the test adapter to the constructor
- [typescript.md](typescript.md) — two red → green → refactor cycles building `OrderProcessor`, `tsc` as the compile step, a setup helper passing the test adapter to the constructor
