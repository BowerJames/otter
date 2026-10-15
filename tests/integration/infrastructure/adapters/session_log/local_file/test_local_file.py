"""Behaviour of the local file adapter, run against this machine's file system."""

from pathlib import Path

import pytest

from otter.infrastructure.adapters.session_log.local_file import LocalFileAdapter

pytestmark = pytest.mark.integration


def test_a_file_that_does_not_exist_holds_no_text(tmp_path: Path) -> None:
    assert LocalFileAdapter(tmp_path / "session.jsonl").read() == ""


def test_making_the_adapter_does_not_make_its_file(tmp_path: Path) -> None:
    LocalFileAdapter(tmp_path / "session.jsonl")

    assert list(tmp_path.iterdir()) == []


def test_appending_makes_the_file_and_the_directories_it_sits_in(tmp_path: Path) -> None:
    path = tmp_path / "sessions" / "today" / "session.jsonl"
    LocalFileAdapter(path).append("hello\n")

    assert path.read_text(encoding="utf-8") == "hello\n"


def test_appended_text_is_read_back_after_the_text_already_in_the_file(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text("earlier\n", encoding="utf-8")
    adapter = LocalFileAdapter(path)
    adapter.append("Call Zoë.\n")

    assert adapter.read() == "earlier\nCall Zoë.\n"


def test_the_file_is_utf_8(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    LocalFileAdapter(path).append("Zoë\n")

    assert path.read_bytes() == "Zoë\n".encode()
