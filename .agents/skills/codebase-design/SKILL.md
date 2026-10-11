---
name: codebase-design
description: Shared vocabulary for designing deep modules. Use when the user wants to design or improve a module's interface, find deepening opportunities, decide where a seam goes, make code more testable or AI-navigable, or when another skill needs the deep-module vocabulary.
---

# Codebase Design

Design **deep modules**: a lot of behaviour represented behind a small interface, testable through its interface and dependencies. Use this language and these principles wherever code is being designed or restructured.

The aim is to provide:

- leverage for callers
- locality for maintainers
- flexibility for developers
- testability for everyone.

## Glossary

Use these terms exactly — don't substitute "component," "service," "API," or "boundary." Consistent language is the whole point.

**Interface** — everything a caller must know to use an entity correctly: the type signature, but also invariants, ordering constraints, error modes, required configuration, and performance characteristics.

_Avoid_: API, signature (too narrow — they refer only to the type-level surface).

**Behaviour** — A capability of an entity that can be measured or observed through its interface and adapters.

**Implementation** — The body of code that sits behind an interface. This is what provides the entity its behaviours.

**Module** — An interface coupled with the full range of behaviours that can be represented by an entity satisfying the interface along with the implementations that provide those behaviours.

_Avoid_: unit, component, service.

**Depth** — leverage at the interface: the range of capabilities a caller (or test) could exercise per unit of interface they have to learn. A module is **deep** when a large range of capabilities sits behind a small interface, **shallow** when the interface is nearly as complex as the implementation.

**Seam** _(Michael Feathers)_ — a place where you can alter the capabilities of an entity satisfying a module's interface without editing the implementation. Prefer to place seams in the factories of a module.

_Avoid_: boundary (overloaded with DDD's bounded context).

**Adapter** — a concrete thing that satisfies an interface at a seam. The interface the adapter satisfies can be a subset of the full interface of the thing itself.

**Factory** — The code that creates an entity satisfying a module's interface.

_Avoid_: constructor

**Resource** — anything an entity uses that exists outside the software's environment or a test's control: the filesystem, the network, the clock, randomness, environment variables, a database. A test cannot decide the outcome of an interaction with a resource, so behaviour that crosses one must be tested by substituting it — a resource is reached through a **Seam**, satisfied by the real **Adapter** in production and a test adapter (fake or mock) in tests.

_Avoid_: dependency (every import is one; most need no mocking), external service (time isn't a service), side effect (describes the crossing, not the thing), boundary (rejected above).

**Leverage** — what callers want from a module: more capability per unit of interface they learn. One implementation pays back across N call sites and M tests.

**Locality** — what maintainers want from a module: change, bugs, knowledge, and verification concentrate in one place rather than spreading across callers. Fix once, fixed everywhere.

**Flexibility** — what developers want from a module: the ease with which one can extend or broaden the range of capabilities sitting behind an interface.

## Deep vs shallow

**Deep module** = small interface + lots of implementation:

```
┌─────────────────────┐
│   Small Interface   │  ← Few methods, simple params
├─────────────────────┤
│                     │
│  Deep Implementation│  ← Complex logic hidden
│                     │
└─────────────────────┘
```

**Shallow module** = large interface + little implementation (avoid):

```
┌─────────────────────────────────┐
│       Large Interface           │  ← Many methods, complex params
├─────────────────────────────────┤
│  Thin Implementation            │  ← Just passes through
└─────────────────────────────────┘
```

When designing an interface, ask whether you can maintain the range of capabilities but:

- Reduce the number of methods
- Simplify the parameters
- Hide more complexity behind the interface
- Add sensible defaults

## Principles

- **Depth is measured against the interface, not the implementation.** A deep module can provide a large range of capabilities by being internally composed of adapters provided through seams.
- **The deletion test.** Imagine deleting the module. If complexity vanishes, it was a pass-through. If complexity reappears across N callers, it was earning its keep.
- **A module's factory is not part of its interface.** Adding seams to the factories of a module does not increase the complexity of the module's interface and therefore does not reduce the leverage.
- **A module's interface and factories are the test surface.** Callers and tests drive through the same interface. Behaviours can be measured through the interface or adapters that satisfy the seams.
- **Behaviour is not the same as capability.** A module with a seam satisfied by many adapters exhibits a wide range of capabilities (one for each adapter) through a single behaviour.

## Designing for testability

Good modules make testing natural:

1. **Accept dependencies, don't create them.**
2. **Return results, don't produce side effects.**
3. **Small surface area.** Fewer methods = fewer tests needed. Fewer params = simpler test setup.

## Relationships

- A **Module** has exactly one **Interface** (the surface it presents to callers and tests).
- **Depth** is a property of a **Module**, measured against its **Interface**.
- A **Module** has one or more **Factories**; a **Factory** is not part of the **Interface**.
- A **Seam** belongs in a **Factory** where possible, and in the **Interface** otherwise.
- An **Adapter** sits at a **Seam** and satisfies an **Interface**.
- **Depth** produces **Leverage** for callers.
- **Seams** satisfied by **Adapters** produce **Flexibility** for developers and **Locality** for maintainers: a new adapter adds a capability, and each side of the seam changes and fails in one place.

## Rejected framings

- **Depth as ratio of implementation-lines to interface-lines** (Ousterhout): rewards padding the implementation. We use depth-as-leverage instead.
- **"Boundary"**: overloaded with DDD's bounded context. Say **seam** or **interface**.

## Language idioms

The vocabulary above is language-agnostic. When implementing, read the file for the target language:

- [python.md](python.md) — Protocols and Callables as interfaces, a worked `PaymentGateway` module, two formulations of `OrderProcessor`
- [typescript.md](typescript.md) — no classes: interfaces and function types, a worked `PaymentGateway` module, two formulations of `OrderProcessor`
