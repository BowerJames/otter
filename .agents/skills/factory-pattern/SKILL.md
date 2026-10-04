---
name: factory-pattern
description: Construction wrapped behind an interface. Use when creation needs to vary (which adapter, which configuration, per-request data), when binding runtime data to dependencies, or when deciding where a module gets built. Requires the codebase-design and dependency-injection skills.
---

# Prerequisites

- **[codebase-design](../codebase-design/SKILL.md)** — vocabulary used exactly: module, interface, seam, adapter, resource.
- **[dependency-injection](../dependency-injection/SKILL.md)** — construction, and seams declared at construction.

# Factory Pattern

A factory is construction wrapped behind an interface: a module whose implementation is the choice of concrete. Callers receive the built module through its **Interface** and never see which concrete they got — so *what gets built* becomes a decision that can vary, defer, or move to the place that knows enough to make it.

## Glossary

**Factory** — a module whose job is construction: its signature declares construction's ingredients (adapters, configuration, runtime data) and returns a module behind an interface. Its implementation is the choice of concrete.

_Avoid_: builder (assembles a data object piece by piece — a different job), creator (vague), container (a registry, not a module).

**Composition point** — where a graph is wired: the only code that names the concretes. The widest sits near `main`; a narrower one sits wherever runtime data arrives.

## Rules

### 1. Return the interface, hide the concrete

The factory's return type is the **Interface**; the product concrete appears only in the factory's body. A factory that returns `StripeGateway` has hidden nothing — the caller is welded to one adapter, just via an extra call.

The factory names its products; it never names its ingredients. The choice of product concrete is the factory's *implementation*; the ingredients are its *interface* — adapters, configuration, and data arrive as parameters, never fetched from the body.

Every concrete has exactly one place it may appear: the composition point names ingredient concretes, the factory names product concretes, and everyone else sees interfaces.

### 2. Bind runtime data to root-chosen adapters

Construction has two ingredients: dependencies (adapters, chosen at a composition point) and data (values arriving at runtime). When a module needs both, the factory is where they meet — bound at the composition point, called at the boundary where the data arrives.

A factory a module calls is a dependency like any other: it arrives at construction, or the module is welded to one way of building. Bind the root-time ingredient into the factory at construction; the boundary supplies only the runtime data.

A test injects a fake factory and controls construction without touching globals. A factory at a boundary may use what it built; it must not cache the product for a wider span than its caller — every later request would see the first entity's config.

### 3. A factory wires; it doesn't work

The factory's body is pure construction: choose the concrete, bind the ingredients, return. No I/O, no clock, no network — those belong to **Use**, entered by the module after the factory returns it. A factory that works has a module hiding inside it: extract the module, let the factory build it.

### 4. A factory earns its place when construction varies

Something must vary: which adapter (a config decides), which configuration, what data binds (per request). If construction is fixed — same concrete, same ingredients every time — build directly at the composition point. A factory over a fixed graph is indirection without decision.

## Variants

The GoF shapes are this skill's one discipline at different scales:

- **Factory function** (`create_x`, `make_x`, `NewX`): the everyday shape — everything above.
- **Factory method**: a subclass overrides a creation method to choose the concrete. The same seam, declared by inheritance; prefer the function unless the framework demands it.
- **Abstract factory**: a factory whose products are themselves factories — a family of modules that must vary together (all-stripe or all-paypal). Reach for it when a half-switched family is a bug.

## Relationships

- A factory is a **Module**: its interface is the signature (ingredients in, interface-typed module out); its implementation is the choice of concrete.
- The seam lands where the concrete would otherwise leak: the factory's return type is an **Interface** at a **Seam**.
- Rule 2 of dependency-injection holds recursively: the factory a module calls arrives at that module's construction.

## Rejected framings

- **"Factories are for complex construction."** Factories are for *varying* construction. Complexity belongs in the built module's implementation, not the builder.
- **"A factory per class."** Fixed construction needs no factory — build at the composition point. Symmetry is not a reason.
- **Factory as service locator.** A factory's signature declares its ingredients; a locator hides them in an ambient registry. If callers must arrange a global before calling, it's a locator wearing the name.

## Language idioms

The rules above are language-agnostic. When implementing, read the file for the target language:

- [python.md](python.md) — `create_x` factory functions, `Callable`-typed factories bound with `functools.partial` or closures, lambda fakes in tests
- [typescript.md](typescript.md) — `createX` factory functions, function-typed factories bound with arrow closures, arrow fakes in tests
