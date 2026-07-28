set dotenv-load

# Show available recipes
default:
    @just --list

# Run semgrep docstring rules (errors if any docstring is present under */src/).
semgrep-rules:
    uv run semgrep scan --config semgrep.yml --error .

# Delete local git branches that don't exist on origin.
# Safe by default (git branch -d); use --force to force delete (git branch -D).
git-branch-cleanup force="":
    ./scripts/git-branch-cleanup.sh {{ force }}
