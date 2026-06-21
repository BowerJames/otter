"""Context → Chat Completions wire translation."""

from __future__ import annotations

import json
from typing import Any

from _helpers import make_model

from otter_ai import (
    AssistantContent,
    AssistantMessage,
    ImageContent,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    Usage,
    UsageCost,
    UserMessage,
)
from otter_ai_chat_completions import ChatCompletionsCompat
from otter_ai_chat_completions._compat import ResolvedCompat, resolve_compat
from otter_ai_chat_completions._messages import (
    convert_messages,
    convert_tools,
    has_tool_history,
    transform_messages,
)


def _compat(**overrides: Any) -> ResolvedCompat:
    raw = ChatCompletionsCompat(**overrides) if overrides else None
    return resolve_compat(raw)


def _asst(*, content: list[AssistantContent] | None = None) -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=content or [],
        api="chat-completions",
        provider="openai",
        model="gpt-4o",
        usage=Usage(
            input=0,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost=UsageCost(input=0, output=0, cache_read=0, cache_write=0, total=0),
        ),
        stop_reason="stop",
        timestamp=0,
    )


# --------------------------------------------------------------------------- #
# transform_messages
# --------------------------------------------------------------------------- #


def test_transform_drops_errored_assistant_turn() -> None:
    model = make_model()
    errored = _asst(content=[TextContent(type="text", text="x")]).model_copy(
        update={"stop_reason": "error"}
    )
    good = _asst(content=[TextContent(type="text", text="y")])
    out = transform_messages(
        [UserMessage(role="user", content="hi", timestamp=0), errored, good], model
    )
    assert errored not in out
    assert good in out


def test_transform_synthesizes_missing_tool_result() -> None:
    model = make_model()
    call = ToolCall(type="tool_call", id="call_1", name="search", arguments={"q": "x"})
    asst = _asst(content=[call])
    out = transform_messages(
        [UserMessage(role="user", content="run", timestamp=0), asst], model
    )
    # The orphaned call gets a synthetic error tool result appended.
    assert any(
        isinstance(m, ToolResultMessage) and m.tool_call_id == "call_1" and m.is_error
        for m in out
    )


def test_transform_downgrades_images_for_non_vision_model() -> None:
    model = make_model(input_modalities=["text"])
    user = UserMessage(
        role="user",
        content=[
            TextContent(type="text", text="look"),
            ImageContent(type="image", data="AAA", mime_type="image/png"),
        ],
        timestamp=0,
    )
    out = transform_messages([user], model)
    transformed = out[0]
    assert isinstance(transformed, UserMessage)
    assert isinstance(transformed.content, list)
    assert all(isinstance(b, TextContent) for b in transformed.content)
    assert any(
        isinstance(b, TextContent) and "image omitted" in b.text
        for b in transformed.content
    )


def test_transform_keeps_images_for_vision_model() -> None:
    model = make_model(input_modalities=["text", "image"])
    user = UserMessage(
        role="user",
        content=[ImageContent(type="image", data="AAA", mime_type="image/png")],
        timestamp=0,
    )
    out = transform_messages([user], model)
    assert out == [user]


def test_transform_cross_model_thinking_becomes_text() -> None:
    # Same model id keeps the thinking block; a different model converts to text.
    same_model = make_model()
    cross_model = make_model(id="other-model")

    thinking = ThinkingContent(type="thinking", thinking="reasoning here")
    same_asst = _asst(content=[thinking])

    same_out = transform_messages([same_asst], same_model)
    same_msg = same_out[0]
    assert isinstance(same_msg, AssistantMessage)
    assert any(isinstance(b, ThinkingContent) for b in same_msg.content)

    cross_out = transform_messages([same_asst], cross_model)
    cross_msg = cross_out[0]
    assert isinstance(cross_msg, AssistantMessage)
    cross_blocks = cross_msg.content
    assert any(
        isinstance(b, TextContent) and b.text == "reasoning here" for b in cross_blocks
    )
    assert not any(isinstance(b, ThinkingContent) for b in cross_blocks)


