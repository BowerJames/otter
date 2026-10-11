---
name: project-structure
description: Policy for where code lives on disk. Use when creating a file or package, deciding where a shared data carrier or helper belongs, when a second module needs something another module defines, or when fixing import cycles and utils dumping grounds. Requires the codebase-design skill.
---

# Prerequisites

- **[codebase-design](../codebase-design/SKILL.md)** — read it first. This skill uses its vocabulary (module, interface, behaviour, implementation, seam, adapter, factory, resource) exactly.

# Project Structure

Project structure is the mapping of modules onto files: where each module's code lives, what other code may import from it, and where things used by more than one module go. The aim is that placement never needs a prediction: everything starts beside its first user and moves, cheaply, when a second user appears.

## Glossary

**Package** — the directory that holds one module's code: its interface, factories and implementations. One module, one package.

_Avoid_: folder (says nothing about ownership), module (already means an interface and its behaviours, not a place on disk).

**Entry point** — the one file in a package that other packages import from. It exports the module's interface, its factories, and the data carriers that appear in its interface.

_Avoid_: public API (interface already names what callers must know), barrel (names the mechanism, not the role).

**Data carrier** — a type that holds data and its invariants and reaches no resource: `Order`, `Receipt`, `Money`. It has no implementation behind it, so modules take and return it as its concrete type, not through an interface of its own.

_Avoid_: model (overloaded with ORMs and machine learning), DTO, entity (already means a thing satisfying a module's interface).

**Domain package** — the package holding the data carriers that no single module owns. One file per concept, named for the concept.

_Avoid_: utils, common, shared, helpers, core (names that say only that something is shared, so they accept anything).

## Rules

### 1. One package per module, one entry point per package

A module's interface, factories and implementations live together in one package. Other packages import only from its entry point, never from the files behind it. Implementations are not exported: a factory returns the interface, so no caller needs them.

This improves **leverage for callers** since there is one place to import from and it shows only what a caller must know.

This improves **locality for maintainers** since anything behind the entry point can be renamed, split or moved without touching another package.

### 2. Place at first use, move at second use

A data carrier or helper is defined in the package of the first module that needs it. If it appears in that module's interface, the entry point exports it. Nothing moves until a second package needs it.

When a second package needs it, ask in order:

1. **Does the second package need only a slice of it?** Then it declares its own interface with just the fields it reads and imports nothing.
2. **Does the second package already depend on the first module's interface?** Then it imports the data carrier from the first package's entry point.
3. **Otherwise** move it to the domain package.

This improves **locality for maintainers** since each data carrier has exactly one definition and one owner at every point in the project's life.

This improves **flexibility for developers** since a new module never waits on a decision about where shared things will eventually live.

### 3. Imports point one way

- A package may import from the domain package and from other packages' entry points.
- The domain package imports from no module's package.
- No cycles. A cycle between two packages means something both need belongs in the domain package.
- The program's start-up code calls the factories and wires the entities together. It may import any entry point; nothing imports it.

This improves **locality for maintainers** since a change can only affect the packages that import the one changed.

This improves **testability for everyone** since a module can be built through its factory with nothing but its own package, the domain package and test adapters.

### 4. Name a package for what it is, not for being shared

There is no `utils`, `common`, `shared` or `helpers` package. A helper used by one package stays in that package. Duplicate a small helper until its second or third use, then apply the deletion test:

- If it hides real complexity it is a module: give it an interface, a factory and a package named for what it does (`retry`, `money`).
- If it does not, the duplication was the right call.

The domain package holds data carriers and their invariants only. Anything that reaches a resource is a module, not a data carrier.

This improves **leverage for callers** since a package's name says what it offers.

This improves **locality for maintainers** since nothing accumulates in a place with no owner.

## Language idioms

The rules above are language-agnostic. When implementing, read the file for the target language:

- [python.md](python.md) — packages with `__init__.py` as the entry point, a worked `Order` moving from one package to the domain package
- [typescript.md](typescript.md) — directories with `index.ts` as the entry point, a worked `Order` moving from one package to the domain package
