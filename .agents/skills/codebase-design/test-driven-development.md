# Test-driven development

This file uses the vocabulary of [codebase-design](SKILL.md) and [testing](testing.md). Where the files created in each cycle go is covered by [project-structure](project-structure.md).

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

A port is added to the constructor when a behaviour first needs a new dependency, and its fake is written in the same cycle. A behaviour that needs more from a dependency the component already has adds a method to that port's interface, and the port's fake gains the method in the same cycle. A port's interface starts in the component; it becomes a contract only when a second component needs it and it means the same thing to both.

## Edge components and adapters

An edge component is driven by tests in the same way, through its interface and its own constructor. An outbound edge component's cycles pass the library's own test hook, or a fake of its view; an inbound edge component's cycles drive it through its framework's test client. Where a behaviour can only be measured against the real resource, the cycle's test is an integration test.

An adapter is driven through the port's interface or the contract it satisfies, constructed with fakes of the interfaces of the components it calls.

## After the cycles

The cycles build a component against fakes. Once its behaviours are pinned, whatever will satisfy its ports in production is driven by its own cycles: the edge components that face foreign components, and the adapters that join it to other components. The factories, composites and entrypoints are written last: they hold no behaviour, so no cycle drives them.

## Language idioms

The sections above are language-agnostic. When implementing, read the file for the target language:

- [python/test-driven-development.md](python/test-driven-development.md) — two red → green → refactor cycles building `OrderProcessor`, mypy as the compile step, fixtures passing the fake to the constructor
- [typescript/test-driven-development.md](typescript/test-driven-development.md) — two red → green → refactor cycles building `OrderProcessor`, `tsc` as the compile step, a setup helper passing the fake to the constructor
