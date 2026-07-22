"""Model-connection events: routing, defaults, ``extra="forbid"``, round-trip."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from otter_ai_core import AssistantContextItem, TextContent, Usage, UsageCost
from otter_ai_core.connection import ConnectionBackend, ConnectionClient
from otter_ai_core.model_connection import (
    AbortResponse,
    AddToolResultMessage,
    AddUserMessage,
    BranchMove,
    BranchMoved,
    ClientContextEvent,
    ClientContextEventType,
    CompactionDone,
    CreateCompaction,
    CreateResponse,
    ModelConnectionBackend,
    ModelConnectionClient,
    ResponseDone,
    ResponseStarted,
    ResponseUpdated,
    ServerContextEvent,
    ToolResultAdded,
    UserItemAdded,
    UserItemUpdated,
)

_CLIENT_ADAPTER: TypeAdapter[ClientContextEvent] = TypeAdapter(ClientContextEvent)
_SERVER_ADAPTER: TypeAdapter[ServerContextEvent] = TypeAdapter(ServerContextEvent)


def _usage() -> Usage:
    return Usage(
        input=10,
        output=5,
        cache_read=0,
        cache_write=0,
        total_tokens=15,
        cost=UsageCost(input=0.0, output=0.0, cache_read=0.0, cache_write=0.0, total=0.0),
    )


def _user_message() -> dict[str, Any]:
    return {"role": "user", "content": "hi", "timestamp": 0}


def _tool_result_message() -> dict[str, Any]:
    return {
        "role": "tool_result",
        "tool_call_id": "t1",
        "tool_name": "get_time",
        "content": [TextContent(type="text", text="noon").model_dump()],
        "is_error": False,
        "timestamp": 0,
    }


def _assistant_item(**message_overrides: Any) -> dict[str, Any]:
    """An ``AssistantContextItem`` dict (id + nested assistant ``message``).

    ``stop_reason`` defaults to ``None`` (in flight); callers pass a terminal
    value (e.g. ``"stop"``) for a ``response.done`` item. Overrides apply to
    the nested ``message``.
    """
    message: dict[str, Any] = {
        "role": "assistant",
        "content": [TextContent(type="text", text="hi").model_dump()],
        "api": "responses",
        "provider": "openai",
        "model": "gpt-test",
        "usage": _usage().model_dump(),
        "stop_reason": None,
        "timestamp": 0,
    }
    message.update(message_overrides)
    return {"id": "a1", "message": message}


def _user_item() -> dict[str, Any]:
    return {"id": "u1", "message": _user_message()}


def _tool_result_item() -> dict[str, Any]:
    return {"id": "tr1", "message": _tool_result_message()}


# --------------------------------------------------------------------------- #
# Leaf routing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "typ, leaf, extra",
    [
        ("user_message.add", AddUserMessage, {"message": _user_message()}),
        ("tool_result.add", AddToolResultMessage, {"message": _tool_result_message()}),
        ("response.create", CreateResponse, {}),
        ("response.abort", AbortResponse, {}),
        ("compaction.create", CreateCompaction, {}),
        ("branch.move", BranchMove, {"at_item_id": "i1"}),
    ],
)
def test_client_event_routing(typ: str, leaf: type, extra: dict[str, Any]) -> None:
    payload: dict[str, Any] = {"type": typ, **extra}
    assert isinstance(_CLIENT_ADAPTER.validate_python(payload), leaf)


@pytest.mark.parametrize(
    "typ, leaf, extra",
    [
        ("response.started", ResponseStarted, {"partial": _assistant_item()}),
        ("response.updated", ResponseUpdated, {"partial": _assistant_item()}),
        ("response.done", ResponseDone, {"item": _assistant_item(stop_reason="stop")}),
        ("user_item.added", UserItemAdded, {"item": _user_item()}),
        ("user_item.updated", UserItemUpdated, {"item": _user_item()}),
        (
            "tool_result_item.added",
            ToolResultAdded,
            {"item": _tool_result_item()},
        ),
        ("compaction.done", CompactionDone, {}),
        ("branch.moved", BranchMoved, {"at_item_id": "i1"}),
    ],
)
def test_server_event_routing(typ: str, leaf: type, extra: dict[str, Any]) -> None:
    payload: dict[str, Any] = {"type": typ, **extra}
    assert isinstance(_SERVER_ADAPTER.validate_python(payload), leaf)


# --------------------------------------------------------------------------- #
# type= Literal defaults (ergonomic construction)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "cls, typ",
    [
        (AddUserMessage, "user_message.add"),
        (AddToolResultMessage, "tool_result.add"),
        (CreateResponse, "response.create"),
        (AbortResponse, "response.abort"),
        (ResponseStarted, "response.started"),
        (ResponseUpdated, "response.updated"),
        (ResponseDone, "response.done"),
        (UserItemAdded, "user_item.added"),
        (UserItemUpdated, "user_item.updated"),
        (ToolResultAdded, "tool_result_item.added"),
        (CreateCompaction, "compaction.create"),
        (BranchMove, "branch.move"),
        (CompactionDone, "compaction.done"),
        (BranchMoved, "branch.moved"),
    ],
)
def test_type_field_has_default(cls: type[BaseModel], typ: str) -> None:
    """Every model-connection event carries a default for its ``type`` field."""
    assert cls.model_fields["type"].default == typ


def test_create_response_constructs_without_type() -> None:
    """An event with no required non-type fields builds with no arguments."""
    assert CreateResponse().type == ClientContextEventType.CREATE_RESPONSE


# --------------------------------------------------------------------------- #
# extra="forbid"
# --------------------------------------------------------------------------- #


def test_extra_fields_forbidden_on_client_event() -> None:
    with pytest.raises(ValidationError):
        _CLIENT_ADAPTER.validate_python({"type": "response.create", "unexpected": 1})


def test_extra_fields_forbidden_on_server_event() -> None:
    with pytest.raises(ValidationError):
        _SERVER_ADAPTER.validate_python(
            {"type": "response.started", "partial": _assistant_item(), "unexpected": 1}
        )


# --------------------------------------------------------------------------- #
# stop_reason invariant: None while in flight (partial), set on the terminal item
# --------------------------------------------------------------------------- #


def test_partial_item_allows_none_stop_reason() -> None:
    """An in-flight ``response.started`` partial may carry ``stop_reason=None``."""
    ev = ResponseStarted(partial=AssistantContextItem.model_validate(_assistant_item()))
    assert ev.partial.message.stop_reason is None
    restored = _SERVER_ADAPTER.validate_json(ev.model_dump_json())
    assert isinstance(restored, ResponseStarted)
    assert restored == ev


def test_done_item_carries_terminal_stop_reason() -> None:
    ev = ResponseDone(item=AssistantContextItem.model_validate(_assistant_item(stop_reason="stop")))
    assert ev.item.message.stop_reason == "stop"


# --------------------------------------------------------------------------- #
# JSON round-trip through the union
# --------------------------------------------------------------------------- #


def test_response_done_round_trip_through_union() -> None:
    ev = ResponseDone(item=AssistantContextItem.model_validate(_assistant_item(stop_reason="stop")))
    restored = _SERVER_ADAPTER.validate_json(ev.model_dump_json())
    assert restored == ev


def test_add_user_message_round_trip_through_union() -> None:
    ev = AddUserMessage.model_validate(
        {"message": _user_message()}
    )  # type defaults to "user_message.add"
    restored = _CLIENT_ADAPTER.validate_json(ev.model_dump_json())
    assert restored == ev


# --------------------------------------------------------------------------- #
# CreateResponse per-request overrides (model / thinking_level)
# --------------------------------------------------------------------------- #


def test_create_response_overrides_default_none() -> None:
    """``model`` / ``thinking_level`` default to None (session-bound default)."""
    ev = CreateResponse()
    assert ev.model is None
    assert ev.thinking_level is None


def test_create_response_overrides_round_trip() -> None:
    ev = CreateResponse(model="gpt-test", thinking_level="high")
    restored = _CLIENT_ADAPTER.validate_json(ev.model_dump_json())
    assert isinstance(restored, CreateResponse)
    assert restored == ev
    assert restored.model == "gpt-test"
    assert restored.thinking_level == "high"


# --------------------------------------------------------------------------- #
# New stateful-connection session ops: compaction + branch
# --------------------------------------------------------------------------- #


def test_create_compaction_round_trip() -> None:
    ev = CreateCompaction(first_kept_item_id="i1", custom_instructions="be brief", summary="s")
    restored = _CLIENT_ADAPTER.validate_json(ev.model_dump_json())
    assert isinstance(restored, CreateCompaction)
    assert restored == ev


def test_branch_move_requires_at_item_id() -> None:
    with pytest.raises(ValidationError):
        _CLIENT_ADAPTER.validate_python({"type": "branch.move"})


def test_branch_move_round_trip() -> None:
    ev = BranchMove(at_item_id="i1", summary="went back")
    restored = _CLIENT_ADAPTER.validate_json(ev.model_dump_json())
    assert isinstance(restored, BranchMove)
    assert restored == ev


def test_branch_moved_requires_at_item_id() -> None:
    """``BranchMoved`` echoes the request target, so ``at_item_id`` is required
    even on the refusal path — same invariant as the request ``BranchMove``."""
    with pytest.raises(ValidationError):
        _SERVER_ADAPTER.validate_python({"type": "branch.moved"})


def test_compaction_done_success_round_trip() -> None:
    ev = CompactionDone(
        summary="s",
        summary_item_id="c1",
        first_kept_item_id="i1",
        removed_item_ids=["a", "b"],
        tokens_before=100,
        usage=_usage(),
    )
    restored = _SERVER_ADAPTER.validate_json(ev.model_dump_json())
    assert isinstance(restored, CompactionDone)
    assert restored == ev
    assert restored.error_message is None


def test_compaction_done_error_path_defaults() -> None:
    """A bare ``compaction.done`` is constructible for the refusal path."""
    ev = CompactionDone(error_message="compaction unsupported")
    assert ev.summary is None
    assert ev.tokens_before is None
    restored = _SERVER_ADAPTER.validate_json(ev.model_dump_json())
    assert isinstance(restored, CompactionDone)
    assert restored.error_message == "compaction unsupported"


def test_branch_moved_success_round_trip() -> None:
    ev = BranchMoved(at_item_id="i1", removed_item_ids=["a"], summary_item_id="b1")
    restored = _SERVER_ADAPTER.validate_json(ev.model_dump_json())
    assert isinstance(restored, BranchMoved)
    assert restored == ev
    assert restored.error_message is None


def test_branch_moved_error_path() -> None:
    ev = BranchMoved(at_item_id="i1", error_message="branch unsupported")
    assert ev.removed_item_ids is None
    restored = _SERVER_ADAPTER.validate_json(ev.model_dump_json())
    assert isinstance(restored, BranchMoved)
    assert restored.error_message == "branch unsupported"


# --------------------------------------------------------------------------- #
# Typed aliases specialize the generic connection runtime
# --------------------------------------------------------------------------- #


def test_model_connection_aliases_specialize_connection() -> None:
    """The model aliases fix the two type params but are the generic handles."""
    assert ModelConnectionClient.__origin__ is ConnectionClient  # type: ignore[attr-defined]
    assert ModelConnectionBackend.__origin__ is ConnectionBackend  # type: ignore[attr-defined]
