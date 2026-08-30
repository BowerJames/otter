---
name: test-driven-development
description: Phases and benefits of test driven development (TDD). Used in all module development.
---

# Prerequisite Reading

**`codebase-design` skill** - Provides valuable context on the shared vocabulary to use and the goals of clean codebase design.

# Benefits of TDD

**Testing is not about finding bugs** - The major benefit of testing happens when you think about writing the tests. It helps guide you towards a good design and help you ensure that the module is testable through its interface.

**A test is the first user of your code** - Good code reduces coupling. A function or method that is highly coupled is hard to test. Tests interact with the module through its interface, modules that are complex to test imply a complex interface which reduces leverage.

**You need to know where you are going** - Tests describe the desired behaviour of a module, they provide a measurable target for your development to know when you are done and give confidence in your implementation.

# Phases of TDD

**Identify Target Behaviour** - During this phase you need to identify the target behaviour (or change in behaviour) you expect from your system.

**Identify Target Modules** - During this phase you need to identify which modules will require behavioural changes to reflect the overall behavioural change to the system.

**Red Phase** - During the red phase you encode the desired behaviour and/or behavoural change of your module(s) interface. You do this by adding or adapting tests such that the target test will fail until the behaviours you expect from the module(s) are satisfied. By the end of the red phase you should verify that the expected tests are all failing.

**Green Phase** - During the green phase you adapt any modules implementation to reflect the intended behavioural change in the module(s) interface. You do this by editing each module's implementation until the all the tests are passing. This phase is not complete until all tests pass.

**Refactor Phase** - This phase gives you the chance to review the implementation you have edited and refactor the code to improve the internal design without changing behaviour. During this phase tests should not be edited and should remain green.

# Identify Target Behaviour

Grill the user until you are both clear and aligned on the behavioural change you are looking for in the system.

# Identify Target Modules

Propose your intended module changes for all required module changes. Each proposal should be scoped to a specific part of the modules interface or implementation. You should format your proposals as following:

```
Reason: <your reason for the change you are proposing>

Change: <the specific behavioural change being proposed either to the interface of within the implementation>

Current Interface Section:


<current interface signature and interface comments for the section of the interface the proposal is suggesting a change for>

Proposed Interface Section:


<Proposed signature and interface comments for the section of the interface being changed after development>
```

## Important Guidance

- `Current Interface Section` and `Proposed Interface Section` are at the interface level so the user has context on the intended behaviour of the section of the interface being edited. If the proposed change is an implementation change only the `Current Interface` and `Proposed Interface` can be the same.
- The `Current Interface Section` and `Proposed Interface Section` should include only interface details (signature, comments, ect) and should not containe any implementation code snippets.

# Red Phase

Propose the test additions and amendments that will encode the required behavioural changes across the edited modules. Each proposal should be scoped to a single test and should be formated like so:

```
Purpose: <purpose of the test change>

Current test:

<current test signature and body> (if exists)

Proposed test:

<proposed new test signature and body with amended areas highlighted>
```

Once all decisions have been made complete the red phase development, verify the expected tests are failing, commit the red state and check back in with the user.

_Never_: Edit the implementation of any modules during this phase.

_Prefer_: Adapting existing tests to fold in the new behaviour where sensible over creating new tests for everything.

# Green Phase

Conplete the development of the implementation until all tests are passing.

Once all tests are passing commit your work.

If you encounter any issues that you believe require a change to the tests you should stop immediately and raise it with the user for discussion before proceeding. 

_Never_: edit the tests without discussing with and getting approval from the user first.

# Refactor Phase

This is your chance to review the implementations of the modules you have edited and look for opportunities to improve their design to increase internal leverage.

Propose your refactors to the user then implement any that are approved.

Verify that all the tests still pass.

_Never_: Edit the tests during this phase. Behaviour of modules should remain the same.