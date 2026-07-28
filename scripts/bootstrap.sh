#!/usr/bin/env bash
#
# One-shot, idempotent dev-environment bootstrap for the otter monorepo.
#
# Usage:
#   scripts/bootstrap.sh        # from anywhere; resolves the repo root itself
#
# Installs any missing prerequisites (uv, just), syncs the workspace against
# uv.lock, and enables the local pre-commit hook. Every step is a no-op if it
# has already run, so this is safe to re-run.
#
#   uv   — https://astral.sh/uv/install.sh  (default install dir: ~/.local/bin)
#   just — https://just.systems/install.sh  (installed to ~/.local/bin via --to)
#
# Neither tool is a Python package, so neither can live in pyproject.toml/uv.lock.
# macOS + Linux only. Written for bash 3.2 (macOS system bash): no associative
# arrays, no mapfile/readarray.
set -euo pipefail

LOCAL_BIN="$HOME/.local/bin"

# Status lines filled in by the ensure_* helpers; surfaced in the final summary.
UV_STATUS=""
JUST_STATUS=""

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

# Install uv (via the official installer) unless it is already on PATH.
ensure_uv() {
    if command -v uv >/dev/null 2>&1; then
        UV_STATUS="already on PATH ($(uv --version))"
        return 0
    fi
    echo "  uv: not found; installing via https://astral.sh/uv/install.sh ..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Make it resolvable for the rest of this run (it lands in ~/.local/bin).
    export PATH="$LOCAL_BIN:$PATH"
    if command -v uv >/dev/null 2>&1; then
        UV_STATUS="installed ($(uv --version))"
        return 0
    fi
    echo "  uv: installed but $LOCAL_BIN is not on PATH." >&2
    echo "       Add 'export PATH=\"$LOCAL_BIN:\$PATH\"' to your shell rc and re-run." >&2
    return 1
}

# Install just (via the official installer) unless a copy is already available —
# globally on PATH (e.g. Homebrew) OR previously installed here by this script.
ensure_just() {
    if command -v just >/dev/null 2>&1; then
        JUST_STATUS="already on PATH ($(just --version))"
        return 0
    fi
    if [ -x "$LOCAL_BIN/just" ]; then
        # Installed by a previous run, but ~/.local/bin isn't on PATH yet.
        JUST_STATUS="already installed at $LOCAL_BIN (added to PATH for this run)"
        export PATH="$LOCAL_BIN:$PATH"
        return 0
    fi
    echo "  just: not found; installing via https://just.systems/install.sh ..."
    mkdir -p "$LOCAL_BIN"
    curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh \
        | bash -s -- --to "$LOCAL_BIN"
    export PATH="$LOCAL_BIN:$PATH"
    if command -v just >/dev/null 2>&1; then
        JUST_STATUS="installed ($(just --version))"
        return 0
    fi
    echo "  just: installed but $LOCAL_BIN is not on PATH." >&2
    echo "        Add 'export PATH=\"$LOCAL_BIN:\$PATH\"' to your shell rc and re-run." >&2
    return 1
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# Resolve the repo root from the script location and cd there so uv sync /
# git config work regardless of where the script is invoked from.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

case "$(uname -s)" in
    Darwin) os="macOS" ;;
    Linux)  os="Linux" ;;
    *)
        echo "Unsupported OS: $(uname -s) — bootstrap supports macOS and Linux only." >&2
        exit 1
        ;;
esac

echo "Bootstrapping otter dev environment ($os)..."
echo

echo "[1/4] Prerequisites"
ensure_uv
ensure_just
echo

echo "[2/4] Syncing workspace (uv sync)"
uv sync
echo

echo "[3/4] Enabling pre-commit hook (git config core.hooksPath .githooks)"
git config core.hooksPath .githooks
echo

echo "[4/4] Done"
echo
echo "Summary:"
printf '  uv:    %s\n' "$UV_STATUS"
printf '  just:  %s\n' "$JUST_STATUS"
echo "  deps:  workspace synced against uv.lock (.venv is up to date)"
echo "  hook:  core.hooksPath = .githooks"

fresh=0
case "$UV_STATUS"   in installed*) fresh=1 ;; esac
case "$JUST_STATUS" in installed*) fresh=1 ;;
esac
if [ "$fresh" -eq 1 ]; then
    echo
    echo "Note: prerequisites were just installed. Open a new shell (or source your"
    echo "      rc file) so 'uv' and 'just' are on PATH in future terminals."
fi

echo
echo "Run 'just' to see available recipes."
