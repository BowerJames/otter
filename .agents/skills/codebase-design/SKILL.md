---
name: codebase-design
description: Shared vocabulary for designing deep modules. Use when the user wants to design or improve a module's interface, find deepening opportunities, decide where a seam goes, make code more testable or AI-navigable, or when another skill needs the deep-module vocabulary.
---

# Codebase Design

Design **deep modules**: a lot of behaviour behind a small interface, placed at a clean seam, testable through that interface. Use this language and these principles wherever code is being designed or restructured. The aim is leverage for callers, locality for maintainers, and testability for everyone.

## Glossary

Use these terms exactly — don't substitute "component," "service," "API," or "boundary." Consistent language is the whole point.

**Module** — anything with an interface and an implementation. Deliberately scale-agnostic: a function, class, package, or tier-spanning slice. All of these can be considered modules if they provide implementations fully tested through an interface.

_Avoid_: unit, component, service.

**Interface** — everything a caller must know to use an entity correctly: the type signature, but also invariants, ordering constraints, error modes, required configuration, and performance characteristics.

_Avoid_: API, signature (too narrow — they refer only to the type-level surface).

**Implementation** — what's inside a module, its body of code. Distinct from **Adapter**: a thing can be a small adapter with a large implementation (a Postgres repo) or a large adapter with a small implementation (an in-memory fake). Reach for "adapter" when the seam is the topic; "implementation" otherwise.

**Depth** — leverage at the interface: the amount of behaviour a caller (or test) can exercise per unit of interface they have to learn. A module is **deep** when a large amount of behaviour sits behind a small interface, **shallow** when the interface is nearly as complex as the implementation.

**Seam** _(Michael Feathers)_ — a place where you can alter the behaviour of a module without editing the implementation of the module. Where to put the seam is its own design decision, but it must live in the interface of the module.

_Avoid_: boundary (overloaded with DDD's bounded context).

**Adapter** — a concrete thing that satisfies an interface at a seam. The interface the adapter satisfies can be a subset of the full interface of the thing.

**Resource** — anything a module uses that exists outside its implementation and outside a test's control: the filesystem, the network, the clock, randomness, environment variables, a database. A test cannot decide the outcome of an interaction with a resource, so behaviour that crosses one must be tested by substituting it — a resource is reached through a **Seam**, satisfied by the real **Adapter** in production and a test adapter (fake or mock) in tests.

_Avoid_: dependency (every import is one; most need no mocking), external service (time isn't a service), side effect (describes the crossing, not the thing), boundary (rejected above).

**Leverage** — what callers get from depth: more capability per unit of interface they learn. One implementation pays back across N call sites and M tests.

**Locality** — what maintainers get from depth: change, bugs, knowledge, and verification concentrate in one place rather than spreading across callers. Fix once, fixed everywhere.

**Comments** — any non-executing, human-readable text embedded in the source code. Deliberately syntax-agnostic: this encompasses inline notes, block explanations, and structural entity documentation (like Python docstrings, Javadoc, or rustdoc). Comments serve two distinct architectural roles: at the **Interface**, they document everything a consumer needs to know to use the entity (this should be implementation-agnostic); within the **Implementation**, they explain the domain context and the "why" behind the code.

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

When designing an interface, ask:

- Can I reduce the number of methods?
- Can I simplify the parameters?
- Can I hide more complexity inside?
- Can I add sensible defaults?

## Principles

- **Depth is a property of the interface, not the implementation.** A deep module can be internally composed of small, mockable, swappable parts controlled via seams in its interface.
- **The deletion test.** Imagine deleting the module. If complexity vanishes, it was a pass-through. If complexity reappears across N callers, it was earning its keep.
- **A module's interface is the test surface.** Callers and tests cross the same seam. If you want to test *past* the interface, the module is probably the wrong shape and should be reconsidered.
- **One adapter means a hypothetical seam. Two adapters means a real one.** Don't introduce a seam unless something actually varies across it.

## Designing for testability

Good interfaces make testing natural:

1. **Accept dependencies, don't create them.**
2. **Return results, don't produce side effects.**
3. **Small surface area.** Fewer methods = fewer tests needed. Fewer params = simpler test setup.

## Relationships

- A **Module** has exactly one **Interface** (the surface it presents to callers and tests).
- **Depth** is a property of a **Module**, measured against its **Interface**.
- A **Seam** is where an **Interface** lives.
- An **Adapter** sits at a **Seam** and satisfies an **Interface**.
- **Depth** produces **Leverage** for callers and **Locality** for maintainers.

## Rejected framings

- **Depth as ratio of implementation-lines to interface-lines** (Ousterhout): rewards padding the implementation. We use depth-as-leverage instead.
- **"Boundary"**: overloaded with DDD's bounded context. Say **seam** or **interface**.

## Language idioms

The vocabulary above is language-agnostic. When implementing, read the file for the target language:

- [python.md](python.md) — Protocols and Callables as interfaces, the three shapes of a seam, adapters at seams, testability idioms
- [typescript.md](typescript.md) — no classes: factory functions returning interface-satisfying object literals, the three shapes of a seam, adapters at seams, testability idioms
