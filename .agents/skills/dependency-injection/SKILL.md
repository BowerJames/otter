---
name: dependency-injection
description: Discipline for wiring modules together. Covers coding against interfaces and declaring seams at construction. Use when wiring dependencies, structuring initialisation, or fixing modules that create or fetch what they need. Requires the codebase-design skill.
---

# Prerequisites

- **[codebase-design](../codebase-design/SKILL.md)** — read it first. This skill uses its vocabulary (module, interface, implementation, seam, adapter, resource) exactly.

# Dependency Injection

Dependency injection is passing a module its dependencies instead of letting it create or fetch them: a module receives **Adapters** across its **Seams** rather than reaching for **Resources** itself. The aim is that every resource sits behind a seam, and every seam is declared in the **Interface**.

## Glossary

Use these terms exactly. The prerequisite terms (module, interface, implementation, seam, adapter, resource) are defined in [codebase-design](../codebase-design/SKILL.md); these are this skill's own.

**Construction** — the act of assembling a module so it is ready for use: a class constructor, a factory function, or simply entering a function.

## Rules

### 1. Code against interfaces, not implementations

Declare a dependency's type as an **Interface**, not a concrete class. The concrete thing is an **Adapter**; the seam exists only where the interface is declared.

The interface belongs to the consumer: declare the operations the caller needs, which is often a subset of the adapter's full surface. A consumer forced to see `refund` when it only ever charges is seeing someone else's interface.

### 2. Declare seams at construction

The seam must be visible in the module's interface, and construction is where the interface declares it. A dependency in the signature is a fact every caller and test can see and must satisfy; a dependency fetched inside the body is a hidden resource — present in behaviour, absent from the interface.

- **Injection at construction makes the invalid state unrepresentable.** A module cannot be assembled without its adapters.
- **Service locator** (asking a global registry or container for dependencies) removes the seam from the interface entirely: the module works only when the ambient world is arranged just so. Injection inverts this — dependencies arrive; the module never fetches.
- **Setter injection** half-hides it: the module exists in an unready state until some caller remembers the setter. The interface lies about what is required.

This is the testability rule "accept dependencies, don't create them" applied at the level of the signature. Construction is partial application: bind the behaviour, and what remains is a stable function from data to results.

## Language idioms

The rules above are language-agnostic. When implementing, read the file for the target language:

- [python.md](python.md) — Protocols and Callables as dependency types, seams declared in `__init__` signatures, pytest fixtures wiring the graph, Python gotchas
- [typescript.md](typescript.md) — interfaces and function types as dependency types, seams declared in factory signatures, object-literal fakes wiring the graph, TypeScript gotchas