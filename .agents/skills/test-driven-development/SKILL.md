---
name: test-driven-development
description: Development methodology for driving development through tests. Use this when you are adding, enhancing or amending modules.
---

# Prerequisites

- **[codebase-design](../codebase-design/SKILL.md)** — read it first. This skill uses its vocabulary (module, interface, behaviour, implementation, seam, adapter, factory, resource).
- **[testing](../testing/SKILL.md)** — read it first. This skill uses its vocabulary (module under test, test adapter, test harness, ...).

# Test-driven development

## The TDD Cycle

TDD is the red → green loop, and the loop is a feedback loop: the rate of feedback is the speed limit. Each cycle writes one failing test for one **Behaviour**, then only enough implementation to turn it green.

- **Red before green.** Write the failing test first — a behaviour specified before it exists. Then only enough implementation to pass it: no anticipated tests, no speculative features.
- **Red fails for the right reason.** The code compiles, the test runs, and it fails because the behaviour is not implemented — never on a missing symbol or a type error. Build just enough skeleton to get there: a signature and a stub that signals not-implemented, with no implementation behind it.
- **One slice at a time.** One behaviour, one test, one minimal implementation per cycle — a vertical slice from interface to implementation. Each cycle teaches the next; committing to a bulk of tests up front is testing imagined behaviour.
- **Green stays green.** A new red means the last change broke a behaviour the suite already promised; fix backwards before writing forwards.

## Let tests guide design

When developing with TDD you should not try to complete all the design work up front. Start with a minimal factory and interface and evolve it gradually along with your test harness as behaviours you add require.

## Language idioms

The sections above are language-agnostic. When implementing, read the file for the target language:

- [python.md](python.md) — two red → green cycles building `OrderProcessor`, mypy as the compile step, fixtures wiring the fake
- [typescript.md](typescript.md) — two red → green cycles building `OrderProcessor`, `tsc` as the compile step, a setup helper wiring the fake
