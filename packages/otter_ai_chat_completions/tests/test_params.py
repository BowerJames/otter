"""Request body construction (``build_params``)."""

from __future__ import annotations

from typing import Any

from _helpers import make_model

from otter_ai import Context, TextContent, Tool, ToolResultMessage, UserMessage
from otter_ai_chat_completions import (
    ChatCompletionsCompat,
    ChatCompletionsModel,
    ChatTemplateKwargVar,
)
from otter_ai_chat_completions._compat import resolve_compat
from otter_ai_chat_completions._params import build_params


def _params(
    model: ChatCompletionsModel,
    compat: ChatCompletionsCompat | None = None,
    context: Context | None = None,
) -> dict[str, Any]:
    return build_params(
        model,
        context
        or Context(messages=[UserMessage(role="user", content="hi", timestamp=0)]),
        resolve_compat(compat),
    )


# --------------------------------------------------------------------------- #
# Core params
# --------------------------------------------------------------------------- #


def test_basic_params_shape() -> None:
    params = _params(make_model())
    assert params["model"] == "gpt-4o"
    assert params["stream"] is True
    assert params["stream_options"] == {"include_usage": True}
    assert params["store"] is False
    assert params["messages"][0]["role"] == "user"


def test_max_completion_tokens_field_by_default() -> None:
    model = make_model(request_max_tokens=512)
    params = _params(model)
    assert params["max_completion_tokens"] == 512
    assert "max_tokens" not in params


def test_max_tokens_field_when_compat_overridden() -> None:
    model = make_model(request_max_tokens=512)
    params = _params(model, ChatCompletionsCompat(max_tokens_field="max_tokens"))
    assert params["max_tokens"] == 512
    assert "max_completion_tokens" not in params


def test_temperature_emitted() -> None:
    params = _params(make_model(temperature=0.7))
    assert params["temperature"] == 0.7


def test_tool_choice_emitted() -> None:
    params = _params(make_model(tool_choice="auto"))
    assert params["tool_choice"] == "auto"


def test_store_omitted_when_unsupported() -> None:
    params = _params(make_model(), ChatCompletionsCompat(supports_store=False))
    assert "store" not in params


def test_stream_options_omitted_when_unsupported() -> None:
    params = _params(
        make_model(), ChatCompletionsCompat(supports_usage_in_streaming=False)
    )
    assert "stream_options" not in params


def test_tools_present_when_context_has_tools() -> None:
    from pydantic import BaseModel

    class P(BaseModel):
        x: int

    ctx = Context(
        messages=[UserMessage(role="user", content="x", timestamp=0)],
        tools=[Tool(name="add", description="d", parameters=P)],
    )
    params = _params(make_model(), context=ctx)
    assert params["tools"][0]["function"]["name"] == "add"


def test_empty_tools_when_tool_history_present() -> None:
    # Anthropic-via-proxy requires the tools param when tool history exists.
    ctx = Context(
        messages=[
            UserMessage(role="user", content="x", timestamp=0),
            ToolResultMessage(
                role="tool_result",
                tool_call_id="c1",
                tool_name="add",
                content=[TextContent(type="text", text="1")],
                is_error=False,
                timestamp=0,
            ),
        ]
    )
    params = _params(make_model(), context=ctx)
    assert params["tools"] == []


# --------------------------------------------------------------------------- #
# Thinking formats (all 10)
# --------------------------------------------------------------------------- #


def test_thinking_openai_reasoning_effort() -> None:
    params = _params(
        make_model(reasoning=True, reasoning_effort="medium"),
    )
    assert params["reasoning_effort"] == "medium"


def test_thinking_openai_applies_level_map() -> None:
    params = _params(
        make_model(
            reasoning=True,
            reasoning_effort="medium",
            thinking_level_map={"off": "low", "medium": "HIGH"},
        ),
    )
    assert params["reasoning_effort"] == "HIGH"


def test_thinking_openrouter_format() -> None:
    params = _params(
        make_model(reasoning=True, reasoning_effort="high"),
        ChatCompletionsCompat(thinking_format="openrouter"),
    )
    assert params["reasoning"] == {"effort": "high"}


def test_thinking_deepseek_format() -> None:
    params = _params(
        make_model(reasoning=True, reasoning_effort="low"),
        ChatCompletionsCompat(thinking_format="deepseek"),
    )
    assert params["thinking"] == {"type": "enabled"}
    assert params["reasoning_effort"] == "low"


def test_thinking_together_format() -> None:
    params = _params(
        make_model(reasoning=True, reasoning_effort="low"),
        ChatCompletionsCompat(thinking_format="together"),
    )
    assert params["reasoning"] == {"enabled": True}
    assert params["reasoning_effort"] == "low"


def test_thinking_zai_format() -> None:
    params = _params(
        make_model(reasoning=True, reasoning_effort="low"),
        ChatCompletionsCompat(thinking_format="zai"),
    )
    assert params["thinking"] == {"type": "enabled"}
    assert params["reasoning_effort"] == "low"


