"""A conversation with a model served over an OpenAI-compatible chat completions endpoint."""

import json
from collections.abc import Sequence
from typing import assert_never

from openai import AsyncOpenAI, omit
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionContentPartParam,
    ChatCompletionFunctionToolParam,
    ChatCompletionMessageParam,
)

from otter.messages import (
    AssistantMessage,
    AssistantPart,
    AudioPart,
    ContextEntry,
    ImagePart,
    ImageUrlPart,
    TextPart,
    ThinkingPart,
    ToolCall,
    ToolResultMessage,
    ToolSpec,
    UserMessage,
    UserPart,
)


class OpenAIChatCompletionsCompatibleConversation:
    """One conversation with one model: it holds the history and generates the next turn.

    The client decides which provider is spoken to (its base URL and API key); any
    provider serving the chat completions format will do. `system` is the system prompt
    the model sees ahead of every turn, and `tools` are the tools it may ask to have
    called. `context` is the history the conversation starts out with, oldest first; the
    thinking in its assistant turns is not sent.

    `supports_images` and `supports_audio` say what the model can take in. Where one is
    false, a part of that kind is not sent: a short text note saying it was omitted goes
    to the model in its place, so the conversation stays usable.

    An instance is a single conversation, so concurrent calls to `generate` on one
    instance are not supported.
    """

    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        *,
        system: str | None = None,
        tools: Sequence[ToolSpec] = (),
        context: Sequence[ContextEntry] = (),
        supports_images: bool = True,
        supports_audio: bool = True,
    ) -> None:
        self._client = client
        self._model = model
        self._supports_images = supports_images
        self._supports_audio = supports_audio
        # Kept in wire form: the history is only ever read back by the endpoint.
        self._messages: list[ChatCompletionMessageParam] = []
        if system is not None:
            self._messages.append({"role": "system", "content": system})
        self._tools: list[ChatCompletionFunctionToolParam] = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": dict(tool.parameters),
                },
            }
            for tool in tools
        ]
        for entry in context:
            match entry:
                case UserMessage():
                    self.add_user_message(entry.content)
                case AssistantMessage():
                    self._messages.append(_assistant_turn_on_the_wire(entry))
                case ToolResultMessage():
                    self.add_tool_result(entry.tool_call_id, entry.text)
                case _:
                    assert_never(entry)

    def add_user_message(self, content: Sequence[UserPart]) -> None:
        """Append a user turn; it is sent to the model on the next `generate`."""
        self._messages.append(
            {"role": "user", "content": [self._on_the_wire(part) for part in content]}
        )

    def _on_the_wire(self, part: UserPart) -> ChatCompletionContentPartParam:
        match part:
            case TextPart():
                return {"type": "text", "text": part.text}
            case ImagePart() | ImageUrlPart() if not self._supports_images:
                return {"type": "text", "text": "[image omitted: this model cannot view images]"}
            case ImagePart():
                return {
                    "type": "image_url",
                    "image_url": {"url": f"data:{part.media_type};base64,{part.data}"},
                }
            case ImageUrlPart():
                return {"type": "image_url", "image_url": {"url": part.url}}
            case AudioPart() if not self._supports_audio:
                return {"type": "text", "text": "[audio omitted: this model cannot hear audio]"}
            case AudioPart():
                return {
                    "type": "input_audio",
                    "input_audio": {"data": part.data, "format": part.format},
                }
            case _:
                assert_never(part)

    async def generate(self) -> AssistantMessage:
        """Send the conversation so far to the model and return the turn it produces.

        The returned turn joins the history. The conversation is sent as it stands: one
        the provider cannot accept, such as a tool call left without a result, is the
        provider's to reject. If the request fails, or the model's turn cannot be read
        (tool arguments that are not valid JSON raise `json.JSONDecodeError`), the error
        propagates and the history is left as it was.
        """
        completion = await self._client.chat.completions.create(
            model=self._model, messages=self._messages, tools=self._tools or omit
        )
        message = completion.choices[0].message
        calls = [call for call in message.tool_calls or [] if call.type == "function"]

        # Everything that can fail happens before the history is touched, so a turn that
        # cannot be read leaves the conversation as it was.
        content: list[AssistantPart] = []
        # Not part of the chat completions format: providers that show their reasoning
        # (Z.ai among them) add it to the message as this extra field.
        thinking = (message.model_extra or {}).get("reasoning_content")
        if isinstance(thinking, str) and thinking:
            content.append(ThinkingPart(thinking))
        if message.content:
            content.append(TextPart(message.content))
        content.extend(
            ToolCall(
                id=call.id, name=call.function.name, arguments=json.loads(call.function.arguments)
            )
            for call in calls
        )

        turn: ChatCompletionAssistantMessageParam = {"role": "assistant"}
        if message.content:
            turn["content"] = message.content
        if calls:
            # The arguments go back exactly as the model wrote them, not re-serialised.
            turn["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }
                for call in calls
            ]
        self._messages.append(turn)
        return AssistantMessage(content=tuple(content))

    def add_tool_result(self, tool_call_id: str, text: str) -> None:
        """Append the result of a tool call the model asked for in its last turn."""
        self._messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": text})


def _assistant_turn_on_the_wire(message: AssistantMessage) -> ChatCompletionAssistantMessageParam:
    turn: ChatCompletionAssistantMessageParam = {"role": "assistant"}
    texts = [part.text for part in message.content if isinstance(part, TextPart)]
    if texts:
        turn["content"] = "\n\n".join(texts)
    calls = [part for part in message.content if isinstance(part, ToolCall)]
    if calls:
        turn["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
            }
            for call in calls
        ]
    return turn