# --------------------------------------------------------------------------- #
# convert_messages
# --------------------------------------------------------------------------- #


def test_system_prompt_becomes_system_role_by_default() -> None:
    model = make_model()
    params = convert_messages(
        model,
        "you are helpful",
        [UserMessage(role="user", content="hi", timestamp=0)],
        _compat(),
    )
    assert params[0] == {"role": "system", "content": "you are helpful"}


def test_system_prompt_becomes_developer_role_for_reasoning_model() -> None:
    model = make_model(reasoning=True)
    params = convert_messages(
        model,
        "you are helpful",
        [UserMessage(role="user", content="hi", timestamp=0)],
        _compat(),
    )
    assert params[0]["role"] == "developer"


def test_user_string_content_passes_through() -> None:
    model = make_model()
    params = convert_messages(
        model,
        None,
        [UserMessage(role="user", content="hi there", timestamp=0)],
        _compat(),
    )
    assert params == [{"role": "user", "content": "hi there"}]


def test_assistant_text_is_plain_string_not_array() -> None:
    # Sending ``[{type:"text", text:...}]`` is non-standard and some models
    # mirror the block structure; pi-ai always joins to a plain string.
    model = make_model()
    asst = _asst(content=[TextContent(type="text", text="hello")])
    params = convert_messages(
        model,
        None,
        [UserMessage(role="user", content="x", timestamp=0), asst],
        _compat(),
    )
    assistant_param = next(p for p in params if p["role"] == "assistant")
    assert isinstance(assistant_param["content"], str)
    assert assistant_param["content"] == "hello"


def test_assistant_tool_calls_serialized() -> None:
    model = make_model()
    asst = _asst(
        content=[ToolCall(type="tool_call", id="c1", name="add", arguments={"x": 1})]
    )
    params = convert_messages(
        model,
        None,
        [UserMessage(role="user", content="x", timestamp=0), asst],
        _compat(),
    )
    assistant_param = next(p for p in params if p["role"] == "assistant")
    assert assistant_param["tool_calls"] == [
        {
            "id": "c1",
            "type": "function",
            "function": {"name": "add", "arguments": json.dumps({"x": 1})},
        }
    ]


def test_empty_assistant_message_is_skipped() -> None:
    model = make_model()
    asst = _asst(content=[])  # no text, no tool calls
    params = convert_messages(
        model,
        None,
        [UserMessage(role="user", content="x", timestamp=0), asst],
        _compat(),
    )
    assert all(p["role"] != "assistant" for p in params)


def test_tool_result_becomes_tool_role() -> None:
    model = make_model()
    asst = _asst(
        content=[ToolCall(type="tool_call", id="c1", name="add", arguments={})]
    )
    result = ToolResultMessage(
        role="tool_result",
        tool_call_id="c1",
        tool_name="add",
        content=[TextContent(type="text", text="42")],
        is_error=False,
        timestamp=0,
    )
    params = convert_messages(
        model,
        None,
        [UserMessage(role="user", content="x", timestamp=0), asst, result],
        _compat(),
    )
    tool_param = next(p for p in params if p["role"] == "tool")
    assert tool_param == {"role": "tool", "content": "42", "tool_call_id": "c1"}


def test_tool_result_name_emitted_when_required() -> None:
    model = make_model()
    asst = _asst(
        content=[ToolCall(type="tool_call", id="c1", name="add", arguments={})]
    )
    result = ToolResultMessage(
        role="tool_result",
        tool_call_id="c1",
        tool_name="add",
        content=[TextContent(type="text", text="42")],
        is_error=False,
        timestamp=0,
    )
    params = convert_messages(
        model,
        None,
        [UserMessage(role="user", content="x", timestamp=0), asst, result],
        _compat(requires_tool_result_name=True),
    )
    tool_param = next(p for p in params if p["role"] == "tool")
    assert tool_param["name"] == "add"


