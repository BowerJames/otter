"""JSON round-trip serialization of a rich Context."""

from __future__ import annotations

from otter_ai_core import (
    AssistantMessage,
    AssistantMessageDiagnostic,
    Context,
    ContextItem,
    DiagnosticErrorInfo,
    TextContent,
    ThinkingContent,
    Tool,
    ToolCall,
    ToolResultMessage,
    Usage,
    UsageCost,
    UserMessage,
)


def _usage() -> Usage:
    return Usage(
        input=100,
        output=42,
        cache_read=7,
        cache_write=3,
        cache_write_1h=1,
        total_tokens=152,
        cost=UsageCost(
            input=0.001,
            output=0.002,
            cache_read=0.0001,
            cache_write=0.0003,
            total=0.0034,
        ),
    )


def _rich_context() -> Context:
    return Context(
        system_prompt="You are helpful.",
        tools=[
            Tool(
                name="get_time",
                description="Get the time",
                parameters={"type": "object", "properties": {}},
            )
        ],
        items=[
            ContextItem(
                id="u1",
                message=UserMessage(
                    role="user", content="What time is it?", timestamp=1_700_000_000_000
                ),
            ),
            ContextItem(
                id="a1",
                message=AssistantMessage(
                    role="assistant",
                    content=[
                        ThinkingContent(
                            type="thinking",
                            thinking="reasoning",
                            thinking_signature="sig",
                        ),
                        ToolCall(
                            type="tool_call", id="t1", name="get_time", arguments={}
                        ),
                    ],
                    api="anthropic-messages",
                    provider="anthropic",
                    model="claude-3",
                    response_model="claude-3-real",
                    response_id="resp_1",
                    diagnostics=[
                        AssistantMessageDiagnostic(
                            type="retry",
                            timestamp=1_700_000_001_000,
                            error=DiagnosticErrorInfo(
                                name="RateLimitError", message="slow down"
                            ),
                            details={"attempt": 2},
                        )
                    ],
                    usage=_usage(),
                    stop_reason="tool_use",
                    timestamp=1_700_000_001_000,
                ),
            ),
            ContextItem(
                id="t1",
                message=ToolResultMessage(
                    role="tool_result",
                    tool_call_id="t1",
                    tool_name="get_time",
                    content=[TextContent(type="text", text="12:00")],
                    details={"raw": 1234},
                    is_error=False,
                    timestamp=1_700_000_002_000,
                ),
            ),
        ],
    )


def test_context_roundtrip_json() -> None:
    ctx = _rich_context()
    serialized = ctx.model_dump_json()
    restored = Context.model_validate_json(serialized)

    assert restored == ctx


def test_context_roundtrip_preserves_field_shapes() -> None:
    restored = Context.model_validate_json(_rich_context().model_dump_json())

    assistant = restored.items[1].message
    assert isinstance(assistant, AssistantMessage)
    assert isinstance(assistant.content[0], ThinkingContent)
    assert assistant.content[0].thinking_signature == "sig"
    assert isinstance(assistant.content[1], ToolCall)
    assert assistant.response_model == "claude-3-real"
    assert assistant.usage.cache_write_1h == 1
    assert assistant.diagnostics is not None
    assert assistant.diagnostics[0].details == {"attempt": 2}

    tool_result = restored.items[2].message
    assert isinstance(tool_result, ToolResultMessage)
    assert tool_result.details == {"raw": 1234}


def test_empty_context_roundtrip() -> None:
    ctx = Context()
    assert Context.model_validate_json(ctx.model_dump_json()) == ctx
