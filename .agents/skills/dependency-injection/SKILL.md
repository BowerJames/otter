---
name: dependency-injection
description: Discipline for how entities get their dependencies; what a constructor receives, and the factories that call it. Use when wiring dependencies, deciding whether a dependency belongs in a module's constructor or its interface, writing or changing a factory, or fixing modules that create or fetch what they need. Requires the codebase-design skill.
---

# Prerequisites

- **[codebase-design](../codebase-design/SKILL.md)** — read it first. This skill uses its vocabulary (entity, module, interface, behaviour, implementation, constructor, port, configuration, adapter, factory, data carrier, resource) exactly.

# Dependency Injection

Dependency injection is passing an entity its dependencies instead of letting it create or fetch them. It has two sides. The **Constructor** accepts: a module receives an **Adapter** for its **Port**, and its **Configuration**, rather than reaching for **Resources** itself. The **Factory** supplies: a module factory chooses adapters and calls the module's constructor, and an adapter factory builds an adapter. The aim is that every resource sits behind a port, the port is declared in the constructor, the **Interface** carries only data, and nothing reaches a resource while entities are being built.

Where factories live on disk is covered by [project-structure](../project-structure/SKILL.md).

## The constructor

### 1. A constructor takes the module's port and its configuration

A module's constructor takes at most one parameter that carries behaviour: the module's port, an interface the module declares itself. Everything else it takes is configuration.

- **The port holds everything the module needs.** A behaviour that needs something new adds a method to the port, never a second port.
- **A port is an interface, never an implementation.** A constructor never names an adapter's type.
- **A port belongs to the module that declares it.** A constructor never names another module's interface. Two modules that need the same thing each declare it on their own port. Their adapters can be thin wrappers around the same resource or library: the adapter decides how each module uses it.
- **A port holds only what the module calls.** It is shaped by the module's needs, not copied from the adapter that will satisfy it.

Data carriers and configuration have no implementation to swap, so they are passed as their concrete types. Configuration is a plain value or a data carrier, never an object from a library: a module is self-contained, so what a library provides reaches it through its port.

An adapter's constructor is not limited to the module's port: it can take ports of its own, satisfied by other entities, or anything else it needs. Like every constructor, it must take everything required to measure the adapter's behaviours.

This improves **flexibility for designers** since a new adapter adds a capability without touching the module.

This improves **locality for maintainers** since a port changes with its module alone, and a change to an adapter or to another module stops at the adapter.

This improves **testability for everyone** since one test adapter, passed to the constructor, observes and drives everything the module does outside itself.

### 2. The port and configuration go in the constructor, not the interface

Anything that changes the behaviour of an entity is passed to its constructor: as the port if it is an interface, as configuration if it is a value.

- **The interface takes only data.** A method on the interface takes data carriers and plain values supplied by the caller. It never takes a port or a configuration value.

This improves **leverage for callers** since the interface for the module stays simpler, increasing the capability per unit of complexity in the interface.

This improves **locality for maintainers** since the behaviour of an entity is decided in one place, where it is constructed.

This improves **testability for everyone** since every behaviour can be measured from the constructor arguments and the interface alone. It also allows tests to be grouped by constructor setup.

### 3. A constructor accepts what it needs, and reaches no resource

A constructor never creates what it needs and never fetches it. Neither the constructor nor the implementation constructs an adapter, reads an environment variable, reads the clock or opens a connection: each of those arrives through the constructor. An adapter reaches its resource when it is called, never while it is being constructed.

This improves **testability for everyone** since constructing any entity is safe in a test, and only a call shows what reaches a resource.

## The factory

A factory is code that calls an entity's constructor and returns the entity. It is never the constructor itself: the constructor accepts what the entity needs, and the factory supplies it. There are two kinds:

- **A module factory** builds a module: it gets an adapter for the module's port and calls the module's constructor.
- **An adapter factory** builds an adapter: it builds the parts the adapter's constructor takes and calls the adapter's constructor. Every adapter has one, even an adapter with nothing to build but itself.

### 4. A factory returns the interface

A module factory declares its return type as the interface of the module. An adapter factory declares its return type as the port the adapter satisfies. Neither returns the implementation.

This improves **leverage for callers** since a caller of the factory learns only the interface.

This improves **locality for maintainers** since the implementation can be renamed or replaced without touching any caller of the factory.

### 5. A factory only wires

A factory calls constructors and other factories, and returns what it built. It does nothing else. Anything worth testing belongs in a module or an adapter.

What a factory takes is a design decision that depends on its use case. It may take nothing, parameters that select between choices, configuration values, adapters, entities of other modules, or anything else. Whether it builds a new entity on every call or returns one it has kept is a design decision too.

This improves **testability for everyone** since every behaviour sits behind a constructor, where a test can reach it with test adapters.

### 6. A factory reaches no resource

A factory never reads an environment variable, reads a settings file or opens a connection. A value or a connection that comes from the environment is acquired by whatever calls the factory, and passed in as a parameter. Which code that is — an entrypoint, a settings loader, a test — is a design decision.

This improves **locality for maintainers** since how the program is wired and how it reads its environment change independently.

This improves **testability for everyone** since a factory can be called with any values, and since no constructor reaches a resource either, building the program reaches none.

### 7. One constructor, many factories

An entity has a single constructor. Each factory is one way of supplying it: one per choice of adapters, or one per environment. A new way of building a module or an adapter is a new factory, never a second constructor and never a change to the interface.

This improves **flexibility for designers** since a new combination of adapters is added without touching the module.

### 8. A factory calls one entity's constructor, and gets everything else from factories

A factory calls the constructor of the entity it builds and, for an adapter, the constructors of the parts defined in the adapter's package. Every other entity it needs comes from that entity's factory or as a parameter.

- A module factory never calls an adapter's constructor. It calls the adapter's factory.
- A factory never calls another module's constructor. It calls one of that module's factories, or takes the entity as a parameter.

This improves **locality for maintainers** since the knowledge of how an entity is built stays with that entity's factories: a module factory chooses adapters without knowing what they are made of.

## Language idioms

The rules above are language-agnostic. When implementing, read the file for the target language:

- [python.md](python.md) — worked examples of each rule, built on `OrderProcessor`, a `create_order_processor` module factory and a `create_stripe_adapter` adapter factory
- [typescript.md](typescript.md) — worked examples of each rule, built on `OrderProcessor`, a `createOrderProcessor` module factory and a `createStripeAdapter` adapter factory
