# Development Tools

| tool      | purpose                                                                           | run             |
| --------- | --------------------------------------------------------------------------------- | --------------- |
| just      | Run pre-prepared scripts made for internal use within the repository              | just            |
| gh        | Github CLI tool for interacting with the github repository                        | gh              |
| tmux      | Can be used if you need to run interactive commands or processes that you are worried might hang | tmux            |
| ruff      | Linting + formatting                                                              | uv run ruff     |
| mypy      | Static type checking                                                              | uv run mypy     |
| pytest    | Testing (including async)                                                         | uv run pytest   |
| semgrep   | Docstring policy rules                                                            | uv run semgrep  |
| ast-grep  | AST-based structural search and rewrite                                           | uv run ast-grep |

# Pre Commit Hooks

This repository has pre-commit hooks enabled which can be found in `.githooks/pre-commit`.

# Self Documenting Code

In this repo we are practicing a variation of `Self Documenting Code` standards. The use of the following docstrings is forbidden:

- Module Docstrings
- Class Docstrings
- Function Docstring
- Method Docstrings

Comments are discouraged but allowed if there is code to explain counterintuitive parts of the code or special edge cases.

If comments are used they must be localised to the position of the code they are referencing. They should not be added at the top of function block describing something that happens later in the code. This is likely to lead to stale comments in the future if the relevant are of code is edited but the comments are not updated because they are not localised.

# Programming to Interfaces

In this repository we are practicing `Programming to Interfaces` design standards. The preferred interface mechanic is the `Protocol` rather than `ABC`. 