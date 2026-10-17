# Dependency Injection

This file uses the vocabulary of [codebase-design](SKILL.md) exactly.

Dependency injection is passing an entity its dependencies instead of letting it create or fetch them. It has two sides. The **Constructor** accepts: a component receives what satisfies each of its **Ports**, and its **Configuration**, rather than reaching for **Resources** itself. The **Factory** supplies: it chooses what satisfies each port and calls the constructor. The aim is that every resource sits behind a port or a foreign object passed to an edge component, every dependency is declared in a constructor, the **Interface** carries only data, and nothing reaches a resource while the **Assembly** is being built.

Where factories live on disk is covered by [project-structure](project-structure.md).

## The constructor

### 1. A constructor takes the component's ports and its configuration

A component's constructor takes one port for each thing it depends on. Everything else it takes is configuration.

- **One port per dependency, named for what it is to the component.** `payments`, `clock`, `tools`. A behaviour that needs something new from a dependency the component already has adds a method to that port's interface; a behaviour that needs a new dependency adds a new port.
- **A port is an interface, never an implementation.** A constructor never names an edge component's or an adapter's type.
- **A port's interface belongs to the component, or is a contract.** A constructor never names another component's interface. Two components that need the same thing each declare it, unless it means the same thing to both, in which case it is promoted to a contract that both ports use.
- **A port holds only what the component calls.** Its interface is shaped by the component's needs, not copied from whatever will satisfy it.

Data carriers and configuration have no implementation to swap, so they are passed as their concrete types. Configuration is a plain value or a data carrier.

An **outbound edge component**'s constructor also takes its foreign dependency: the library's own object (an `httpx.Client`, a model provider's SDK client), or a view of it where the library offers no test hook. It is the one place a foreign object appears in a constructor.

An **adapter**'s constructor takes the interfaces of the components it calls, contracts and configuration. It never takes a port's interface, except a **decorator**, which takes the very interface it satisfies, and it takes no foreign object: what else it needs follows from an adapter defining no port of its own, in [Relationships](SKILL.md#relationships). Like every constructor, it must take everything required to measure the adapter's behaviours.

This improves **flexibility for designers** since a new component or adapter passed to a port adds a capability without touching the component, and each port can be swapped on its own.

This improves **locality for maintainers** since a port changes with its component alone, and a change to what satisfies one port stops there.

This improves **testability for everyone** since a fake passed to each port observes and drives everything the component does outside itself, and each dependency is faked on its own.

### 2. Ports and configuration go in the constructor, not the interface

Anything that changes the behaviour of an entity is passed to its constructor: as a port if it is an interface, as configuration if it is a value.

- **The interface takes only data.** A method on the interface takes data carriers and plain values supplied by the caller. It never takes a port or a configuration value.
- **Except what a foreign interface hands in.** An inbound edge component's interface is foreign, and the framework passes what it passes with each call: a request, a socket, a set of background tasks. Those belong to the foreign interface. They are used only in the humble shell, and never carry the component's dependencies, which still arrive through its constructor rather than through the framework's own injection.

This improves **leverage for callers** since the interface for the component stays simpler, increasing the capability per unit of complexity in the interface.

This improves **locality for maintainers** since the behaviour of an entity is decided in one place, where it is constructed.

This improves **testability for everyone** since every behaviour can be measured from the constructor arguments and the interface alone. It also allows tests to be grouped by constructor setup.

### 3. A constructor accepts what it needs, and reaches no resource

A constructor never creates what it needs and never fetches it. Neither the constructor nor the implementation constructs another component or an adapter, reads an environment variable, reads the clock or opens a connection: each of those arrives through the constructor.

Who acquires a resource follows its lifetime, as the [principles](SKILL.md#principles) set out, and it is never a constructor. A resource for a single use is acquired when the component is called, or by a session its interface opens, which then holds it. One that lives as long as the process is passed in.

When an entity must be built per request, because it holds that request's resources, the constructor takes a function that opens it, returning its interface. A factory satisfies that function.

This improves **testability for everyone** since constructing any entity is safe in a test, and only a call shows what reaches a resource.

## The factory

A factory is code that calls an entity's constructor and returns the entity. It is never the constructor itself: the constructor accepts what the entity needs, and the factory supplies it. A factory builds a component, an edge component included, or an adapter.

### 4. A factory returns the interface

A factory for a component declares its return type as the component's interface: for an inbound edge component, that is the foreign interface it presents, such as a router. A factory for an adapter declares its return type as the port's interface or the contract it satisfies. Neither returns the implementation.

This improves **leverage for callers** since a caller of the factory learns only the interface.

This improves **locality for maintainers** since the implementation can be renamed or replaced without touching any caller of the factory.

### 5. A factory only wires

A factory calls constructors and other factories, builds the library objects an edge component takes, and returns what it built. It does nothing else. Anything worth testing belongs in a component or an adapter.

What a factory takes is a design decision that depends on its use case. It may take nothing, parameters that select between choices, configuration values, other entities, or anything else. How it gets the other entities it needs, by calling their factories, calling their constructors or taking them as parameters, is a design decision too, and so is whether it builds a new entity on every call or returns one it has kept.

This improves **testability for everyone** since every behaviour sits behind a constructor, where a test can reach it with fakes.

### 6. A factory reaches no resource

A factory never reads an environment variable, reads a settings file or opens a connection, and so it is synchronous: a factory that has to wait on something is reaching for a resource.

- **Building is not reaching.** A library object that reaches its resource only when called, such as an HTTP client or a model provider's SDK client, can be built in a factory.
- **A library's defaults are not a way round.** A library that reads a value from the environment when it is not given one, as many SDKs do for an API key, is reaching the environment on the factory's behalf. A factory passes every such value explicitly, as a parameter.
- **What lives as long as the process is acquired outside.** A value or a connection that comes from the environment is acquired by whatever calls the factory, and passed in as a parameter. Which code that is — the entrypoint, a settings loader, a test — is a design decision.

This improves **locality for maintainers** since how the program is wired and how it reads its environment change independently.

This improves **testability for everyone** since a factory can be called with any values, and since no constructor reaches a resource either, building the program reaches none.

### 7. One constructor, many factories

An entity has a single constructor. Each factory is one way of supplying it: one per choice of what satisfies its ports, or one per environment. A new way of building a component or an adapter is a new factory, never a second constructor and never a change to the interface.

This improves **flexibility for designers** since a new combination of dependencies is added without touching the component.

### 8. A composite is a factory

A composite presents an assembly of components and adapters as one component. It is a factory: its parameters are the composite's ports, which it passes to the components inside, and it returns one interface, the interface of the component it presents. Everything else it builds stays hidden from its callers, who see one more component with one interface and its ports.

A composite follows every rule for factories: it only wires, reaches no resource and returns the interface. It has no constructor of its own, because it is not an entity with behaviour: the behaviour belongs to the components inside.

This improves **leverage for callers** since a whole assembly is used through one interface, and a caller learns only the ports it must satisfy.

This improves **locality for maintainers** since the inside of a composite can be rewired without touching anything that uses it.

## Language idioms

The rules above are language-agnostic. When implementing, read the file for the target language:

- [python/dependency-injection.md](python/dependency-injection.md) — worked examples of each rule, built on `OrderProcessor`, its `payments` and `clock` ports, a `StripePayments` edge component, a `create_order_processor` factory, and a `create_research_team` composite
- [typescript/dependency-injection.md](typescript/dependency-injection.md) — worked examples of each rule, built on `OrderProcessor`, its `payments` and `clock` ports, a `StripePayments` edge component, a `createOrderProcessor` factory, and a `createResearchTeam` composite
