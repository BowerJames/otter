# Development Tools

| tool      | purpose                                                                           | run             |
| --------- | --------------------------------------------------------------------------------- | --------------- |
| just      | Run pre-prepared scripts made for internal use within the repository              | just            |
| gh        | Github CLI tool for interacting with the github repository                        | gh              |
| tmux      | Can be used if you need to run interactive commands or processes that you are worried might hang | tmux            |
| ruff      | Linting + formatting                                                              | uv run ruff     |
| mypy      | Static type checking                                                              | uv run mypy     |
| pytest    | Testing (including async)                                                         | uv run pytest   |
| ast-grep  | AST-based structural search and rewrite                                           | uv run ast-grep |

# Pre Commit Hooks

This repository has pre-commit hooks enabled which can be found in `.githooks/pre-commit`.