---
name: dependency-injection
description: Discipline for wiring modules together. Covers coding against interfaces and declaring seams in the factory. Use when wiring dependencies, deciding whether a dependency belongs in a module's factory or its interface, or fixing modules that create or fetch what they need. Requires the codebase-design skill.
---

# Prerequisites

- **[codebase-design](../codebase-design/SKILL.md)** — read it first. This skill uses its vocabulary (module, interface, behaviour, implementation, seam, adapter, factory, resource) exactly.

# Dependency Injection

Dependency injection is passing a module its dependencies instead of letting it create or fetch them: a module receives **Adapters** across its **Seams** rather than reaching for **Resources** itself. The aim is that every resource sits behind a seam, and every seam is declared in a **Factory** where possible, so the **Interface** carries only data.

## Rules

### 1. Code against interfaces, not implementations

Where possible a module's interface and the dependencies passed in factories should be interfaces, not implementations.

This applies to things with behaviour. A data carrier has no implementation behind it, so it is passed as its concrete type.

This improves **flexibility for developers** since modules can be deepened through the creation of new adapters.

This improves **locality for maintainers** since modules can be used with a wide range of entities allowing the localisation of behaviour.

This improves **testability for everyone** as swappable mocks can be used in tests to observe and drive behaviours.

### 2. Declare seams in factories

Anything that changes the behaviour of an entity satisfying a module's interface should be passed to its factory.

This improves **leverage for callers** since the interface for the module stays simpler, increasing the capability per unit of complexity in the interface.

This improves **locality for maintainers** since it reduces the number of locations where the behaviour of modules changes.

This improves **testability for everyone** since behaviours can be tested consistently based only on the factory setup. It also allows tests to be grouped by factory setup.

## Language idioms

The rules above are language-agnostic. When implementing, read the file for the target language:

- [python.md](python.md) — worked examples of each rule, built on `OrderProcessor`
- [typescript.md](typescript.md) — worked examples of each rule, built on `OrderProcessor`
