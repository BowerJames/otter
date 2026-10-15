"""The TUI's startup code, run as the command a user would run."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


def run_tui(*args: str, cwd: Path, environ: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "otter.infrastructure.entrypoints.tui", *args],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=cwd,
        env={"PATH": os.environ.get("PATH", ""), **environ},
    )


def test_a_missing_api_key_is_reported_and_the_command_fails(tmp_path: Path) -> None:
    result = run_tui(
        "--model-name",
        "glm-5.3",
        "--model-type",
        "chat-completions",
        "--provider",
        "zai",
        cwd=tmp_path,
        environ={},
    )

    assert result.returncode == 1
    assert result.stderr.strip() == "error: no API key for provider 'zai': set ZAI_API_KEY"


def test_the_api_key_is_read_from_a_dotenv_file_in_the_working_directory(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("ZAI_API_KEY=zai-key\n")

    result = run_tui(
        "--model-name",
        "glm-5.3",
        "--model-type",
        "realtime",
        "--provider",
        "zai",
        cwd=tmp_path,
        environ={},
    )

    # Past the key: it is the pairing of model type and provider that is refused.
    assert result.stderr.strip() == "error: provider 'zai' serves no 'realtime' models"


def test_a_model_the_provider_does_not_serve_is_reported_and_the_command_fails(
    tmp_path: Path,
) -> None:
    result = run_tui(
        "--model-name",
        "glm-5.3",
        "--model-type",
        "realtime",
        "--provider",
        "zai",
        cwd=tmp_path,
        environ={"ZAI_API_KEY": "zai-key"},
    )

    assert result.returncode == 1
    assert result.stderr.strip() == "error: provider 'zai' serves no 'realtime' models"