def test_thinking_qwen_format() -> None:
    params = _params(
        make_model(reasoning=True, reasoning_effort="low"),
        ChatCompletionsCompat(thinking_format="qwen"),
    )
    assert params["enable_thinking"] is True


def test_thinking_qwen_chat_template_format() -> None:
    params = _params(
        make_model(reasoning=True, reasoning_effort="low"),
        ChatCompletionsCompat(thinking_format="qwen-chat-template"),
    )
    assert params["chat_template_kwargs"] == {
        "enable_thinking": True,
        "preserve_thinking": True,
    }


def test_thinking_chat_template_format_resolves_vars() -> None:
    params = _params(
        make_model(reasoning=True, reasoning_effort="medium"),
        ChatCompletionsCompat(
            thinking_format="chat-template",
            chat_template_kwargs={
                "enable": ChatTemplateKwargVar(var="thinking.enabled"),
                "effort": ChatTemplateKwargVar(var="thinking.effort"),
                "static": "literal",
            },
        ),
    )
    assert params["chat_template_kwargs"] == {
        "enable": True,
        "effort": "medium",
        "static": "literal",
    }


def test_thinking_chat_template_effort_omit_when_off() -> None:
    params = _params(
        make_model(reasoning=True),  # no reasoning_effort
        ChatCompletionsCompat(
            thinking_format="chat-template",
            chat_template_kwargs={
                "enable": ChatTemplateKwargVar(var="thinking.enabled"),
                "effort": ChatTemplateKwargVar(
                    var="thinking.effort", omit_when_off=True
                ),
            },
        ),
    )
    # effort is omitted (omit_when_off + no effort); enable resolves to False.
    assert params["chat_template_kwargs"] == {"enable": False}


def test_thinking_string_thinking_format() -> None:
    params = _params(
        make_model(reasoning=True, reasoning_effort="high"),
        ChatCompletionsCompat(thinking_format="string-thinking"),
    )
    assert params["thinking"] == "high"


def test_thinking_ant_ling_format() -> None:
    params = _params(
        make_model(reasoning=True, reasoning_effort="medium"),
        ChatCompletionsCompat(thinking_format="ant-ling"),
    )
    assert params["reasoning"] == {"effort": "medium"}


def test_no_thinking_fields_when_model_not_reasoning() -> None:
    params = _params(make_model(reasoning=False, reasoning_effort="medium"))
    assert "reasoning_effort" not in params
    assert "thinking" not in params
    assert "reasoning" not in params


# --------------------------------------------------------------------------- #
# Cache shaping
# --------------------------------------------------------------------------- #


def test_openai_prompt_cache_key_on_openai_baseurl() -> None:
    params = _params(
        make_model(session_id="sess-123"),
    )
    assert params["prompt_cache_key"] == "sess-123"


def test_openai_prompt_cache_key_none_when_retention_none() -> None:
    params = _params(make_model(session_id="sess-123", cache_retention="none"))
    assert "prompt_cache_key" not in params


def test_anthropic_cache_control_markers() -> None:
    from otter_ai import Tool

    ctx = Context(
        system_prompt="system",
        messages=[UserMessage(role="user", content="hi", timestamp=0)],
        tools=[Tool(name="t", description="d", parameters={"type": "object"})],
    )
    params = _params(
        make_model(),
        ChatCompletionsCompat(cache_control_format="anthropic"),
        context=ctx,
    )
    # cache_control lands on the system message's text content.
    system_msg = params["messages"][0]
    assert isinstance(system_msg["content"], list)
    assert system_msg["content"][0]["cache_control"] == {"type": "ephemeral"}
    # And on the last tool definition.
    assert params["tools"][-1]["function"]["cache_control"] == {"type": "ephemeral"}


def test_anthropic_cache_control_long_retention_ttl() -> None:
    ctx = Context(messages=[UserMessage(role="user", content="hi", timestamp=0)])
    params = _params(
        make_model(cache_retention="long"),
        ChatCompletionsCompat(
            cache_control_format="anthropic", supports_long_cache_retention=True
        ),
        context=ctx,
    )
    user_msg = params["messages"][-1]
    assert isinstance(user_msg["content"], list)
    assert user_msg["content"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #


def test_openrouter_routing_emitted_as_provider() -> None:
    params = _params(
        make_model(),
        ChatCompletionsCompat(openrouter_routing={"only": ["anthropic"]}),
    )
    assert params["provider"] == {"only": ["anthropic"]}


def test_vercel_gateway_routing() -> None:
    params = _params(
        make_model(base_url="https://ai-gateway.vercel.sh/v1"),
        ChatCompletionsCompat(vercel_gateway_routing={"order": ["openai"]}),
    )
    assert params["providerOptions"] == {"gateway": {"order": ["openai"]}}
