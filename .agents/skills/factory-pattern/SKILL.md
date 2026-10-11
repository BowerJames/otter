---
name: factory-pattern
description: The code that creates an entity satisfying a module's interface. Use when deciding how a module gets built or what a factory should return. Requires the codebase-design and dependency-injection skills.
---

# Prerequisites

- **[codebase-design](../codebase-design/SKILL.md)** — vocabulary used exactly: module, interface, implementation, factory.
- **[dependency-injection](../dependency-injection/SKILL.md)** — its two rules: code against interfaces, and declare seams in factories.

# Factory Pattern

A factory for a module is code that creates and returns an entity satisfying the interface of the module.

There can be many factories for a module. The factory must declare its return type as the interface of the module and not a concrete implementation of the module.

## Language idioms

The rules above are language-agnostic. When implementing, read the file for the target language:

- [python.md](python.md) — a `create_payment_gateway` factory with its return type declared wrong, then right
- [typescript.md](typescript.md) — a `createPaymentGateway` factory with its return type left inferred, then declared