def test_thinking_as_text_when_required() -> None:
    model = make_model(reasoning=True)
    thinking = ThinkingContent(type="thinking", thinking="my thoughts")
    text = TextContent(type="text", text="answer")
    asst = _asst(content=[thinking, text])
    params = convert_messages(
        model,
        None,
        [UserMessage(role="user", content="x", timestamp=0), asst],
        _compat(requires_thinking_as_text=True),
    )
    assistant_param = next(p for p in params if p["role"] == "assistant")
    # Thinking-as-text prepends the thinking content (plain string), no tags.
    assert "my thoughts" in assistant_param["content"]
    assert "answer" in assistant_param["content"]


def test_requires_assistant_after_tool_result_bridges_gap() -> None:
    model = make_model()
    asst = _asst(
        content=[ToolCall(type="tool_call", id="c1", name="add", arguments={})]
    )
    result = ToolResultMessage(
        role="tool_result",
        tool_call_id="c1",
        tool_name="add",
        content=[TextContent(type="text", text="42")],
        is_error=False,
        timestamp=0,
    )
    followup = UserMessage(role="user", content="thanks", timestamp=0)
    params = convert_messages(
        model,
        None,
        [UserMessage(role="user", content="x", timestamp=0), asst, result, followup],
        _compat(requires_assistant_after_tool_result=True),
    )
    roles = [p["role"] for p in params]
    # A synthetic assistant message bridges the tool_result -> user transition.
    # Find the tool position and assert an assistant then a user follow.
    tool_idx = roles.index("tool")
    assert roles[tool_idx + 1] == "assistant"
    assert roles[tool_idx + 2] == "user"


def test_tool_result_images_reinjected_as_user_message_for_vision_model() -> None:
    model = make_model(input_modalities=["text", "image"])
    asst = _asst(
        content=[ToolCall(type="tool_call", id="c1", name="snap", arguments={})]
    )
    result = ToolResultMessage(
        role="tool_result",
        tool_call_id="c1",
        tool_name="snap",
        content=[ImageContent(type="image", data="AAA", mime_type="image/png")],
        is_error=False,
        timestamp=0,
    )
    params = convert_messages(
        model,
        None,
        [UserMessage(role="user", content="x", timestamp=0), asst, result],
        _compat(),
    )
    # The tool message gets a placeholder text; the image is re-injected as a
    # following user message carrying an image_url part.
    user_with_image = next(
        p for p in params if p["role"] == "user" and isinstance(p["content"], list)
    )
    assert any(
        isinstance(part, dict) and part.get("type") == "image_url"
        for part in user_with_image["content"]
    )


# --------------------------------------------------------------------------- #
# convert_tools + has_tool_history
# --------------------------------------------------------------------------- #


def test_convert_tools_includes_strict_false_by_default() -> None:
    from pydantic import BaseModel

    from otter_ai import Tool

    class Params(BaseModel):
        x: int

    tools = [Tool(name="add", description="add", parameters=Params)]
    out = convert_tools(tools, _compat())
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "add"
    assert out[0]["function"]["strict"] is False


def test_convert_tools_omits_strict_when_unsupported() -> None:
    from otter_ai import Tool

    tools = [Tool(name="add", description="add", parameters={"type": "object"})]
    out = convert_tools(tools, _compat(supports_strict_mode=False))
    assert "strict" not in out[0]["function"]


def test_has_tool_history_detects_tool_result() -> None:
    assert has_tool_history(
        [
            ToolResultMessage(
                role="tool_result",
                tool_call_id="c1",
                tool_name="add",
                content=[TextContent(type="text", text="1")],
                is_error=False,
                timestamp=0,
            )
        ]
    )


def test_has_tool_history_detects_assistant_tool_call() -> None:
    assert has_tool_history(
        [_asst(content=[ToolCall(type="tool_call", id="c1", name="a", arguments={})])]
    )


def test_has_tool_history_false_for_plain_user() -> None:
    assert not has_tool_history([UserMessage(role="user", content="hi", timestamp=0)])
