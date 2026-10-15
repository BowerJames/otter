"""Behaviour of the in-memory adapter, driven through the session log's port."""

from otter.infrastructure.adapters.session_log.in_memory import InMemoryAdapter


def test_it_starts_out_with_no_text() -> None:
    assert InMemoryAdapter().read() == ""


def test_appended_text_is_read_back_in_the_order_it_was_appended() -> None:
    adapter = InMemoryAdapter()
    adapter.append("one\n")
    adapter.append("two\n")

    assert adapter.read() == "one\ntwo\n"
